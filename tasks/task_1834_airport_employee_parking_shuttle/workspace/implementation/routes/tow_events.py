"""TowEvent endpoints: authorize, mark towed, release, cancel."""
import math
from datetime import timedelta

from flask import Blueprint, request

import db
from db import fmt_dt, now, parse_dt, touch
from domain import (
    TOW_BASE_CENTS, STORAGE_DAILY_CENTS,
    get_or_404, serialize_tow, permit_program, open_cycle_for_program,
)
from errors import raise_error
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("tow_events", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")


@bp.route("/parking/tow-events", methods=["POST"])
def create_tow_event():
    user_id, role = require_roles("EnforcementOfficer")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("permit_id", "violation_id"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    permit = get_or_404(db.permits, body["permit_id"])
    violation = get_or_404(db.violations, body["violation_id"])
    program = permit_program(permit)
    # Priority 6: permit must be SUSPENDED with reason VIOLATION_THRESHOLD
    if not (permit["status"] == "SUSPENDED" and permit.get("suspension_reason") == "VIOLATION_THRESHOLD"):
        raise_error("ERR_INVALID_STATE",
                    "Tow authorization requires Permit SUSPENDED with suspension_reason VIOLATION_THRESHOLD")
    # Priority 7: violation enforceable
    if violation["payment_status"] != "UNPAID" or violation["appeal_status"] == "DISMISSED":
        raise_error("ERR_TOW_VIOLATION_NOT_ENFORCEABLE", "Triggering violation is not enforceable")
    # Priority 8: tow hold elapsed
    suspended_at = parse_dt(permit["suspended_at"])
    if suspended_at is None or now() < suspended_at + timedelta(hours=program["tow_hold_hours"]):
        raise_error("ERR_TOW_HOLD_NOT_ELAPSED", "Tow hold period has not elapsed")
    # Priority 11: cross-reference coherence
    if violation["permit_id"] != permit["id"]:
        raise_error("ERR_VIOLATION_PERMIT_MISMATCH",
                    "violation_id references a violation of a different permit")
    rec = db.new_record({
        "permit_id": permit["id"],
        "violation_id": violation["id"],
        "authorized_by": user_id,
        "status": "AUTHORIZED",
        "towed_at": None,
        "released_at": None,
        "impound_fee_cents": None,
        "charge_entry_id": None,
    })
    db.tow_events[rec["id"]] = rec
    return success_object(serialize_tow(rec), 201)


@bp.route("/parking/tow-events/<tid>", methods=["GET"])
def get_tow_event(tid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.tow_events, tid)
    return success_object(serialize_tow(rec), 200)


@bp.route("/parking/tow-events", methods=["GET"])
def list_tow_events():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    permit_id = request.args.get("permit_id")
    violation_id = request.args.get("violation_id")
    charge_entry_id = request.args.get("charge_entry_id")
    status = request.args.get("status")
    items = sorted(db.tow_events.values(), key=lambda t: t["created_at"])
    out = []
    for t in items:
        if permit_id is not None and t["permit_id"] != permit_id:
            continue
        if violation_id is not None and t["violation_id"] != violation_id:
            continue
        if charge_entry_id is not None and t.get("charge_entry_id") != charge_entry_id:
            continue
        if status is not None and t["status"] != status:
            continue
        out.append(serialize_tow(t))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/tow-events/<tid>/events", methods=["POST"])
def tow_event_event(tid):
    user_id, role = require_roles("EnforcementOfficer")
    tow = get_or_404(db.tow_events, tid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    event_type = body.get("event_type")
    if event_type not in ("MARK_TOWED", "RELEASE", "CANCEL"):
        raise_error("ERR_INVALID_REQUEST", "invalid event_type")
    if event_type == "MARK_TOWED":
        if tow["status"] != "AUTHORIZED":
            raise_error("ERR_INVALID_STATE", "MARK_TOWED requires AUTHORIZED")
        tow["towed_at"] = fmt_dt(now())
        tow["status"] = "TOWED"
        touch(tow)
    elif event_type == "RELEASE":
        if tow["status"] != "TOWED":
            raise_error("ERR_INVALID_STATE", "RELEASE requires TOWED")
        permit = db.permits.get(tow["permit_id"])
        program = permit_program(permit) if permit else None
        cycle = open_cycle_for_program(program["id"]) if program else None
        if cycle is None:
            raise_error("ERR_NO_OPEN_BILLING_CYCLE", "No OPEN billing cycle for the program")
        tow["released_at"] = fmt_dt(now())
        held_seconds = (now() - parse_dt(tow["towed_at"])).total_seconds()
        days_held = max(1, math.ceil(held_seconds / 86400))
        fee = TOW_BASE_CENTS + STORAGE_DAILY_CENTS * days_held
        tow["impound_fee_cents"] = fee
        entry = db.new_record({
            "cycle_id": cycle["id"],
            "employee_id": permit["employee_id"],
            "permit_id": permit["id"],
            "charge_type": "TOW_FEE",
            "amount_cents": fee,
            "subsidy_cents": 0,
            "span_start": None,
            "span_end": None,
            "status": "PENDING",
            "description": None,
        })
        db.charge_entries[entry["id"]] = entry
        touch(cycle)
        tow["charge_entry_id"] = entry["id"]
        tow["status"] = "RELEASED"
        touch(tow)
    else:  # CANCEL
        if tow["status"] != "AUTHORIZED":
            raise_error("ERR_INVALID_STATE", "CANCEL requires AUTHORIZED")
        tow["status"] = "CANCELLED"
        touch(tow)
    return success_object(serialize_tow(tow), 200)
