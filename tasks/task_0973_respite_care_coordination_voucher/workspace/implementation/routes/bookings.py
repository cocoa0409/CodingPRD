"""Booking, check-in, cancel, confirm, satisfaction survey routes."""
from datetime import timedelta
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_posture_gate, err_invalid_state,
    err_caregiver_not_active, err_provider_not_active,
    err_window_capacity_full, err_caregiver_double_booked,
    err_voucher_not_issuable, err_booking_beyond_voucher_expiry,
    err_booking_not_confirmed, err_evv_outside_window, err_evv_already_open,
    err_duplicate_survey, err_forbidden_ownership, err_no_provider_available,
)
from middleware import require_roles, check_caregiver_ownership, check_provider_ownership
from response import success
from services.util import (
    body, req_str, opt_str, req_enum, req_ts, req_int, opt_int, paginate, serialize,
    hours_val, overlaps, opt_bool,
)
from services import core

bp = Blueprint("bookings", __name__)

BOOKING_STATUSES = {
    "PENDING_CONFIRMATION", "CONFIRMED", "IN_SERVICE", "COMPLETED",
    "CANCELLED", "NO_SHOW",
}


def _booking_or_404(bid):
    b = db.bookings.get(bid)
    if b is None:
        raise err_not_found("booking")
    return b


def _program_for_voucher(voucher):
    return db.programs.get(voucher["program_id"])


