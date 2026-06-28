"""Talent endpoints and lifecycle (PRD §3.1, §3.4 availability summary)."""
from flask import Blueprint, request

from db import db, lock
from errors import ApiError
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import (
    mint_common,
    touch,
    public,
    get_json_body,
    require_str,
    require_enum,
    require_int,
    lookup,
    paginate,
)
from timeutil import inclusive_day_span, require_dt

bp = Blueprint("talents", __name__)

ALL_ROLES = {"Agent", "CastingDirector", "Talent"}
UNION_STATUSES = {"SAG", "NON_UNION"}
TALENT_STATUSES = {"PROSPECT", "ROSTERED", "SUSPENDED", "ARCHIVED"}


@bp.route("/talents", methods=["POST"])
def create_talent():
    _, role = get_identity()
    require_role(role, {"Agent"})
    body = get_json_body()
    agency_id = require_str(body, "agency_id")
    full_name = require_str(body, "full_name")
    union_status = require_enum(body, "union_status", UNION_STATUSES)
    scale_rate_cents = require_int(body, "scale_rate_cents", minimum=0)
    with lock:
        lookup("Agency", agency_id)
        record = mint_common({
            "agency_id": agency_id,
            "full_name": full_name,
            "union_status": union_status,
            "status": "PROSPECT",
            "scale_rate_cents": scale_rate_cents,
            "booked_day_count": 0,
        })
        db.talents[record["id"]] = record
        return object_response(public(record), status=201)


@bp.route("/talents", methods=["GET"])
def list_talents():
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        items = list(db.talents.values())
        agency_id = request.args.get("agency_id")
        if agency_id is not None:
            items = [t for t in items if t["agency_id"] == agency_id]
        status = request.args.get("status")
        if status is not None:
            items = [t for t in items if t["status"] == status]
        page, limit, offset, total = paginate(items)
        return array_response(page, limit, offset, total)


@bp.route("/talents/<talent_id>", methods=["GET"])
def get_talent(talent_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        record = lookup("Talent", talent_id)
        return object_response(public(record), status=200)


@bp.route("/talents/<talent_id>/availability-summary", methods=["GET"])
def availability_summary(talent_id):
    _, role = get_identity()
    require_role(role, ALL_ROLES)
    with lock:
        lookup("Talent", talent_id)
        holds = [
            h for h in db.availability_holds.values()
            if h["talent_id"] == talent_id and h["status"] == "ACTIVE"
        ]
        projected = sum(
            inclusive_day_span(require_dt(h["start_date"]), require_dt(h["end_date"]))
            for h in holds
        )
        committed = _committed_days(holds)
        return object_response(
            {"projected_blocked_days": projected, "committed_days": committed},
            status=200,
        )


def _committed_days(holds):
    """Merge inclusive day windows of ACTIVE CONFIRMED_BOOKING holds (PRD §3.4)."""
    confirmed = [h for h in holds if h["hold_kind"] == "CONFIRMED_BOOKING"]
    confirmed.sort(key=lambda h: (h["created_at"], h["_seq"]))
    intervals = []
    for h in confirmed:
        start = require_dt(h["start_date"]).date()
        end = require_dt(h["end_date"]).date()
        intervals.append((start, end))
    if not intervals:
        return 0
    # Merge overlapping/adjacent-overlapping inclusive day intervals.
    intervals.sort(key=lambda iv: iv[0])
    total = 0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start <= cur_end:  # overlap (inclusive days)
            if end > cur_end:
                cur_end = end
        else:
            total += (cur_end - cur_start).days + 1
            cur_start, cur_end = start, end
    total += (cur_end - cur_start).days + 1
    return total


@bp.route("/talents/<talent_id>/roster", methods=["POST"])
def roster_talent(talent_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        talent = lookup("Talent", talent_id)
        status = talent["status"]
        if status not in ("PROSPECT", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        if status == "PROSPECT":
            has_card = any(
                c["talent_id"] == talent_id for c in db.comp_cards.values()
            )
            if not has_card:
                raise ApiError("ERR_NO_COMP_CARD")
        talent["status"] = "ROSTERED"
        touch(talent)
        return object_response(public(talent), status=200)


@bp.route("/talents/<talent_id>/suspend", methods=["POST"])
def suspend_talent(talent_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        talent = lookup("Talent", talent_id)
        if talent["status"] != "ROSTERED":
            raise ApiError("ERR_INVALID_STATE")
        talent["status"] = "SUSPENDED"
        touch(talent)
        return object_response(public(talent), status=200)


@bp.route("/talents/<talent_id>/archive", methods=["POST"])
def archive_talent(talent_id):
    _, role = get_identity()
    require_role(role, {"Agent"})
    with lock:
        talent = lookup("Talent", talent_id)
        if talent["status"] not in ("ROSTERED", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE")
        open_booking = any(
            b["talent_id"] == talent_id and b["booking_status"] in ("PENDING", "CONFIRMED")
            for b in db.bookings.values()
        )
        if open_booking:
            raise ApiError("ERR_TALENT_HAS_OPEN_BOOKINGS")
        talent["status"] = "ARCHIVED"
        touch(talent)
        # Side effect: ACTIVE availability holds -> RELEASED.
        for h in db.availability_holds.values():
            if h["talent_id"] == talent_id and h["status"] == "ACTIVE":
                h["status"] = "RELEASED"
                touch(h)
        return object_response(public(talent), status=200)
