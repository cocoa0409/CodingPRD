"""Booking endpoints (PRD §3.4, §3.5)."""

from datetime import timedelta

from flask import Blueprint, request

import errors
from db import store, iso, parse_dt
from errors import err
from middleware import authenticate, require_roles, get_json, parse_pagination, paginate
from response import ok
from services import validate as v
from services.cascade import (cancel_confirmed_booking_escrow_release,
                              cancel_scheduled_sessions)
from services.calc import (compute_estimated_session_pay, LAST_MINUTE_WINDOW_HOURS)
from services.common import base_record, touch
from services.ledger import recompute_escrow_available
from services.lookup import (get_family, get_caregiver, get_job_posting,
                             get_booking, sorted_by_created)
from services.serialize import booking_out
from services.temporal import windows_share_instant

bp = Blueprint("bookings", __name__)

TIER_ORDER = {"NONE": 0, "BASIC": 1, "STANDARD": 2, "PREMIUM": 3}


@bp.route("/marketplace/bookings", methods=["POST"])
def create_booking():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    body = get_json()

    family_id = v.req_str(body, "family_id")
    caregiver_id = v.req_str(body, "caregiver_id")
    job_posting_id = v.req_str(body, "job_posting_id")
    agreed_rate = v.req_int(body, "agreed_rate_cents", minimum=1)
    scheduled_start = v.req_datetime(body, "scheduled_start")
    scheduled_end = v.req_datetime(body, "scheduled_end")
    recurrence_count = v.opt_int(body, "recurrence_count", default=1, minimum=1)
    is_holiday = v.opt_bool(body, "is_holiday", default=False)

    if auth.is_family and auth.user_id != family_id:
        raise err(errors.ERR_FORBIDDEN, "Family may only offer its own bookings")

    # Existence (priority 3): body FK fields left to right.
    family = get_family(family_id)
    caregiver = get_caregiver(caregiver_id)
    posting = get_job_posting(job_posting_id)

    # Posting consistency + OPEN (priority 8).
    if posting["family_id"] != family_id or posting["status"] != "OPEN":
        raise err(errors.ERR_POSTING_MISMATCH, "Posting inconsistent or not OPEN")

    # Rate floor (priority 9).
    if agreed_rate < caregiver["hourly_rate_floor_cents"]:
        raise err(errors.ERR_RATE_BELOW_FLOOR, "agreed_rate below caregiver floor")

    # Recurrence shape (priority 10).
    if posting["care_type"] == "ONE_TIME":
        if recurrence_count != 1:
            raise err(errors.ERR_RECURRENCE_INVALID, "ONE_TIME requires recurrence_count==1")
    else:  # RECURRING
        if recurrence_count < 2:
            raise err(errors.ERR_RECURRENCE_INVALID, "RECURRING requires recurrence_count>=2")

    # Interval ordering (priority 13).
    if not (scheduled_end > scheduled_start):
        raise err(errors.ERR_INVALID_INTERVAL, "scheduled_end must be after scheduled_start")

    rec = base_record()
    rec.update({
        "family_id": family_id,
        "caregiver_id": caregiver_id,
        "job_posting_id": job_posting_id,
        "care_type": posting["care_type"],
        "agreed_rate_cents": agreed_rate,
        "scheduled_start_iso": iso(scheduled_start),
        "scheduled_end_iso": iso(scheduled_end),
        "recurrence_count": recurrence_count,
        "is_holiday": is_holiday,
        "status": "OFFERED",
        "offer_round": 1,
        "is_last_minute": False,
        "estimated_pay_cents": 0,
        "final_pay_cents": None,
    })
    store.bookings[rec["id"]] = rec
    return ok(booking_out(rec), status=201)


