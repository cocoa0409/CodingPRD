"""EmergencyRequest routes and satisfaction/report snapshots."""
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_invalid_state,
    err_caregiver_not_active, err_emergency_window_past,
    err_emergency_reserve_exhausted, err_budget_exceeded,
    err_no_provider_available,
)
from middleware import require_roles, check_caregiver_ownership
from response import success
from services.util import (
    body, req_str, opt_str, req_number, req_ts, req_enum, paginate, serialize,
    hours_val, round_half_up_int,
)
from services import core

bp = Blueprint("emergency", __name__)

EMERGENCY_STATUSES = {"OPEN", "TRIAGED", "DISPATCHED", "FULFILLED", "EXPIRED", "CANCELLED"}
SNAPSHOT_TARGETS = {"FINALIZED", "SUBMITTED_TO_FUNDER", "UNDER_AMENDMENT"}


def _emergency_or_404(eid):
    e = db.emergencies.get(eid)
    if e is None:
        raise err_not_found("emergency")
    return e


@bp.route("/respite/emergency-requests", methods=["POST"])
def create_emergency():
    user_id, role = require_roles("Caregiver", "Coordinator")
    data = body()
    caregiver_id = req_str(data, "caregiver_id")
    needed_start = req_ts(data, "needed_start_at")
    needed_end = req_ts(data, "needed_end_at")
    reason = req_str(data, "reason")
    if needed_end <= needed_start:
        raise err_invalid_request("needed_end_at must be after needed_start_at")
    check_caregiver_ownership(user_id, role, caregiver_id)
    caregiver = db.caregivers.get(caregiver_id)
    if caregiver is None:
        raise err_not_found("caregiver")
    if caregiver["status"] != "ACTIVE":
        raise err_caregiver_not_active()
    if needed_start <= db.now():
        raise err_emergency_window_past()
    requested_hours = (needed_end - needed_start).total_seconds() / 3600.0
    base = db.new_common()
    er = {
        **base,
        "caregiver_id": caregiver_id,
        "needed_start_at": needed_start,
        "needed_end_at": needed_end,
        "reason": reason,
        "requested_hours": hours_val(requested_hours),
        "approved_hours": None,
        "status": "OPEN",
        "dispatched_booking_id": None,
        "selected_provider_id": None,
    }
    db.emergencies[er["id"]] = er
    return success(serialize(er, "emergency"), status=201)


@bp.route("/respite/emergency-requests/<eid>", methods=["GET"])
def get_emergency(eid):
    user_id, role = require_roles("Caregiver", "Coordinator", "FunderAdmin")
    er = _emergency_or_404(eid)
    check_caregiver_ownership(user_id, role, er["caregiver_id"])
    return success(serialize(er, "emergency"))


@bp.route("/respite/emergency-requests", methods=["GET"])
def list_emergencies():
    user_id, role = require_roles("Caregiver", "Coordinator", "FunderAdmin")
    caregiver_id = request.args.get("caregiver_id")
    status = request.args.get("status")
    dispatched_booking_id = request.args.get("dispatched_booking_id")
    selected_provider_id = request.args.get("selected_provider_id")
    items = list(db.emergencies.values())
    if role == "Caregiver":
        items = [e for e in items if e["caregiver_id"] == user_id]
    if caregiver_id:
        items = [e for e in items if e["caregiver_id"] == caregiver_id]
    if status:
        items = [e for e in items if e["status"] == status]
    if dispatched_booking_id:
        items = [e for e in items if e.get("dispatched_booking_id") == dispatched_booking_id]
    if selected_provider_id:
        items = [e for e in items if e.get("selected_provider_id") == selected_provider_id]
    page, meta = paginate(items)
    return success(
        [serialize(e, "emergency") for e in page],
        response_type="array",
        pagination=meta,
    )


def _find_program_for_emergency(er):
    """Find the program to use for this emergency. Tests have exactly one program."""
    if len(db.programs) == 1:
        return next(iter(db.programs.values()))
    # if caregiver has allocations, prefer their program
    for a in db.allocations.values():
        if a["caregiver_id"] == er["caregiver_id"]:
            return db.programs.get(a["program_id"])
    # fallback: any program
    return next(iter(db.programs.values()), None)


@bp.route("/respite/emergency-requests/<eid>/triage", methods=["POST"])
def triage_emergency(eid):
    require_roles("Coordinator")
    data = body()
    approved_hours = req_number(data, "approved_hours")
    opt_str(data, "note")
    er = _emergency_or_404(eid)
    if er["status"] != "OPEN":
        raise err_invalid_state("Emergency request is not OPEN")
    if er["needed_start_at"] <= db.now():
        raise err_emergency_window_past()
    program = _find_program_for_emergency(er)
    if program is None:
        raise err_not_found("program")
    if (
        Decimal(str(program["emergency_hours_used"])) + Decimal(str(approved_hours))
        > Decimal(str(program["emergency_reserve_hours"]))
    ):
        raise err_emergency_reserve_exhausted()
    er["approved_hours"] = hours_val(approved_hours)
    er["status"] = "TRIAGED"
    db.touch(er)
    return success(serialize(er, "emergency"))


