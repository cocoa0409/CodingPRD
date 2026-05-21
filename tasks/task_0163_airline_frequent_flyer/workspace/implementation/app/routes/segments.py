"""FlightSegment endpoints."""

from __future__ import annotations

from flask import Blueprint, g, request

from .. import errors as E
from ..auth import require_roles
from ..envelope import ok_object, ok_array
from ..store import store, new_uuid
from ..timeutil import clock
from ..services.common import (
    get_json_body, require_fields, parse_pagination, paginate,
    bump_version, get_member_or_404, get_flight_or_404, get_segment_owned,
    enforce_member_ownership, enforce_member_status,
)
from ..services.serialize import serialize_segment
from ..services import calc, ledger


segments_bp = Blueprint("segments", __name__)


VALID_CABINS = {"ECONOMY", "BUSINESS", "FIRST"}


@segments_bp.post("/members/<member_id>/segments")
@require_roles("Member", "BookingAgent")
def create_segment(member_id):
    m = get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    body = get_json_body()
    require_fields(body, "flight_id", "booked_cabin")
    if body["booked_cabin"] not in VALID_CABINS:
        raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid booked_cabin.")
    f = get_flight_or_404(body["flight_id"])
    enforce_member_status(m)
    if f["status"] != "SCHEDULED":
        raise E.ApiError(E.ERR_FLIGHT_NOT_BOOKABLE, 409, "Flight not bookable.")
    now = clock.now()
    sid = new_uuid()
    s = {
        "id": sid,
        "member_id": member_id,
        "flight_id": f["id"],
        "booked_cabin": body["booked_cabin"],
        "flown_cabin": None,
        "status": "BOOKED",
        "flown_year": None,
        "qualifying_points_earned": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.segments[sid] = s
    return ok_object(serialize_segment(s), 201)


@segments_bp.get("/members/<member_id>/segments")
@require_roles("Member", "ProgramAdmin", "BookingAgent")
def list_segments(member_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    flown_year_f = request.args.get("flown_year")
    if flown_year_f is not None:
        try:
            flown_year_f = int(flown_year_f)
        except ValueError:
            raise E.ApiError(E.ERR_INVALID_REQUEST, 400, "Invalid flown_year.")
    items = [
        s for s in store.segments.values()
        if s["member_id"] == member_id
        and (status_f is None or s["status"] == status_f)
        and (flown_year_f is None or s.get("flown_year") == flown_year_f)
    ]
    items.sort(key=lambda s: s["created_at"])
    page, total, has_more = paginate(items, limit, offset)
    data = [serialize_segment(s) for s in page]
    return ok_array(data, limit, offset, total, has_more)


@segments_bp.post("/members/<member_id>/segments/<segment_id>/mark-flown")
@require_roles("BookingAgent", "ProgramAdmin")
def mark_flown(member_id, segment_id):
    m = get_member_or_404(member_id)
    s = get_segment_owned(member_id, segment_id)
    if s["status"] != "BOOKED":
        raise E.ApiError(E.ERR_SEGMENT_NOT_FLYABLE, 409, "Segment is not BOOKED.")
    f = store.flights.get(s["flight_id"])
    if not f or f["status"] != "DEPARTED":
        raise E.ApiError(E.ERR_SEGMENT_NOT_FLYABLE, 409, "Flight must be DEPARTED to mark-flown.")
    enforce_member_status(m)
    # Determine flown_cabin: booked_cabin unless a CONFIRMED UpgradeRequest exists for this segment.
    flown_cabin = s["booked_cabin"]
    for u in store.upgrade_requests.values():
        if u["flight_segment_id"] == s["id"] and u["status"] == "CONFIRMED":
            flown_cabin = u["target_cabin"]
            break
    now = clock.now()
    # Tier-at-departure for accrual = current Member.tier at this moment per scaffold.
    pts = calc.segment_accrual(f["base_fare_cents"], flown_cabin, m["tier"])
    s["status"] = "FLOWN"
    s["flown_cabin"] = flown_cabin
    s["flown_year"] = f["departure_at"].year
    s["qualifying_points_earned"] = pts
    bump_version(s, now)
    # Append ACCRUAL ledger row with posted_at = Flight.departure_at, expires_at = posted_at + 24 months.
    from ..timeutil import add_months
    posted = f["departure_at"]
    expires = add_months(posted, 24)
    ledger.append(
        member_id=member_id,
        kind="ACCRUAL",
        points_delta=pts,
        qualifying_points=pts,
        posted_at=posted,
        expires_at=expires,
        remaining_unredeemed=pts,
        related_segment_id=s["id"],
        now=now,
    )
    m["last_activity_at"] = now
    bump_version(m, now)
    # Any UpgradeRequest still in WAITLISTED for this segment transitions to EXPIRED.
    for u in store.upgrade_requests.values():
        if u["flight_segment_id"] == s["id"] and u["status"] == "WAITLISTED":
            u["status"] = "EXPIRED"
            u["held_points"] = 0
            bump_version(u, now)
    return ok_object(serialize_segment(s))


@segments_bp.post("/members/<member_id>/segments/<segment_id>/cancel")
@require_roles("Member", "BookingAgent")
def cancel_segment(member_id, segment_id):
    get_member_or_404(member_id)
    enforce_member_ownership(g.user_id, g.user_role, member_id)
    s = get_segment_owned(member_id, segment_id)
    if s["status"] != "BOOKED":
        raise E.ApiError(E.ERR_SEGMENT_NOT_FLYABLE, 409, "Segment is not BOOKED.")
    f = store.flights.get(s["flight_id"])
    if not f or f["status"] != "SCHEDULED":
        raise E.ApiError(E.ERR_FLIGHT_NOT_BOOKABLE, 409, "Flight no longer SCHEDULED.")
    now = clock.now()
    s["status"] = "CANCELLED"
    bump_version(s, now)
    for u in store.upgrade_requests.values():
        if u["flight_segment_id"] == s["id"] and u["status"] == "WAITLISTED":
            u["status"] = "CANCELLED"
            u["held_points"] = 0
            bump_version(u, now)
    return ok_object(serialize_segment(s))


@segments_bp.post("/members/<member_id>/segments/<segment_id>/refund")
@require_roles("ProgramAdmin")
def refund_segment(member_id, segment_id):
    m = get_member_or_404(member_id)
    s = get_segment_owned(member_id, segment_id)
    if s["status"] != "FLOWN":
        raise E.ApiError(E.ERR_SEGMENT_NOT_REFUNDABLE, 409, "Segment is not FLOWN.")
    now = clock.now()
    pts = s.get("qualifying_points_earned", 0) or 0
    s["status"] = "REFUNDED"
    bump_version(s, now)
    # Append negative ACCRUAL row (the only allowed negative ACCRUAL).
    ledger.append(
        member_id=member_id,
        kind="ACCRUAL",
        points_delta=-pts,
        qualifying_points=-pts,
        posted_at=now,
        expires_at=None,
        remaining_unredeemed=None,
        related_segment_id=s["id"],
        now=now,
    )
    bump_version(m, now)
    return ok_object(serialize_segment(s))
