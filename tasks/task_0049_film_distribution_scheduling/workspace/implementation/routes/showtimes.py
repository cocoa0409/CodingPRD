"""Showtime endpoints: create, get, list, cancel."""

from flask import Blueprint, request

from db import db, new_id
from clock import now_iso, now_dt
from middleware import (
    require_roles,
    get_auth,
    parse_json_body,
    require_fields,
    require_int,
    require_str,
    require_enum,
)
from response import success_object, success_array
from errors import (
    ERR_NOT_FOUND,
    ERR_REFERENCED_ENTITY_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_BAD_REQUEST,
    ERR_SCREEN_FORMAT_MISMATCH,
    ERR_REGION_STRATEGY_VIOLATION,
    ERR_SCREEN_TIME_CONFLICT,
    ERR_OUTSIDE_OPERATING_HOURS,
    ERR_COMPETING_FILM_CONFLICT,
    ERR_MIN_SHOW_COUNT_BREACH,
    raise_error,
)
from datetime_utils import parse_iso8601, iso_week_label
from services.audit import append_audit
from services.calculations import compute_block_and_end_minutes, COMPETING_PEAK_CAP, attendance_is_low
from services.cascade import cascade_showtime_cancel
from services.pagination import parse_pagination, paginate, sort_by_created_at_asc
from services.version_check import check_version, check_idempotent_action

bp = Blueprint("showtimes", __name__)