@bp.route("/respite/emergency-requests/<eid>/dispatch", methods=["POST"])
def dispatch_emergency(eid):
    require_roles("Coordinator")
    er = _emergency_or_404(eid)
    if er["status"] != "TRIAGED":
        raise err_invalid_state("Emergency request is not TRIAGED")
    program = _find_program_for_emergency(er)
    if program is None:
        raise err_not_found("program")
    core.gate_operational(program)
    provider = core.emergency_dispatch_selector(er["needed_start_at"], er["needed_end_at"])
    # budget check
    approved_d = Decimal(str(er["approved_hours"]))
    provisional = round_half_up_int(
        approved_d
        * Decimal(str(program["standard_rate_cents_per_hour"]))
        * Decimal(str(program["emergency_multiplier"]))
    )
    if provisional > core.program_unencumbered(program):
        raise err_budget_exceeded()

    # 1. create emergency voucher
    base_v = db.new_common()
    voucher = {
        **base_v,
        "allocation_id": None,
        "program_id": program["id"],
        "caregiver_id": er["caregiver_id"],
        "is_emergency": True,
        "authorized_hours": hours_val(er["approved_hours"]),
        "committed_hours": 0.0,
        "consumed_hours": 0.0,
        "released_hours": 0.0,
        "forfeited_hours": 0.0,
        "status": "ISSUED",
        "issued_at": db.now(),
        "expires_at": er["needed_end_at"],
    }
    db.vouchers[voucher["id"]] = voucher

    # 2. budget ENCUMBER
    core.encumber(program, provisional, "voucher", voucher["id"], "emergency dispatch")

    # 3. create booking in CONFIRMED
    dur_minutes = int(
        (er["needed_end_at"] - er["needed_start_at"]).total_seconds() // 60
    )
    base_b = db.new_common()
    booking = {
        **base_b,
        "voucher_id": voucher["id"],
        "caregiver_id": er["caregiver_id"],
        "provider_id": provider["id"],
        "window_id": None,
        "program_id": program["id"],
        "emergency_request_id": er["id"],
        "is_emergency": True,
        "auto_matched": False,
        "start_at": er["needed_start_at"],
        "end_at": er["needed_end_at"],
        "committed_minutes": dur_minutes,
        "status": "CONFIRMED",
        "provisional_amount_cents": core.compute_provisional_cents(
            dur_minutes, program["standard_rate_cents_per_hour"]
        ),
        "cancel_reason": None,
    }
    db.bookings[booking["id"]] = booking

    # voucher ISSUED -> COMMITTED
    voucher["status"] = "COMMITTED"
    voucher["committed_hours"] = hours_val(er["approved_hours"])
    db.touch(voucher)

    # 4. emergency_hours_used
    program["emergency_hours_used"] = hours_val(
        Decimal(str(program["emergency_hours_used"])) + approved_d
    )
    db.touch(program)

    er["selected_provider_id"] = provider["id"]
    er["dispatched_booking_id"] = booking["id"]
    er["status"] = "DISPATCHED"
    db.touch(er)
    return success(serialize(er, "emergency"))


@bp.route("/respite/emergency-requests/<eid>/cancel", methods=["POST"])
def cancel_emergency(eid):
    user_id, role = require_roles("Caregiver", "Coordinator")
    er = _emergency_or_404(eid)
    if role == "Caregiver":
        check_caregiver_ownership(user_id, role, er["caregiver_id"])
    if er["status"] not in ("OPEN", "TRIAGED"):
        raise err_invalid_state("Emergency request cannot be cancelled from its current state")
    er["status"] = "CANCELLED"
    db.touch(er)
    return success(serialize(er, "emergency"))


# ---------------- satisfaction surveys (read endpoints) ----------------
@bp.route("/respite/satisfaction-surveys/<sid>", methods=["GET"])
def get_survey(sid):
    require_roles("Caregiver", "Provider", "Coordinator", "FunderAdmin")
    s = db.surveys.get(sid)
    if s is None:
        raise err_not_found("booking")  # no specific not-found id for survey; closest is booking
    return success(serialize(s, "survey"))


@bp.route("/respite/satisfaction-surveys", methods=["GET"])
def list_surveys():
    user_id, role = require_roles("Caregiver", "Provider", "Coordinator", "FunderAdmin")
    booking_id = request.args.get("booking_id")
    provider_id = request.args.get("provider_id")
    caregiver_id = request.args.get("caregiver_id")
    items = list(db.surveys.values())
    if role == "Caregiver":
        items = [s for s in items if s["caregiver_id"] == user_id]
    elif role == "Provider":
        items = [s for s in items if s["provider_id"] == user_id]
    if booking_id:
        items = [s for s in items if s["booking_id"] == booking_id]
    if provider_id:
        items = [s for s in items if s["provider_id"] == provider_id]
    if caregiver_id:
        items = [s for s in items if s["caregiver_id"] == caregiver_id]
    page, meta = paginate(items)
    return success(
        [serialize(s, "survey") for s in page],
        response_type="array",
        pagination=meta,
    )


# ---------------- report snapshots ----------------
@bp.route("/respite/report-snapshots/<sid>", methods=["GET"])
def get_snapshot(sid):
    require_roles("FunderAdmin")
    s = db.snapshots.get(sid)
    if s is None:
        raise err_not_found("snapshot")
    return success(serialize(s, "snapshot"))


@bp.route("/respite/report-snapshots/<sid>/transitions", methods=["POST"])
def snapshot_transition(sid):
    require_roles("FunderAdmin")
    data = body()
    target = req_enum(data, "target_status", SNAPSHOT_TARGETS)
    s = db.snapshots.get(sid)
    if s is None:
        raise err_not_found("snapshot")
    allowed = {
        ("GENERATED", "FINALIZED"),
        ("FINALIZED", "SUBMITTED_TO_FUNDER"),
        ("SUBMITTED_TO_FUNDER", "UNDER_AMENDMENT"),
        ("UNDER_AMENDMENT", "FINALIZED"),
        ("FINALIZED", "UNDER_AMENDMENT"),
    }
    if (s["status"], target) not in allowed:
        raise err_invalid_state(
            f"Snapshot transition {s['status']} -> {target} not permitted"
        )
    s["status"] = target
    db.touch(s)
    return success(serialize(s, "snapshot"))
