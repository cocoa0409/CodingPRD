"""Appointment endpoints: hold, deposits, waiver, confirm, cancel,
cancel-by-artist, reschedule, complete, no-show, payout, touchups
(PRD §3.5–§3.10)."""
from flask import Blueprint, request

import db
from clock import logical_now, parse_iso8601, now_iso_millis
from errors import ApiError
from helpers import (get_json_body, require_str, require_int, optional_int,
                     require_bool, require_enum, paginate)
from lookups import (get_appointment, get_artist, get_client, get_chair,
                     get_flash, get_custom_request, check_version)
from middleware import require_auth, require_ownership
from response import success
from serializers import (serialize_appointment, serialize_deposit,
                         serialize_waiver, serialize_touchup)
import services

bp = Blueprint("appointments", __name__)

PRICING_MODES = {"HOURLY", "PIECE"}
NON_TERMINAL_APPT = {"HELD", "CONFIRMED"}
FORFEITURE_WINDOW_SECONDS = 48 * 3600  # 48-hour reschedule forfeiture window


# ---------------------------------------------------------------------------
# Overlap helpers
# ---------------------------------------------------------------------------
def _artist_overlaps(artist_id, start, end, exclude_id=None):
    """Half-open [start,end) overlap with another non-terminal appointment for
    the same artist (zero buffer)."""
    for ap in db.appointments.values():
        if exclude_id is not None and ap["id"] == exclude_id:
            continue
        if ap["artist_id"] != artist_id:
            continue
        if ap["status"] not in NON_TERMINAL_APPT:
            continue
        a_start = parse_iso8601(ap["start_at"])
        a_end = parse_iso8601(ap["end_at"])
        if start < a_end and a_start < end:
            return True
    return False


def _chair_overlaps(chair, start, end, exclude_id=None):
    """Buffered overlap on the same chair: expand each existing interval by the
    chair's cleanup_buffer_minutes on each side, then half-open compare."""
    buffer_seconds = chair["cleanup_buffer_minutes"] * 60
    from datetime import timedelta
    buf = timedelta(seconds=buffer_seconds)
    for ap in db.appointments.values():
        if exclude_id is not None and ap["id"] == exclude_id:
            continue
        if ap["chair_id"] != chair["id"]:
            continue
        if ap["status"] not in NON_TERMINAL_APPT:
            continue
        a_start = parse_iso8601(ap["start_at"]) - buf
        a_end = parse_iso8601(ap["end_at"]) + buf
        if start < a_end and a_start < end:
            return True
    return False