@bp.route("/respite/bookings", methods=["POST"])
def create_booking():
    user_id, role = require_roles("Caregiver", "Coordinator")
    data = body()
    voucher_id = req_str(data, "voucher_id")
    caregiver_id = req_str(data, "caregiver_id")
    match_mode = req_enum(data, "match_mode", {"EXPLICIT", "AUTO"})
    start_at = req_ts(data, "start_at")
    end_at = req_ts(data, "end_at")
    if end_at <= start_at:
        raise err_invalid_request("end_at must be after start_at")
    committed_minutes = int((end_at - start_at).total_seconds() // 60)

    # caregiver actor must own the booking
    check_caregiver_ownership(user_id, role, caregiver_id)

    # existence (priority 5)
    voucher = db.vouchers.get(voucher_id)
    if voucher is None:
        raise err_not_found("voucher")
    caregiver = db.caregivers.get(caregiver_id)
    if caregiver is None:
        raise err_not_found("caregiver")
    program = _program_for_voucher(voucher)
    if program is None:
        raise err_not_found("program")

    # posture (priority 6)
    core.gate_operational(program)

    # generic state-machine validity (priority 7) — n/a for create
    # caregiver active (priority 8)
    if caregiver["status"] != "ACTIVE":
        raise err_caregiver_not_active()

    # provider checks per mode (priority 9)
    provider = None
    window = None
    auto_matched = False
    if match_mode == "EXPLICIT":
        provider_id = req_str(data, "provider_id")
        window_id = req_str(data, "window_id")
        provider = db.providers.get(provider_id)
        if provider is None:
            raise err_not_found("provider")
        window = db.windows.get(window_id)
        if window is None:
            raise err_not_found("window")
        if provider["credential_status"] != "ACTIVE":
            raise err_provider_not_active()
        # window must contain booking interval
        if not (window["start_at"] <= start_at and end_at <= window["end_at"]):
            raise err_invalid_request("Window does not contain booking interval")
        # window must belong to provider
        if window["provider_id"] != provider["id"]:
            raise err_invalid_request("Window does not belong to provider")
        # capacity (priority 14): adding the new booking must keep the window's
        # overlap count strictly below capacity. Count only existing bookings
        # that overlap the new booking's interval.
        cnt = core.window_overlap_count(window, interval=(start_at, end_at))
        if cnt >= window["capacity"]:
            raise err_window_capacity_full()
    else:  # AUTO
        # selector (priority 26) — pool must be non-empty; provider active implied
        provider, window = core.auto_match_selector(start_at, end_at)
        auto_matched = True

    # caregiver double-booking buffer (priority 15)
    buf_start = start_at - timedelta(minutes=30)
    buf_end = end_at + timedelta(minutes=30)
    for b in db.bookings.values():
        if b["caregiver_id"] != caregiver_id:
            continue
        if b["status"] in ("CANCELLED", "NO_SHOW"):
            continue
        if overlaps(buf_start, buf_end, b["start_at"], b["end_at"]):
            raise err_caregiver_double_booked()

    # booking end <= voucher.expires_at (priority 17)
    if end_at > voucher["expires_at"]:
        raise err_booking_beyond_voucher_expiry()

    # voucher issuable (priority 27): must be in an issuable state (ISSUED or
    # partially-COMMITTED — the PRD's "existing committed_hours plus the new
    # booking's duration must not exceed ..." wording presupposes the voucher
    # may already carry commitments) with sufficient unconsumed hours.
    if voucher["status"] not in ("ISSUED", "COMMITTED"):
        raise err_voucher_not_issuable()
    dur_hours = Decimal(committed_minutes) / Decimal(60)
    cap = (
        Decimal(str(voucher["authorized_hours"]))
        - Decimal(str(voucher["consumed_hours"]))
        - Decimal(str(voucher["released_hours"]))
        - Decimal(str(voucher["forfeited_hours"]))
    )
    new_total = Decimal(str(voucher["committed_hours"])) + dur_hours
    if new_total > cap:
        raise err_voucher_not_issuable()

    # create booking
    base = db.new_common()
    booking = {
        **base,
        "voucher_id": voucher_id,
        "caregiver_id": caregiver_id,
        "provider_id": provider["id"],
        "window_id": window["id"] if window is not None else None,
        "program_id": program["id"],
        "emergency_request_id": None,
        "is_emergency": False,
        "auto_matched": auto_matched,
        "start_at": start_at,
        "end_at": end_at,
        "committed_minutes": committed_minutes,
        "status": "PENDING_CONFIRMATION",
        "provisional_amount_cents": None,
        "cancel_reason": None,
    }
    db.bookings[booking["id"]] = booking
    # voucher ISSUED -> COMMITTED
    voucher["status"] = "COMMITTED"
    voucher["committed_hours"] = hours_val(
        Decimal(str(voucher["committed_hours"])) + dur_hours
    )
    db.touch(voucher)
    # window capacity bookkeeping
    if window is not None:
        core.maybe_mark_window_full(window)
    return success(serialize(booking, "booking"), status=201)


@bp.route("/respite/bookings/<bid>", methods=["GET"])
def get_booking(bid):
    user_id, role = require_roles("Caregiver", "Provider", "Coordinator", "FunderAdmin")
    b = _booking_or_404(bid)
    if role == "Caregiver":
        check_caregiver_ownership(user_id, role, b["caregiver_id"])
    elif role == "Provider":
        check_provider_ownership(user_id, role, b["provider_id"])
    return success(serialize(b, "booking"))


@bp.route("/respite/bookings", methods=["GET"])
def list_bookings():
    user_id, role = require_roles("Caregiver", "Provider", "Coordinator", "FunderAdmin")
    voucher_id = request.args.get("voucher_id")
    provider_id = request.args.get("provider_id")
    caregiver_id = request.args.get("caregiver_id")
    window_id = request.args.get("window_id")
    emergency_request_id = request.args.get("emergency_request_id")
    status = request.args.get("status")
    items = list(db.bookings.values())
    if role == "Caregiver":
        items = [b for b in items if b["caregiver_id"] == user_id]
    elif role == "Provider":
        items = [b for b in items if b["provider_id"] == user_id]
    if voucher_id:
        items = [b for b in items if b["voucher_id"] == voucher_id]
    if provider_id:
        items = [b for b in items if b["provider_id"] == provider_id]
    if caregiver_id:
        items = [b for b in items if b["caregiver_id"] == caregiver_id]
    if window_id:
        items = [b for b in items if b.get("window_id") == window_id]
    if emergency_request_id:
        items = [b for b in items if b.get("emergency_request_id") == emergency_request_id]
    if status:
        items = [b for b in items if b["status"] == status]
    page, meta = paginate(items)
    return success(
        [serialize(b, "booking") for b in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/respite/bookings/<bid>/confirm", methods=["POST"])
def confirm_booking(bid):
    user_id, role = require_roles("Provider")
    b = _booking_or_404(bid)
    check_provider_ownership(user_id, role, b["provider_id"])
    program = db.programs[b["program_id"]]
    # posture (priority 6)
    core.gate_operational(program)
    # state machine (priority 7)
    if b["status"] != "PENDING_CONFIRMATION":
        raise err_invalid_state("Booking is not PENDING_CONFIRMATION")
    # provider active (priority 9)
    provider = db.providers[b["provider_id"]]
    if provider["credential_status"] != "ACTIVE":
        raise err_provider_not_active()
    b["provisional_amount_cents"] = core.compute_provisional_cents(
        b["committed_minutes"], program["standard_rate_cents_per_hour"]
    )
    b["status"] = "CONFIRMED"
    db.touch(b)
    return success(serialize(b, "booking"))


@bp.route("/respite/bookings/<bid>/cancel", methods=["POST"])
def cancel_booking(bid):
    user_id, role = require_roles("Caregiver", "Provider", "Coordinator")
    b = _booking_or_404(bid)
    if role == "Caregiver":
        check_caregiver_ownership(user_id, role, b["caregiver_id"])
    elif role == "Provider":
        check_provider_ownership(user_id, role, b["provider_id"])
    if b["status"] not in ("PENDING_CONFIRMATION", "CONFIRMED"):
        raise err_invalid_state("Booking cannot be cancelled from its current state")
    data = body()
    reason = opt_str(data, "reason")
    b["status"] = "CANCELLED"
    b["cancel_reason"] = reason
    db.touch(b)
    core.release_booking(b)
    return success(serialize(b, "booking"))


@bp.route("/respite/bookings/<bid>/visit-records", methods=["GET"])
def booking_visits(bid):
    user_id, role = require_roles("Caregiver", "Provider", "Coordinator", "FunderAdmin")
    b = _booking_or_404(bid)
    if role == "Caregiver":
        check_caregiver_ownership(user_id, role, b["caregiver_id"])
    elif role == "Provider":
        check_provider_ownership(user_id, role, b["provider_id"])
    items = [v for v in db.visits.values() if v["booking_id"] == bid]
    items.sort(key=lambda v: (v["created_at"], v["id"]))
    return success(
        [serialize(v, "visit") for v in items],
        response_type="array",
        pagination={
            "limit": len(items), "offset": 0,
            "total_count": len(items), "has_more": False,
        },
    )


@bp.route("/respite/bookings/<bid>/check-in", methods=["POST"])
def check_in(bid):
    user_id, role = require_roles("Provider")
    data = body()
    check_in_location = req_str(data, "check_in_location")
    b = _booking_or_404(bid)
    check_provider_ownership(user_id, role, b["provider_id"])
    program = db.programs[b["program_id"]]
    core.gate_operational(program)
    provider = db.providers[b["provider_id"]]
    if provider["credential_status"] != "ACTIVE":
        raise err_provider_not_active()
    # ERR_BOOKING_NOT_CONFIRMED (priority 28)
    if b["status"] != "CONFIRMED":
        raise err_booking_not_confirmed()
    # EVV window (priority 18)
    now = db.now()
    if not (b["start_at"] - timedelta(minutes=15) <= now <= b["end_at"]):
        raise err_evv_outside_window()
    # No OPEN visit (priority 29)
    for v in db.visits.values():
        if v["booking_id"] == bid and v["status"] == "OPEN":
            raise err_evv_already_open()
    base = db.new_common()
    visit = {
        **base,
        "booking_id": bid,
        "check_in_at": now,
        "check_in_location": check_in_location,
        "check_out_at": None,
        "tasks_completed": [],
        "auto_closed": False,
        "verified_minutes": None,
        "payable_minutes": None,
        "status": "OPEN",
        "rejection_reason": None,
    }
    db.visits[visit["id"]] = visit
    b["status"] = "IN_SERVICE"
    db.touch(b)
    return success(serialize(visit, "visit"), status=201)


@bp.route("/respite/bookings/<bid>/satisfaction-surveys", methods=["POST"])
def create_survey(bid):
    user_id, role = require_roles("Caregiver")
    b = _booking_or_404(bid)
    check_caregiver_ownership(user_id, role, b["caregiver_id"])
    data = body()
    rating = req_int(data, "rating")
    if rating < 1 or rating > 5:
        raise err_invalid_request("rating must be 1..5")
    would_rebook = data.get("would_rebook")
    if not isinstance(would_rebook, bool):
        raise err_invalid_request("would_rebook must be a boolean")
    comments = opt_str(data, "comments", "")
    if b["status"] != "COMPLETED":
        raise err_invalid_state("Surveys are accepted only for COMPLETED bookings")
    for s in db.surveys.values():
        if s["booking_id"] == bid:
            raise err_duplicate_survey()
    base = db.new_common()
    survey = {
        **base,
        "booking_id": bid,
        "caregiver_id": b["caregiver_id"],
        "provider_id": b["provider_id"],
        "rating": rating,
        "would_rebook": would_rebook,
        "comments": comments,
    }
    db.surveys[survey["id"]] = survey
    provider = db.providers[b["provider_id"]]
    core.recompute_quality_scores(provider)
    db.touch(provider)
    return success(serialize(survey, "survey"), status=201)