CANCEL_REASONS = {"LOW_ATTENDANCE", "NEW_FILM_INSERTION", "INCIDENT"}
LIFECYCLE_STATUSES = {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
SALE_STATUSES = {"PRESALE", "ON_SALE", "CLOSED"}


def _serialize(s):
    return dict(s)


def _validate_screen_time_conflict(new_start, new_end, screen_id, business_date_str, cleaning):
    """Check conflicts on the same screen and business_date for non-cancelled showtimes."""
    for s in db.showtimes.values():
        if s["screen_id"] != screen_id:
            continue
        if s["lifecycle_status"] == "CANCELLED":
            continue
        if s["business_date"] != business_date_str:
            continue
        other_start = s["start_minute"]
        other_end = s["end_minute"]
        # Earlier show's interval (cleaning attached to its right side):
        # [other_start, other_end + cleaning) must not overlap [new_start, new_end)
        # AND the new show's interval [new_start, new_end + cleaning) must not overlap
        # [other_start, other_end). Use half-open intervals and apply buffer correctly.
        # The buffer is attached to the right of the earlier showtime — meaning for any pair,
        # the later one must start at or after earlier's end + cleaning.
        # Simplest: compute occupied intervals with buffer on right; check overlap.
        a_start = other_start
        a_end = other_end + cleaning
        b_start = new_start
        b_end = new_end + cleaning
        if a_start < b_end and b_start < a_end:
            raise_error(ERR_SCREEN_TIME_CONFLICT, "screen time conflict")


def _validate_region_strategy(film, cinema):
    rs = film["region_strategy"]
    allowed = rs.get("allowed_regions", [])
    if cinema["region_code"] not in allowed:
        raise_error(ERR_REGION_STRATEGY_VIOLATION, "cinema region not in allowed_regions")
    tier_caps = rs.get("tier_caps", {})
    cap = tier_caps.get(cinema["tier"])
    if cap is None:
        raise_error(ERR_REGION_STRATEGY_VIOLATION, "no tier_cap for cinema tier")
    # Count distinct cinemas in this tier already hosting this film in SCHEDULED-or-later state
    cinemas_hosting = set()
    for s in db.showtimes.values():
        if s["film_id"] != film["id"]:
            continue
        # SCHEDULED or later (i.e., NOT CANCELLED only for ordering — but spec says
        # "active SCHEDULED-or-later cinemas count" — we include SCHEDULED/IN_PROGRESS/COMPLETED)
        if s["lifecycle_status"] in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            other_cin = db.cinemas.get(s["cinema_id"])
            if other_cin and other_cin["tier"] == cinema["tier"]:
                cinemas_hosting.add(s["cinema_id"])
    # The current cinema being added counts; if it's already hosting, no change
    cinemas_hosting.add(cinema["id"])
    if len(cinemas_hosting) > cap:
        raise_error(ERR_REGION_STRATEGY_VIOLATION, "tier cap exceeded")


def _validate_competing_film(cinema, distributor_id, business_date_str, start_minute):
    """At most COMPETING_PEAK_CAP=1 showtime per distributor with start_minute inside the
    peak window (closed-closed inclusion) per business_date per cinema.
    """
    p_start = cinema["peak_window_start_minute"]
    p_end = cinema["peak_window_end_minute"]
    # Check if new start is inside peak window (closed-closed)
    if not (p_start <= start_minute <= p_end):
        return  # not in peak window
    # count existing showtimes
    count = 0
    for s in db.showtimes.values():
        if s["cinema_id"] != cinema["id"]:
            continue
        if s["distributor_id"] != distributor_id:
            continue
        if s["business_date"] != business_date_str:
            continue
        if s["lifecycle_status"] == "CANCELLED":
            continue
        if p_start <= s["start_minute"] <= p_end:
            count += 1
    if count >= COMPETING_PEAK_CAP:
        raise_error(ERR_COMPETING_FILM_CONFLICT, "competing-film peak density cap exceeded")


@bp.route("/screens/<screen_id>/showtimes", methods=["POST"])
@require_roles({"CinemaOps"})
def create_showtime(screen_id):
    role, user_id = get_auth()
    # Path existence
    screen = db.screens.get(screen_id)
    if not screen:
        raise_error(ERR_NOT_FOUND, "screen not found")
    cinema = db.cinemas.get(screen["cinema_id"])
    if not cinema:
        raise_error(ERR_NOT_FOUND, "parent cinema not found")

    body = parse_json_body()
    require_fields(body, ["film_id", "start_minute", "business_date", "ticket_price_cents", "presale_opens_at"])
    film_id = require_str(body.get("film_id"), "film_id")
    start_minute = require_int(body.get("start_minute"), "start_minute", min_v=0, max_v=1439)
    business_date_str = require_str(body.get("business_date"), "business_date")
    business_dt = parse_iso8601(business_date_str, "business_date")
    ticket_price_cents = require_int(body.get("ticket_price_cents"), "ticket_price_cents", min_v=0)
    presale_opens_at_str = require_str(body.get("presale_opens_at"), "presale_opens_at")
    parse_iso8601(presale_opens_at_str, "presale_opens_at")

    # FK existence
    film = db.films.get(film_id)
    if not film:
        raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "film not found")
    distributor = db.distributors.get(film["distributor_id"])
    if not distributor:
        raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "distributor not found")

    # State: spec doesn't require film to be RELEASED at creation — showtimes can be created
    # for PLANNED films and will block sale until release. But DELISTED should be rejected.
    if film["status"] == "DELISTED":
        raise_error(ERR_INVALID_STATE, "film is DELISTED")

    # Compute block/end before validations 9-13
    block_minutes, end_minute = compute_block_and_end_minutes(film, screen, start_minute)

    # Priority 9: format match
    if film["format"] not in screen["supported_formats"]:
        raise_error(ERR_SCREEN_FORMAT_MISMATCH, "film format not supported by screen")

    # Priority 10: region strategy
    _validate_region_strategy(film, cinema)

    # Priority 11: screen time conflict (with cleaning buffer)
    _validate_screen_time_conflict(start_minute, end_minute, screen_id, business_date_str, screen["cleaning_interval_minutes"])

    # Priority 12: operating hours
    if start_minute < screen["operating_start_minute"] or end_minute > screen["operating_end_minute"]:
        raise_error(ERR_OUTSIDE_OPERATING_HOURS, "outside operating hours")

    # Priority 13: competing-film coordination
    _validate_competing_film(cinema, film["distributor_id"], business_date_str, start_minute)

    now = now_iso()
    showtime = {
        "id": new_id(),
        "screen_id": screen_id,
        "cinema_id": cinema["id"],
        "film_id": film_id,
        "distributor_id": film["distributor_id"],
        "start_minute": start_minute,
        "business_date": business_date_str,
        "block_minutes": block_minutes,
        "end_minute": end_minute,
        "ticket_price_cents": ticket_price_cents,
        "presale_opens_at": presale_opens_at_str,
        "sale_status": "PRESALE",
        "lifecycle_status": "SCHEDULED",
        "tickets_sold_count": 0,
        "tickets_refunded_count": 0,
        "gross_box_office_cents": 0,
        "anomaly_flag": False,
        "cancel_reason": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.showtimes[showtime["id"]] = showtime
    append_audit(role, user_id, "SHOWTIME_CREATE", "Showtime", showtime["id"], _serialize(showtime))
    return success_object(_serialize(showtime), http_status=201)


@bp.route("/showtimes/<showtime_id>", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def get_showtime(showtime_id):
    s = db.showtimes.get(showtime_id)
    if not s:
        raise_error(ERR_NOT_FOUND, "showtime not found")
    return success_object(_serialize(s))


@bp.route("/showtimes", methods=["GET"])
@require_roles({"PlatformAdmin", "DistributorOps", "CinemaOps", "FinanceOps", "Auditor"})
def list_showtimes():
    limit, offset = parse_pagination()
    cinema_id = request.args.get("cinema_id")
    film_id = request.args.get("film_id")
    business_date = request.args.get("business_date")
    lifecycle_status = request.args.get("lifecycle_status")
    sale_status = request.args.get("sale_status")

    if lifecycle_status is not None and lifecycle_status not in LIFECYCLE_STATUSES:
        raise_error(ERR_BAD_REQUEST, "invalid lifecycle_status filter")
    if sale_status is not None and sale_status not in SALE_STATUSES:
        raise_error(ERR_BAD_REQUEST, "invalid sale_status filter")

    items = []
    for s in db.showtimes.values():
        if cinema_id is not None and s["cinema_id"] != cinema_id:
            continue
        if film_id is not None and s["film_id"] != film_id:
            continue
        if business_date is not None and s["business_date"] != business_date:
            continue
        if lifecycle_status is not None and s["lifecycle_status"] != lifecycle_status:
            continue
        if sale_status is not None and s["sale_status"] != sale_status:
            continue
        items.append(_serialize(s))
    items = sort_by_created_at_asc(items)
    page, total = paginate(items, limit, offset)
    return success_array(page, limit, offset, total)


def _weekly_min_count_after_cancel(showtime):
    """Count of other showtimes for same cinema_id/distributor in same ISO-week not CANCELLED."""
    business_dt = parse_iso8601(showtime["business_date"], "business_date")
    target_week = iso_week_label(business_dt)
    distributor_id = showtime["distributor_id"]
    cinema_id = showtime["cinema_id"]
    count = 0
    for s in db.showtimes.values():
        if s["id"] == showtime["id"]:
            continue
        if s["cinema_id"] != cinema_id:
            continue
        if s["distributor_id"] != distributor_id:
            continue
        if s["lifecycle_status"] not in ("SCHEDULED", "IN_PROGRESS", "COMPLETED"):
            continue
        s_dt = parse_iso8601(s["business_date"], "business_date")
        if iso_week_label(s_dt) != target_week:
            continue
        count += 1
    return count


@bp.route("/showtimes/<showtime_id>/cancel", methods=["POST"])
@require_roles({"CinemaOps"})
def cancel_showtime(showtime_id):
    role, user_id = get_auth()
    showtime = db.showtimes.get(showtime_id)
    if not showtime:
        raise_error(ERR_NOT_FOUND, "showtime not found")
    body = parse_json_body()
    requested_version = body.get("version")
    if requested_version is not None and (isinstance(requested_version, bool) or not isinstance(requested_version, int)):
        raise_error(ERR_BAD_REQUEST, "version must be integer")
    cancel_reason = require_enum(body.get("cancel_reason"), "cancel_reason", CANCEL_REASONS)
    exchange_to_showtime_id = body.get("exchange_to_showtime_id")
    if exchange_to_showtime_id is not None and not isinstance(exchange_to_showtime_id, str):
        raise_error(ERR_BAD_REQUEST, "exchange_to_showtime_id must be string")

    # Validate exchange target FK if supplied (priority 4 — referenced entity existence)
    if exchange_to_showtime_id:
        dest = db.showtimes.get(exchange_to_showtime_id)
        if not dest:
            raise_error(ERR_REFERENCED_ENTITY_NOT_FOUND, "exchange target not found")

    # State (priority 5): only SCHEDULED can be cancelled. PRD §2.9 places
    # state-machine admissibility (priority 5) ABOVE both
    # min_show_count_breach (priority 16) and duplicate-operation (priority
    # 17), so a cancel against a non-SCHEDULED row is rejected with
    # ERR_INVALID_STATE before either lower priority fires. The §3.7
    # special-case ("returns ERR_MIN_SHOW_COUNT_BREACH rather than
    # ERR_DUPLICATE_OPERATION") only swaps priorities WITHIN the lower
    # tier and does not promote min-breach above the state check.
    if showtime["lifecycle_status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "showtime cannot be cancelled from current state")

    # LOW_ATTENDANCE precondition (still part of state check, priority 5)
    if cancel_reason == "LOW_ATTENDANCE":
        screen = db.screens.get(showtime["screen_id"])
        if not screen:
            raise_error(ERR_INVALID_STATE, "screen missing")
        if not attendance_is_low(showtime["gross_box_office_cents"], screen["seat_capacity"], showtime["ticket_price_cents"]):
            raise_error(ERR_INVALID_STATE, "attendance not low")

    # Exchange target compatibility (state-level check on destination)
    if exchange_to_showtime_id:
        dest = db.showtimes.get(exchange_to_showtime_id)
        if dest["lifecycle_status"] != "SCHEDULED" or dest["sale_status"] not in ("PRESALE", "ON_SALE"):
            from errors import ERR_EXCHANGE_TARGET_INVALID
            raise_error(ERR_EXCHANGE_TARGET_INVALID, "exchange target not in valid state")

    # Priority 16: weekly min show count check (unless INCIDENT)
    if cancel_reason != "INCIDENT":
        distributor = db.distributors.get(showtime["distributor_id"])
        if distributor:
            remaining = _weekly_min_count_after_cancel(showtime)
            if remaining < distributor["min_show_count_per_week"]:
                raise_error(ERR_MIN_SHOW_COUNT_BREACH, "weekly min show count would be breached")

    # Version check (priority 18)
    check_version(showtime["version"], requested_version)

    # Apply
    showtime["lifecycle_status"] = "CANCELLED"
    showtime["sale_status"] = "CLOSED"
    showtime["cancel_reason"] = cancel_reason
    showtime["updated_at"] = now_iso()
    showtime["version"] = showtime["version"] + 1

    cascade_showtime_cancel(showtime, cancel_reason, exchange_to_showtime_id, role, user_id)

    append_audit(role, user_id, "SHOWTIME_CANCEL", "Showtime", showtime["id"], {"cancel_reason": cancel_reason})
    return success_object(_serialize(showtime))