# ---------------------------------------------------------------------------
# POST /studio/appointments  (hold creation, PRD §3.5)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments", methods=["POST"])
@require_auth(["Client"])
def create_appointment():
    body = get_json_body()

    artist_id = require_str(body, "artist_id")
    client_id = require_str(body, "client_id")
    chair_id = require_str(body, "chair_id")
    pricing_mode = require_enum(body, "pricing_mode", PRICING_MODES)
    estimated_minutes = require_int(body, "estimated_minutes")
    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")
    expected_chair_version = optional_int(body, "expected_chair_version")

    if estimated_minutes < 15:
        raise ApiError("ERR_INVALID_REQUEST", "estimated_minutes must be >= 15")

    start = parse_iso8601(start_raw)
    end = parse_iso8601(end_raw)
    if start is None or end is None:
        raise ApiError("ERR_INVALID_REQUEST", "start_at/end_at must be ISO 8601 datetimes")

    flash_design_id = body.get("flash_design_id")
    custom_request_id = body.get("custom_request_id")
    piece_price_cents = optional_int(body, "piece_price_cents")
    hourly_rate_cents = optional_int(body, "hourly_rate_cents")

    # ---- Existence (priority 3): path/body FKs left-to-right ----
    get_artist(artist_id)
    get_client(client_id)
    chair = get_chair(chair_id)
    flash = None
    custom_req = None
    if flash_design_id is not None:
        flash = get_flash(flash_design_id)
    if custom_request_id is not None:
        custom_req = get_custom_request(custom_request_id)

    # ---- Business constraint (priority 8): pricing integrity ----
    # The two sources are mutually exclusive: supplying BOTH is rejected. A
    # session may carry one source (flash or custom) or none (a plain HOURLY/
    # PIECE booking); only the both-at-once case violates the rule.
    if flash_design_id is not None and custom_request_id is not None:
        raise ApiError("ERR_INVALID_PRICING",
                       "flash_design_id and custom_request_id are mutually exclusive")
    if pricing_mode == "PIECE":
        if piece_price_cents is None:
            raise ApiError("ERR_INVALID_PRICING", "PIECE mode requires piece_price_cents")
        if piece_price_cents < 1000:
            raise ApiError("ERR_INVALID_PRICING", "piece_price_cents must be >= 1000")
    else:  # HOURLY
        if hourly_rate_cents is None:
            raise ApiError("ERR_INVALID_PRICING", "HOURLY mode requires hourly_rate_cents")
        if hourly_rate_cents < 1000:
            raise ApiError("ERR_INVALID_PRICING", "hourly_rate_cents must be >= 1000")
        if hourly_rate_cents % 4 != 0:
            raise ApiError("ERR_INVALID_PRICING", "hourly_rate_cents must be divisible by 4")

    # ---- Business constraint (priority 9): custom-request readiness ----
    if custom_req is not None and custom_req["status"] != "APPROVED":
        raise ApiError("ERR_REQUEST_NOT_APPROVED",
                       "Referenced custom request is not APPROVED")

    # ---- Temporal (priority 10): interval validity ----
    if not (end > start):
        raise ApiError("ERR_INVALID_INTERVAL", "end_at must be strictly after start_at")

    # ---- Temporal (priority 11): artist availability ----
    if _artist_overlaps(artist_id, start, end):
        raise ApiError("ERR_ARTIST_DOUBLE_BOOKED",
                       "Artist already booked for an overlapping window")

    # ---- Temporal (priority 12): chair availability (active + buffered) ----
    if not chair["active"]:
        raise ApiError("ERR_CHAIR_UNAVAILABLE", "Chair is not active")
    if _chair_overlaps(chair, start, end):
        raise ApiError("ERR_CHAIR_UNAVAILABLE",
                       "Chair unavailable within cleanup buffer of another session")

    # ---- OCC (last): chair version ----
    check_version(chair, expected_chair_version)

    # Build appointment in HELD state.
    appt = {
        "artist_id": artist_id,
        "client_id": client_id,
        "chair_id": chair_id,
        "flash_design_id": flash_design_id,
        "custom_request_id": custom_request_id,
        "pricing_mode": pricing_mode,
        "piece_price_cents": piece_price_cents if pricing_mode == "PIECE" else None,
        "hourly_rate_cents": hourly_rate_cents if pricing_mode == "HOURLY" else None,
        "estimated_minutes": estimated_minutes,
        "start_at": start_raw,
        "end_at": end_raw,
        "actual_minutes": None,
        "required_deposit_cents": services.required_deposit(
            pricing_mode, piece_price_cents, hourly_rate_cents, estimated_minutes),
        "deposit_paid_cents": 0,
        "gross_cents": None,
        "balance_due_cents": None,
        "completed_at_logical": None,
        "status": "HELD",
    }
    db.stamp_create(appt)
    db.appointments[appt["id"]] = appt

    # Side effect: advance held chair's version.
    db.touch(chair)

    return success(serialize_appointment(appt), 201)


