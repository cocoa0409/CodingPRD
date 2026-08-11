"""Testimony schedule + venue endpoints."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, g

import db
from lib import (
    ApiError,
    bad_request,
    body_dict,
    forbidden,
    get_or_404,
    invalid_state,
    list_ok,
    ok,
    opt_bool,
    opt_str,
    optional_body,
    pagination_params,
    req_dt,
    req_enum,
    req_num,
    req_str,
    require_role,
)
from services import (
    cents,
    engagement_view,
    expert_conflict,
    recompute_case,
    schedule_view,
    venue_conflict,
    venue_view,
)

bp = Blueprint("schedules", __name__)

READ_ROLES = ("PlatformAdmin", "CaseManager", "Expert")


def _run_booking_checks(eng, venue_id, start_dt, end_dt, exclude_id=None):
    """Pinned order: in-past -> expert calendar (half-open) -> venue (closed+buffer)."""
    if start_dt <= db.clock.now():
        raise ApiError(
            "ERR_SCHEDULE_IN_PAST",
            422,
            "session start_at must be strictly after the current logical clock",
        )
    if expert_conflict(eng["expert_id"], start_dt, end_dt, exclude_id=exclude_id):
        raise ApiError(
            "ERR_SCHEDULE_CONFLICT",
            409,
            "session overlaps an existing PROPOSED/CONFIRMED session for this expert",
        )
    if venue_id is not None and venue_conflict(
        venue_id, start_dt, end_dt, exclude_id=exclude_id
    ):
        raise ApiError(
            "ERR_VENUE_CONFLICT",
            409,
            "session overlaps the venue's buffered booking window",
        )


@bp.post("/litigation/engagements/<eid>/testimony-schedules")
def create_schedule(eid):
    b = body_dict()
    kind = req_enum(b, "kind", ("DEPOSITION", "TRIAL"))
    start_at = req_dt(b, "start_at")
    end_at = req_dt(b, "end_at")
    est_hours = req_num(b, "estimated_hours", gt=0)
    travel = opt_bool(b, "travel_required", False)
    venue_id = None
    if "venue_id" in b and b["venue_id"] is not None:
        if not isinstance(b["venue_id"], str):
            bad_request("field 'venue_id' must be a string or null")
        venue_id = b["venue_id"]
    require_role("CaseManager")
    eng = get_or_404(db.engagements, eid, "engagement")
    if venue_id is not None:
        get_or_404(db.venues, venue_id, "venue")
    start_dt = db.parse_iso(start_at)
    end_dt = db.parse_iso(end_at)
    if end_dt <= start_dt:
        raise ApiError(
            "ERR_INVALID_INTERVAL", 422, "end_at must be strictly after start_at"
        )
    _run_booking_checks(eng, venue_id, start_dt, end_dt)
    rec = db.base_record()
    rec.update(
        engagement_id=eid,
        venue_id=venue_id,
        kind=kind,
        start_at=start_at,
        end_at=end_at,
        estimated_hours=est_hours,
        travel_required=travel,
        actual_hours=0,
        cancellation_fee_cents=0,
        status="PROPOSED",
    )
    db.schedules[rec["id"]] = rec
    return ok(schedule_view(rec), 201)


@bp.get("/litigation/engagements/<eid>/testimony-schedules")
def list_schedules(eid):
    limit, offset = pagination_params()
    require_role(*READ_ROLES)
    eng = get_or_404(db.engagements, eid, "engagement")
    if g.user_role == "Expert" and eng["expert_id"] != g.user_id:
        forbidden("experts may access only their own engagements")
    recs = [s for s in db.schedules.values() if s["engagement_id"] == eid]
    return list_ok([schedule_view(s) for s in recs], limit, offset)


@bp.get("/litigation/venues/<vid>/testimony-schedules")
def venue_schedules(vid):
    limit, offset = pagination_params()
    require_role("PlatformAdmin", "CaseManager")
    get_or_404(db.venues, vid, "venue")
    recs = [s for s in db.schedules.values() if s.get("venue_id") == vid]
    return list_ok([schedule_view(s) for s in recs], limit, offset)


@bp.post("/litigation/testimony-schedules/<sid>/confirm")
def confirm_schedule(sid):
    optional_body()
    require_role("CaseManager")
    s = get_or_404(db.schedules, sid, "testimony schedule")
    if s["status"] != "PROPOSED":
        invalid_state("only a PROPOSED session can be confirmed")
    eng = db.engagements[s["engagement_id"]]
    if eng["status"] != "ACTIVE":
        invalid_state("session confirmation requires an ACTIVE engagement")
    start_dt = db.parse_iso(s["start_at"])
    end_dt = db.parse_iso(s["end_at"])
    _run_booking_checks(eng, s.get("venue_id"), start_dt, end_dt, exclude_id=sid)
    if s["kind"] == "TRIAL":
        if not any(
            r["engagement_id"] == eng["id"]
            and r["status"] in ("FINALIZED", "DISCLOSED")
            for r in db.reports.values()
        ):
            raise ApiError(
                "ERR_REPORT_NOT_FINALIZED",
                409,
                "TRIAL sessions require a FINALIZED or DISCLOSED report",
            )
    s["status"] = "CONFIRMED"
    db.touch(s)
    recompute_case(eng["case_id"])
    return ok(schedule_view(s))


@bp.post("/litigation/testimony-schedules/<sid>/cancel")
def cancel_schedule(sid):
    b = optional_body()
    opt_str(b, "reason", None)
    require_role("CaseManager")
    s = get_or_404(db.schedules, sid, "testimony schedule")
    if s["status"] not in ("PROPOSED", "CONFIRMED"):
        invalid_state("only a PROPOSED or CONFIRMED session can be cancelled")
    eng = db.engagements[s["engagement_id"]]
    if s["status"] == "CONFIRMED":
        start_dt = db.parse_iso(s["start_at"])
        now = db.clock.now()
        # strict: now == start_at - 72h exactly -> fee = 0
        if now > start_dt - timedelta(hours=72):
            fee = cents(
                Decimal("0.50")
                * Decimal(str(s["estimated_hours"]))
                * Decimal(eng["hourly_rate_cents"])
                * Decimal("1.25")
            )
            s["cancellation_fee_cents"] = fee
            remaining = (
                eng["retainer_funded_cents"]
                - eng["retainer_drawn_cents"]
                - eng["retainer_refunded_cents"]
            )
            draw = min(fee, remaining)
            if draw > 0:
                eng["retainer_drawn_cents"] += draw
                db.touch(eng)
    s["status"] = "CANCELLED"
    db.touch(s)
    recompute_case(eng["case_id"])
    return ok(schedule_view(s))


@bp.post("/litigation/testimony-schedules/<sid>/complete")
def complete_schedule(sid):
    b = body_dict()
    actual = req_num(b, "actual_hours", ge=0)
    require_role("CaseManager")
    s = get_or_404(db.schedules, sid, "testimony schedule")
    if s["status"] != "CONFIRMED":
        invalid_state("only a CONFIRMED session can be completed")
    if db.clock.now() < db.parse_iso(s["end_at"]):
        invalid_state("session cannot be completed before its end_at")
    s["status"] = "COMPLETED"
    s["actual_hours"] = actual
    db.touch(s)
    recompute_case(db.engagements[s["engagement_id"]]["case_id"])
    return ok(schedule_view(s))


# ------------------------------------------------------------- venues
@bp.post("/litigation/venues")
def create_venue():
    b = body_dict()
    name = req_str(b, "name")
    location = req_str(b, "location")
    from lib import opt_int

    capacity = opt_int(b, "capacity", 20, minimum=1)
    require_role("PlatformAdmin")
    rec = db.base_record()
    rec.update(name=name, location=location, capacity=capacity)
    db.venues[rec["id"]] = rec
    return ok(venue_view(rec), 201)


@bp.get("/litigation/venues/<vid>")
def get_venue(vid):
    require_role("PlatformAdmin", "CaseManager")
    v = get_or_404(db.venues, vid, "venue")
    return ok(venue_view(v))
