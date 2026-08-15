"""Violation endpoints: issuance with escalation, appeals, decisions."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
from db import fmt_dt, now, parse_dt, touch
from domain import (
    BASE_FINE_BY_CODE, ESCALATION_STEP, VIOLATION_WINDOW_DAYS,
    get_or_404, serialize_violation, permit_program, open_cycle_for_program,
    suspend_permit, round_half_up,
)
from errors import raise_error
from middleware import get_auth
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("violations", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")

VIOLATION_CODES = {"EXPIRED_PERMIT", "WRONG_LOT", "NO_PERMIT_DISPLAY",
                   "BLOCKED_LANE", "PARKED_AFTER_REVOCATION"}


@bp.route("/parking/violations", methods=["POST"])
def create_violation():
    user_id, role = get_auth()
    if role != "EnforcementOfficer":
        raise_error("ERR_FORBIDDEN_ROLE", "Role not allowed on this endpoint")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("permit_id", "violation_code"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    if body["violation_code"] not in VIOLATION_CODES:
        raise_error("ERR_INVALID_REQUEST", "invalid violation_code")
    permit = get_or_404(db.permits, body["permit_id"])
    program = permit_program(permit)
    # Fiscal gate: an OPEN cycle must exist
    cycle = open_cycle_for_program(program["id"])
    if cycle is None:
        raise_error("ERR_NO_OPEN_BILLING_CYCLE", "No OPEN billing cycle for the program")
    # Escalation: prior unpaid violations within trailing 365 days (boundary inclusive)
    current = now()
    window_start = current - timedelta(days=VIOLATION_WINDOW_DAYS)
    prior_unpaid = 0
    for v in db.violations.values():
        if (v["permit_id"] == permit["id"] and v["payment_status"] == "UNPAID"
                and parse_dt(v["issued_at"]) >= window_start):
            prior_unpaid += 1
    base = BASE_FINE_BY_CODE[body["violation_code"]]
    fine = round_half_up(Decimal(base) * (Decimal(1) + ESCALATION_STEP * prior_unpaid))
    # Post the PENDING VIOLATION_FINE entry in the OPEN cycle
    entry = db.new_record({
        "cycle_id": cycle["id"],
        "employee_id": permit["employee_id"],
        "permit_id": permit["id"],
        "charge_type": "VIOLATION_FINE",
        "amount_cents": fine,
        "subsidy_cents": 0,
        "span_start": None,
        "span_end": None,
        "status": "PENDING",
        "description": None,
    })
    db.charge_entries[entry["id"]] = entry
    touch(cycle)
    rec = db.new_record({
        "permit_id": permit["id"],
        "violation_code": body["violation_code"],
        "issued_by": user_id,
        "issued_at": fmt_dt(current),
        "fine_cents": fine,
        "payment_status": "UNPAID",
        "appeal_status": "NONE",
        "charge_entry_id": entry["id"],
    })
    db.violations[rec["id"]] = rec
    # Threshold suspension after posting (>= comparison, only when permit ACTIVE)
    if (prior_unpaid + 1 >= program["violation_suspension_threshold"]
            and permit["status"] == "ACTIVE"):
        suspend_permit(permit, "VIOLATION_THRESHOLD")
    return success_object(serialize_violation(rec), 201)


@bp.route("/parking/violations/<vid>", methods=["GET"])
def get_violation(vid):
    require_all = ALL_ROLES
    from middleware import require_roles
    require_roles(*require_all)
    rec = get_or_404(db.violations, vid)
    return success_object(serialize_violation(rec), 200)


@bp.route("/parking/violations", methods=["GET"])
def list_violations():
    from middleware import require_roles
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    permit_id = request.args.get("permit_id")
    charge_entry_id = request.args.get("charge_entry_id")
    payment_status = request.args.get("payment_status")
    appeal_status = request.args.get("appeal_status")
    items = sorted(db.violations.values(), key=lambda v: v["created_at"])
    out = []
    for v in items:
        if permit_id is not None and v["permit_id"] != permit_id:
            continue
        if charge_entry_id is not None and v.get("charge_entry_id") != charge_entry_id:
            continue
        if payment_status is not None and v["payment_status"] != payment_status:
            continue
        if appeal_status is not None and v["appeal_status"] != appeal_status:
            continue
        out.append(serialize_violation(v))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/violations/<vid>/events", methods=["POST"])
def violation_event(vid):
    user_id, role = get_auth()
    if role not in ("Employee", "AppealsOfficer"):
        raise_error("ERR_FORBIDDEN_ROLE", "Role not allowed on this endpoint")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    event_type = body.get("event_type")
    if event_type not in ("APPEAL", "DECIDE_APPEAL"):
        raise_error("ERR_INVALID_REQUEST", "invalid event_type")
    # Priority 2: event-verb role restrictions
    if event_type == "APPEAL" and role != "Employee":
        raise_error("ERR_FORBIDDEN_ROLE", "APPEAL is Employee-only")
    if event_type == "DECIDE_APPEAL" and role != "AppealsOfficer":
        raise_error("ERR_FORBIDDEN_ROLE", "DECIDE_APPEAL is AppealsOfficer-only")
    # Priority 4: existence + path ownership
    violation = get_or_404(db.violations, vid)
    permit = db.permits.get(violation["permit_id"])
    if event_type == "APPEAL" and role == "Employee":
        if permit is None or permit["employee_id"] != user_id:
            raise_error("ERR_NOT_RESOURCE_OWNER", "Violation belongs to a different employee")
    if event_type == "APPEAL":
        # Priority 6: state gate — UNPAID only
        if violation["payment_status"] != "UNPAID":
            raise_error("ERR_INVALID_STATE", "APPEAL requires payment_status UNPAID")
        if violation["appeal_status"] != "NONE":
            raise_error("ERR_INVALID_STATE", "Appeal already filed")
        # Priority 8: temporal — 14-day window, boundary inclusive
        issued = parse_dt(violation["issued_at"])
        if now() > issued + timedelta(days=14):
            raise_error("ERR_APPEAL_WINDOW_CLOSED", "Appeal window has closed")
        violation["appeal_status"] = "APPEALED"
        touch(violation)
    else:  # DECIDE_APPEAL
        decision = body.get("decision")
        if decision not in ("UPHELD", "DISMISSED"):
            raise_error("ERR_INVALID_REQUEST", "decision must be UPHELD or DISMISSED")
        # Priority 6: state gate
        if violation["appeal_status"] != "APPEALED":
            raise_error("ERR_INVALID_STATE", "DECIDE_APPEAL requires appeal_status APPEALED")
        # Priority 7: segregation of duties
        if user_id == violation["issued_by"]:
            raise_error("ERR_SEGREGATION_OF_DUTIES",
                        "Appeal decider must differ from the issuing officer")
        violation["appeal_status"] = decision
        if decision == "DISMISSED":
            violation["payment_status"] = "REVERSED"
            entry = db.charge_entries.get(violation.get("charge_entry_id"))
            if entry is not None:
                if entry["status"] == "PENDING":
                    entry["status"] = "REVERSED"
                    touch(entry)
                elif entry["status"] in ("APPLIED", "EXPORTED"):
                    # Compensating ADJUSTMENT_CREDIT in the program's current OPEN cycle
                    program = permit_program(permit) if permit else None
                    if program is not None:
                        open_cycle = open_cycle_for_program(program["id"])
                        if open_cycle is not None:
                            credit = db.new_record({
                                "cycle_id": open_cycle["id"],
                                "employee_id": entry["employee_id"],
                                "permit_id": entry["permit_id"],
                                "charge_type": "ADJUSTMENT_CREDIT",
                                "amount_cents": -abs(entry["amount_cents"]),
                                "subsidy_cents": 0,
                                "span_start": None,
                                "span_end": None,
                                "status": "PENDING",
                                "description": "Appeal dismissed compensation",
                            })
                            db.charge_entries[credit["id"]] = credit
                            touch(open_cycle)
        touch(violation)
    return success_object(serialize_violation(violation), 200)