@bp.route("/marketplace/bookings/<bid>", methods=["GET"])
def get_one_booking(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    b = get_booking(bid)
    if auth.is_family and auth.user_id != b["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only read its own bookings")
    if auth.is_caregiver and auth.user_id != b["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only read its own bookings")
    return ok(booking_out(b), status=200)


@bp.route("/marketplace/bookings", methods=["GET"])
def list_bookings():
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    limit, offset = parse_pagination()
    family_id = request.args.get("family_id")
    caregiver_id = request.args.get("caregiver_id")
    job_posting_id = request.args.get("job_posting_id")
    status = request.args.get("status")

    items = list(store.bookings.values())
    if auth.is_family:
        items = [b for b in items if b["family_id"] == auth.user_id]
    if auth.is_caregiver:
        items = [b for b in items if b["caregiver_id"] == auth.user_id]
    if family_id is not None:
        items = [b for b in items if b["family_id"] == family_id]
    if caregiver_id is not None:
        items = [b for b in items if b["caregiver_id"] == caregiver_id]
    if job_posting_id is not None:
        items = [b for b in items if b["job_posting_id"] == job_posting_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return ok([booking_out(b) for b in page], status=200, pagination=meta)


@bp.route("/marketplace/bookings/<bid>/counter", methods=["POST"])
def counter_booking(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family", "Caregiver"})
    b = get_booking(bid)

    # Ownership: family counters from COUNTERED, caregiver counters from OFFERED.
    if auth.is_family and auth.user_id != b["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only counter its own bookings")
    if auth.is_caregiver and auth.user_id != b["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only counter its own bookings")

    body = get_json()
    # Validate presence/type of both fields before state/OCC checks would read
    # them; but state (priority 4) precedes OCC (priority 5) precedes business.
    agreed_rate = v.req_int(body, "agreed_rate_cents", minimum=1)
    expected_version = v.req_int(body, "expected_booking_version")

    # State (priority 4).
    if b["status"] not in {"OFFERED", "COUNTERED"}:
        raise err(errors.ERR_INVALID_STATE, "Booking not in a counter-able state")

    # OCC (priority 5).
    if expected_version != b["version"]:
        raise err(errors.ERR_STALE_VERSION, "Stale booking version")

    # Rate floor (priority 9).
    caregiver = get_caregiver(b["caregiver_id"])
    if agreed_rate < caregiver["hourly_rate_floor_cents"]:
        raise err(errors.ERR_RATE_BELOW_FLOOR, "agreed_rate below caregiver floor")

    # Toggle OFFERED <-> COUNTERED.
    b["status"] = "COUNTERED" if b["status"] == "OFFERED" else "OFFERED"
    b["agreed_rate_cents"] = agreed_rate
    b["offer_round"] += 1
    touch(b)  # increments version by 1
    return ok(booking_out(b), status=200)


@bp.route("/marketplace/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    b = get_booking(bid)
    if auth.is_caregiver and auth.user_id != b["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only confirm its own bookings")

    # State (priority 4).
    if b["status"] not in {"OFFERED", "COUNTERED"}:
        raise err(errors.ERR_INVALID_STATE, "Booking not confirmable from this state")

    caregiver = get_caregiver(b["caregiver_id"])
    family = get_family(b["family_id"])

    # Tier sufficiency (priority 6): verification CLEAR and tier reaches required.
    if (caregiver["verification_status"] != "CLEAR"
            or TIER_ORDER[caregiver["background_check_tier"]] < TIER_ORDER[family["required_tier"]]):
        raise err(errors.ERR_TIER_INSUFFICIENT, "Caregiver tier insufficient")

    # Suspension (priority 7).
    if caregiver["availability_status"] == "SUSPENDED":
        raise err(errors.ERR_CAREGIVER_SUSPENDED, "Caregiver is suspended")

    start_dt = parse_dt(b["scheduled_start_iso"])
    end_dt = parse_dt(b["scheduled_end_iso"])

    # Family window conflict (priority 12): closed-adjacency, no buffer, against
    # other CONFIRMED/IN_PROGRESS bookings' first-session windows.
    for other in store.bookings.values():
        if other["id"] == b["id"] or other["family_id"] != b["family_id"]:
            continue
        if other["status"] not in {"CONFIRMED", "IN_PROGRESS"}:
            continue
        o_start = parse_dt(other["scheduled_start_iso"])
        o_end = parse_dt(other["scheduled_end_iso"])
        if windows_share_instant(start_dt, end_dt, o_start, o_end):
            raise err(errors.ERR_FAMILY_WINDOW_CONFLICT,
                      "Family already has an overlapping confirmed booking")

    # Compute is_last_minute and estimated pay (drives escrow).
    now = store.now()
    is_last_minute = (start_dt - now) < timedelta(hours=LAST_MINUTE_WINDOW_HOURS)
    estimated = compute_estimated_session_pay(
        start_dt, end_dt, b["agreed_rate_cents"], family["num_children"],
        b["is_holiday"], is_last_minute,
    )

    # Escrow sufficiency (priority 15).
    if family["escrow_available_cents"] < estimated:
        raise err(errors.ERR_INSUFFICIENT_ESCROW, "Insufficient escrow available")

    # --- commit cascade (atomic) ---
    b["is_last_minute"] = is_last_minute
    b["estimated_pay_cents"] = estimated
    b["status"] = "CONFIRMED"

    family["escrow_reserved_cents"] += estimated
    recompute_escrow_available(family)
    touch(family)

    # Generate sessions: ONE_TIME -> 1; RECURRING -> recurrence_count weekly.
    count = 1 if b["care_type"] == "ONE_TIME" else b["recurrence_count"]
    duration = end_dt - start_dt
    for idx in range(count):
        ws = start_dt + timedelta(weeks=idx)
        we = ws + duration
        srec = base_record()
        srec.update({
            "booking_id": b["id"],
            "caregiver_id": b["caregiver_id"],
            "sequence_index": idx,
            "window_start_iso": iso(ws),
            "window_end_iso": iso(we),
            "status": "SCHEDULED",
            "clock_in_at_iso": None,
            "clock_out_at_iso": None,
            "actual_hours": 0.0,
            "gross_pay_cents": 0,
            # Only the first session inherits the booking-level holiday flag;
            # later weekly sessions default to non-holiday.
            "is_holiday": b["is_holiday"] if idx == 0 else False,
        })
        store.sessions[srec["id"]] = srec

    posting = get_job_posting(b["job_posting_id"])
    posting["status"] = "FILLED"
    touch(posting)

    touch(b)
    return ok(booking_out(b), status=200)


@bp.route("/marketplace/bookings/<bid>/decline", methods=["POST"])
def decline_booking(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Caregiver"})
    b = get_booking(bid)
    if auth.is_caregiver and auth.user_id != b["caregiver_id"]:
        raise err(errors.ERR_FORBIDDEN, "Caregiver may only decline its own bookings")
    if b["status"] not in {"OFFERED", "COUNTERED"}:
        raise err(errors.ERR_INVALID_STATE, "Booking not declinable from this state")
    b["status"] = "DECLINED"
    touch(b)
    return ok(booking_out(b), status=200)


@bp.route("/marketplace/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    auth = authenticate()
    require_roles(auth, {"PlatformAdmin", "Family"})
    b = get_booking(bid)
    if auth.is_family and auth.user_id != b["family_id"]:
        raise err(errors.ERR_FORBIDDEN, "Family may only cancel its own bookings")

    if b["status"] != "CONFIRMED":
        raise err(errors.ERR_INVALID_STATE, "Only a CONFIRMED booking may be cancelled")

    # No child session may have started or completed.
    for s in store.sessions.values():
        if s["booking_id"] == b["id"] and s["status"] in {"IN_PROGRESS", "COMPLETED"}:
            raise err(errors.ERR_INVALID_STATE, "A child session has already started")

    family = get_family(b["family_id"])
    cancel_confirmed_booking_escrow_release(b, family)
    cancel_scheduled_sessions(b)

    posting = store.job_postings.get(b["job_posting_id"])
    if posting is not None:
        posting["status"] = "OPEN"
        touch(posting)

    b["status"] = "CANCELLED"
    touch(b)
    return ok(booking_out(b), status=200)
