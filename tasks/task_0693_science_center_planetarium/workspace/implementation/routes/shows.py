"""ShowEvent endpoints (PRD §3.3)."""
from flask import Blueprint, request

from db import db, new_record, touch
from clock import parse_iso, iso
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_VALIDATION,
    ERR_VENUE_TYPE_MISMATCH,
    ERR_INVALID_TIME_WINDOW,
    ERR_SHOW_TIME_CONFLICT,
    ERR_INVALID_STATE,
)
from middleware import authenticate, require_role
from response import success
from services.common import (
    get_body,
    require_string,
    require_int,
    optional_int,
    validate_range,
    parse_pagination,
    paginate,
)
from services.lookups import get_venue, get_show
from services.serialize import show_view
from services.show_logic import recompute_seats_sold

bp = Blueprint("shows", __name__)


def _parse_dt(body, field):
    if field not in body or body[field] is None:
        raise err(ERR_INVALID_REQUEST, f"Missing required field: {field}")
    dt = parse_iso(body[field])
    if dt is None:
        raise err(ERR_INVALID_REQUEST, f"Field {field} is not a valid ISO8601 instant")
    return dt


@bp.route("/shows", methods=["POST"])
def create_show():
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    body = get_body()
    require_string(body, "venue_id")
    venue_id = body["venue_id"]
    title = require_string(body, "title")
    starts_at = _parse_dt(body, "starts_at")
    ends_at = _parse_dt(body, "ends_at")
    base_price = require_int(body, "base_price_cents")
    surcharge = optional_int(body, "feature_surcharge_cents", 0)

    with db.lock:
        # Existence (priority 3): venue must exist.
        venue = get_venue(venue_id)
        # Per PRD §3.10 the relevant priority order is: show-time conflict (9),
        # then venue-type (11), then strictly-after time-window (12), then the
        # generic field-range (20). Body parse / FK existence are already done.
        # Show-time conflict: [starts_at, ends_at)+buffer must not overlap any
        # other non-cancelled show in the same venue (priority 9).
        _check_show_conflict(venue, starts_at, ends_at)
        # Venue-type compatibility (priority 11).
        if venue["venue_type"] not in ("DOME", "THEATER"):
            raise err(ERR_VENUE_TYPE_MISMATCH, "Show requires a DOME or THEATER venue")
        # Time-window strictly-after (priority 12).
        if not (ends_at > starts_at):
            raise err(ERR_INVALID_TIME_WINDOW, "ends_at must be strictly after starts_at")
        # Field-range (priority 20).
        validate_range(base_price >= 0, "base_price_cents must be >= 0")
        validate_range(surcharge >= 0, "feature_surcharge_cents must be >= 0")

        rec = new_record(with_version=True)
        rec.update({
            "venue_id": venue_id,
            "title": title,
            "starts_at": iso(starts_at),
            "ends_at": iso(ends_at),
            "base_price_cents": base_price,
            "feature_surcharge_cents": surcharge,
            "seats_sold": 0,
            "status": "SCHEDULED",
            "_starts_at_dt": starts_at,
            "_ends_at_dt": ends_at,
        })
        # version begins at 1 (already set by new_record).
        db.shows[rec["id"]] = rec
    return success(show_view(rec), status=201)


def _check_show_conflict(venue, starts_at, ends_at):
    """A new show's [starts_at, ends_at) extended forward by the venue's
    turnover_buffer_minutes must not overlap any non-cancelled show in the
    same venue (PRD §2.10).
    """
    from datetime import timedelta
    buffer = timedelta(minutes=venue["turnover_buffer_minutes"])
    new_start = starts_at
    new_end = ends_at + buffer
    for s in db.shows.values():
        if s["venue_id"] != venue["id"]:
            continue
        if s["status"] == "CANCELLED":
            continue
        ex_start = s["_starts_at_dt"]
        ex_end = s["_ends_at_dt"] + timedelta(minutes=venue["turnover_buffer_minutes"])
        # Half-open overlap with buffer extension on both sides.
        if new_start < ex_end and ex_start < new_end:
            raise err(ERR_SHOW_TIME_CONFLICT, "Show window+buffer overlaps an existing show")


@bp.route("/shows", methods=["GET"])
def list_shows():
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator", "GroupSalesAgent", "FacilityAdmin"})
    limit, offset = parse_pagination()
    venue_id = request.args.get("venue_id")
    status = request.args.get("status")
    with db.lock:
        records = list(db.shows.values())
        if venue_id is not None:
            records = [s for s in records if s["venue_id"] == venue_id]
        if status is not None:
            records = [s for s in records if s["status"] == status]
        page, meta = paginate(records, limit, offset)
        data = [show_view(s) for s in page]
    return success(data, status=200, pagination=meta)


@bp.route("/shows/<sid>", methods=["GET"])
def get_one_show(sid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator", "GroupSalesAgent", "AccessibilityCoordinator"})
    with db.lock:
        s = get_show(sid)
        return success(show_view(s), status=200)


@bp.route("/shows/<sid>/open", methods=["POST"])
def open_show(sid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    with db.lock:
        s = get_show(sid)
        # Permitted only while SCHEDULED and clock < starts_at.
        if s["status"] != "SCHEDULED":
            raise err(ERR_INVALID_STATE, "Show must be SCHEDULED to open")
        if not (db.clock.now < s["_starts_at_dt"]):
            raise err(ERR_INVALID_STATE, "Show start time has passed")
        s["status"] = "OPEN"
        touch(s)
        return success(show_view(s), status=200)


@bp.route("/shows/<sid>/cancel", methods=["POST"])
def cancel_show(sid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    with db.lock:
        s = get_show(sid)
        if s["status"] not in ("SCHEDULED", "OPEN", "SOLD_OUT"):
            raise err(ERR_INVALID_STATE, "Show not in a cancellable state")
        if s["status"] != "SCHEDULED":
            # Depth-3 cascade: bookings -> CANCELLED, accommodations -> DENIED.
            for b in db.show_bookings.values():
                if b["show_event_id"] == s["id"] and b["status"] in ("HELD", "CONFIRMED"):
                    b["status"] = "CANCELLED"
                    touch(b)
                    # Hop 2: linked accommodations SUBMITTED/APPROVED -> DENIED.
                    for a in db.accommodations.values():
                        if a.get("show_booking_id") == b["id"] and a["status"] in ("SUBMITTED", "APPROVED"):
                            a["status"] = "DENIED"
                            touch(a)
            s["seats_sold"] = 0
        s["status"] = "CANCELLED"
        touch(s)
        return success(show_view(s), status=200)


@bp.route("/shows/<sid>/complete", methods=["POST"])
def complete_show(sid):
    _, role = authenticate()
    require_role(role, {"BoxOfficeOperator"})
    with db.lock:
        s = get_show(sid)
        # Permitted from OPEN or SOLD_OUT and only once clock >= ends_at.
        if s["status"] not in ("OPEN", "SOLD_OUT"):
            raise err(ERR_INVALID_STATE, "Show must be OPEN or SOLD_OUT to complete")
        if not (db.clock.now >= s["_ends_at_dt"]):
            raise err(ERR_INVALID_STATE, "Show has not ended yet")
        # Every HELD booking -> CANCELLED (no-show); CONFIRMED stay consumed.
        for b in db.show_bookings.values():
            if b["show_event_id"] == s["id"] and b["status"] == "HELD":
                b["status"] = "CANCELLED"
                touch(b)
        recompute_seats_sold(s)
        s["status"] = "COMPLETED"
        touch(s)
        return success(show_view(s), status=200)