@bp.route("/studio/appointments/<appt_id>", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def fetch_appointment(appt_id):
    appt = get_appointment(appt_id)
    return success(serialize_appointment(appt), 200)


@bp.route("/studio/appointments", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_appointments():
    items = list(db.appointments.values())
    for field in ("artist_id", "client_id", "chair_id",
                  "flash_design_id", "custom_request_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [a for a in items if a.get(field) == val]
    page, meta = paginate(items)
    return success([serialize_appointment(a) for a in page], 200,
                   response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Deposits (PRD §3.6)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/deposits", methods=["POST"])
@require_auth(["Client"])
def pay_deposit(appt_id):
    appt = get_appointment(appt_id)
    body = get_json_body()
    amount_cents = require_int(body, "amount_cents")
    expected_appt_version = optional_int(body, "expected_appointment_version")

    if amount_cents < 1:
        raise ApiError("ERR_INVALID_REQUEST", "amount_cents must be >= 1")

    # Fiscal (priority 13): deposit payable only while HELD or CONFIRMED.
    if appt["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_DEPOSIT_NOT_PAYABLE",
                       "Deposit not payable in state %s" % appt["status"])

    # OCC: appointment version.
    check_version(appt, expected_appt_version)

    deposit = {
        "appointment_id": appt_id,
        "amount_cents": amount_cents,
        "status": "CONFIRMED",
    }
    db.stamp_create(deposit)
    db.deposits[deposit["id"]] = deposit

    appt["deposit_paid_cents"] = appt.get("deposit_paid_cents", 0) + amount_cents
    db.touch(appt)

    return success(serialize_deposit(deposit), 201)


@bp.route("/studio/appointments/<appt_id>/deposits", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_deposits(appt_id):
    get_appointment(appt_id)
    status = request.args.get("status")
    items = [d for d in db.deposits.values() if d["appointment_id"] == appt_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, meta = paginate(items)
    return success([serialize_deposit(d) for d in page], 200,
                   response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Waiver (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/waiver", methods=["POST"])
@require_auth(["Client"])
def record_waiver(appt_id):
    appt = get_appointment(appt_id)
    body = get_json_body()
    client_id = require_str(body, "client_id")
    aftercare_acknowledged = require_bool(body, "aftercare_acknowledged")
    medical_flags = body.get("medical_flags", [])
    if medical_flags is None:
        medical_flags = []
    if not isinstance(medical_flags, list):
        raise ApiError("ERR_INVALID_REQUEST", "medical_flags must be an array")

    get_client(client_id)  # FK existence

    # ConsentWaiver: immutable record, only id + created_at + signed_at (== created_at).
    ts = now_iso_millis()
    waiver = {
        "id": db.new_id(),
        "appointment_id": appt_id,
        "client_id": client_id,
        "medical_flags": medical_flags,
        "aftercare_acknowledged": aftercare_acknowledged,
        "created_at": ts,
        "signed_at": ts,
    }
    db.waivers[waiver["id"]] = waiver
    return success(serialize_waiver(waiver), 201)


@bp.route("/studio/appointments/<appt_id>/waiver", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_waiver(appt_id):
    get_appointment(appt_id)
    items = [w for w in db.waivers.values() if w["appointment_id"] == appt_id]
    page, meta = paginate(items)
    return success([serialize_waiver(w) for w in page], 200,
                   response_type="array", pagination=meta)


# ---------------------------------------------------------------------------
# Confirm (PRD §3.7)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/confirm", methods=["POST"])
@require_auth(["Client"])
def confirm_appointment(appt_id):
    appt = get_appointment(appt_id)
    get_json_body()

    # State (priority 4): must be HELD.
    if appt["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", "confirm not allowed from %s" % appt["status"])

    client = db.clients.get(appt["client_id"])

    # Business safety (priority 5): client must be VERIFIED.
    if client is None or client["id_status"] != "VERIFIED":
        raise ApiError("ERR_CLIENT_NOT_VERIFIED", "Client is not VERIFIED")

    # Business safety (priority 7): valid waiver exists (aftercare_acknowledged true).
    has_valid_waiver = any(
        w["appointment_id"] == appt_id and w["aftercare_acknowledged"] is True
        for w in db.waivers.values())
    if not has_valid_waiver:
        raise ApiError("ERR_WAIVER_MISSING", "No valid consent waiver for appointment")

    # Deposit gate: deposit_paid_cents >= required_deposit_cents.
    if appt["deposit_paid_cents"] < appt["required_deposit_cents"]:
        raise ApiError("ERR_DEPOSIT_NOT_MET", "Deposit not met")

    appt["status"] = "CONFIRMED"
    db.touch(appt)

    # Side effects: flash -> RESERVED, or custom request -> CONVERTED.
    if appt.get("flash_design_id"):
        flash = db.flash_designs.get(appt["flash_design_id"])
        if flash is not None and flash["status"] == "AVAILABLE":
            flash["status"] = "RESERVED"
            db.touch(flash)
    elif appt.get("custom_request_id"):
        req = db.custom_requests.get(appt["custom_request_id"])
        if req is not None and req["status"] == "APPROVED":
            req["status"] = "CONVERTED"
            db.touch(req)

    return success(serialize_appointment(appt), 200)


def _release_flash(appt):
    if appt.get("flash_design_id"):
        flash = db.flash_designs.get(appt["flash_design_id"])
        if flash is not None and flash["status"] == "RESERVED":
            flash["status"] = "AVAILABLE"
            db.touch(flash)


# ---------------------------------------------------------------------------
# Client cancel (PRD §3.8) — deposit forfeited
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/cancel", methods=["POST"])
@require_auth(["Client"])
def cancel_appointment(appt_id):
    appt = get_appointment(appt_id)
    get_json_body()
    if appt["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", "cancel not allowed from %s" % appt["status"])

    appt["status"] = "CANCELLED"
    services.forfeit_deposits(appt)  # CONFIRMED -> FORFEITED, deposit_paid_cents -> 0
    _release_flash(appt)
    db.touch(appt)
    return success(serialize_appointment(appt), 200)


# ---------------------------------------------------------------------------
# Artist cancel (PRD §3.8) — deposit preserved, reliability debited
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/cancel-by-artist", methods=["POST"])
@require_auth(["Artist"])
def cancel_by_artist(appt_id):
    appt = get_appointment(appt_id)
    require_ownership(appt["artist_id"])  # entity-backed Artist ownership (PRD §2.1)
    get_json_body()
    if appt["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE",
                       "cancel-by-artist not allowed from %s" % appt["status"])

    appt["status"] = "CANCELLED"
    # Deposits preserved (stay CONFIRMED, deposit_paid_cents unchanged).
    artist = db.artists.get(appt["artist_id"])
    if artist is not None:
        artist["artist_cancel_count"] = artist.get("artist_cancel_count", 0) + 1
        services.recompute_reliability(artist)
        db.touch(artist)
    _release_flash(appt)
    db.touch(appt)
    return success(serialize_appointment(appt), 200)


# ---------------------------------------------------------------------------
# Reschedule (PRD §3.8) — 48h forfeiture window
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/reschedule", methods=["POST"])
@require_auth(["Client"])
def reschedule_appointment(appt_id):
    appt = get_appointment(appt_id)
    body = get_json_body()
    start_raw = require_str(body, "start_at")
    end_raw = require_str(body, "end_at")
    new_chair_id = body.get("chair_id")
    expected_chair_version = optional_int(body, "expected_chair_version")

    # State: only HELD or CONFIRMED can reschedule.
    if appt["status"] not in ("HELD", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE",
                       "reschedule not allowed from %s" % appt["status"])

    new_start = parse_iso8601(start_raw)
    new_end = parse_iso8601(end_raw)
    if new_start is None or new_end is None:
        raise ApiError("ERR_INVALID_REQUEST", "start_at/end_at must be ISO 8601 datetimes")

    now = logical_now()
    # Temporal (priority 14): new start_at must be strictly after current clock.
    if not (new_start > now):
        raise ApiError("ERR_INVALID_INTERVAL", "new start_at must be after current clock")

    # Optional chair move: existence + OCC.
    target_chair = None
    if new_chair_id is not None:
        target_chair = get_chair(new_chair_id)
        check_version(target_chair, expected_chair_version)

    # Forfeiture window: measured from current clock to the appointment's
    # CURRENT start_at (before the move). Inside (< 48h) => late reschedule.
    current_start = parse_iso8601(appt["start_at"])
    seconds_until = (current_start - now).total_seconds()
    inside_window = seconds_until < FORFEITURE_WINDOW_SECONDS

    # Apply the new window (and chair if moved).
    appt["start_at"] = start_raw
    appt["end_at"] = end_raw
    if target_chair is not None:
        appt["chair_id"] = new_chair_id
        db.touch(target_chair)

    if inside_window:
        services.forfeit_deposits(appt)  # FORFEITED, deposit_paid_cents -> 0
        artist = db.artists.get(appt["artist_id"])
        if artist is not None:
            artist["late_reschedule_count"] = artist.get("late_reschedule_count", 0) + 1
            services.recompute_reliability(artist)
            db.touch(artist)

    db.touch(appt)
    return success(serialize_appointment(appt), 200)


# ---------------------------------------------------------------------------
# Complete (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/complete", methods=["POST"])
@require_auth(["Artist"])
def complete_appointment(appt_id):
    appt = get_appointment(appt_id)
    require_ownership(appt["artist_id"])  # entity-backed Artist ownership (PRD §2.1)
    body = get_json_body()

    if appt["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "complete not allowed from %s" % appt["status"])

    actual_minutes = optional_int(body, "actual_minutes")
    if appt["pricing_mode"] == "HOURLY":
        if actual_minutes is None:
            raise ApiError("ERR_INVALID_REQUEST",
                           "actual_minutes is required for HOURLY completion")
        if actual_minutes < 1:
            raise ApiError("ERR_INVALID_REQUEST", "actual_minutes must be >= 1")
        appt["actual_minutes"] = actual_minutes
    # PIECE: actual_minutes ignored.

    appt["status"] = "COMPLETED"
    appt["gross_cents"] = services.session_gross(appt)
    appt["balance_due_cents"] = services.session_final_balance(
        appt["gross_cents"], appt["deposit_paid_cents"])
    # Record the logical-clock instant of completion for the touch-up window.
    appt["completed_at_logical"] = logical_now().isoformat()

    services.apply_deposits(appt)  # CONFIRMED -> APPLIED (deposit_paid_cents preserved)

    artist = db.artists.get(appt["artist_id"])
    if artist is not None:
        artist["completed_session_count"] = artist.get("completed_session_count", 0) + 1
        services.recompute_reliability(artist)
        db.touch(artist)

    db.touch(appt)
    return success(serialize_appointment(appt), 200)


# ---------------------------------------------------------------------------
# No-show (PRD §3.8)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/no-show", methods=["POST"])
@require_auth(["Artist"])
def no_show_appointment(appt_id):
    appt = get_appointment(appt_id)
    require_ownership(appt["artist_id"])  # entity-backed Artist ownership (PRD §2.1)
    get_json_body()

    if appt["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "no-show not allowed from %s" % appt["status"])

    # Only once the logical clock has reached/passed start_at.
    start = parse_iso8601(appt["start_at"])
    if logical_now() < start:
        raise ApiError("ERR_INVALID_STATE",
                       "no-show only after the appointment start time")

    appt["status"] = "NO_SHOW"
    services.forfeit_deposits(appt)
    _release_flash(appt)
    db.touch(appt)
    return success(serialize_appointment(appt), 200)


# ---------------------------------------------------------------------------
# Payout (PRD §3.9)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/payout", methods=["GET"])
@require_auth(["StudioManager", "Artist"])
def appointment_payout(appt_id):
    appt = get_appointment(appt_id)
    if appt["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "payout only for COMPLETED appointments")
    artist = db.artists.get(appt["artist_id"])
    commission_pct = artist["commission_pct"] if artist else 0.70
    result = services.artist_payout(appt["gross_cents"], commission_pct)
    return success(result, 200)


# ---------------------------------------------------------------------------
# Touch-ups (PRD §3.10)
# ---------------------------------------------------------------------------
@bp.route("/studio/appointments/<appt_id>/touchups", methods=["POST"])
@require_auth(["Client"])
def request_touchup(appt_id):
    appt = get_appointment(appt_id)
    get_json_body()

    # Parent must be COMPLETED.
    if appt["status"] != "COMPLETED":
        raise ApiError("ERR_TOUCHUP_PARENT_NOT_COMPLETED",
                       "Touch-up parent appointment is not COMPLETED")

    # Determine fee by free-window policy (PRD §3.10).
    completed_dt = parse_iso8601(appt.get("completed_at_logical")) \
        if appt.get("completed_at_logical") else None
    request_clock = logical_now()
    # The original session's waiver aftercare flag.
    aftercare_ack = any(
        w["appointment_id"] == appt_id and w["aftercare_acknowledged"] is True
        for w in db.waivers.values())

    if completed_dt is None:
        fee = services.TOUCHUP_FLAT_FEE_CENTS
    else:
        fee = services.touchup_fee(completed_dt, request_clock, aftercare_ack)

    touchup = {
        "parent_appointment_id": appt_id,
        "fee_cents": fee,
        "status": "REQUESTED",
    }
    db.stamp_create(touchup)
    # requested_at is a system field equal to created_at.
    touchup["requested_at"] = touchup["created_at"]
    db.touchups[touchup["id"]] = touchup
    return success(serialize_touchup(touchup), 201)


@bp.route("/studio/appointments/<appt_id>/touchups", methods=["GET"])
@require_auth(["StudioManager", "Artist", "Client"])
def list_touchups(appt_id):
    get_appointment(appt_id)
    status = request.args.get("status")
    items = [t for t in db.touchups.values() if t["parent_appointment_id"] == appt_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, meta = paginate(items)
    return success([serialize_touchup(t) for t in page], 200,
                   response_type="array", pagination=meta)
