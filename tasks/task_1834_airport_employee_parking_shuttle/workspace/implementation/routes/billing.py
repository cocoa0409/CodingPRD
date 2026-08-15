"""BillingCycle and ChargeEntry endpoints."""
from flask import Blueprint, request

import db
from db import parse_date, touch
from domain import (
    get_or_404, serialize_cycle, serialize_entry, employee_standing,
    post_permit_fee, cycle_total,
)
from errors import raise_error
from middleware import require_roles
from response import success_object, success_list
from pagination import parse_pagination

bp = Blueprint("billing", __name__)

ALL_ROLES = ("ParkingAdmin", "Employee", "PayrollAdmin",
             "EnforcementOfficer", "AppealsOfficer", "ShuttleDispatcher")


# ---------------------------------------------------------------------------
# Billing cycles
# ---------------------------------------------------------------------------

@bp.route("/parking/billing-cycles", methods=["POST"])
def create_cycle():
    require_roles("PayrollAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("program_id", "period_start", "period_end"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    program = get_or_404(db.programs, body["program_id"])
    ps = parse_date(body["period_start"])
    pe = parse_date(body["period_end"])
    if ps is None or pe is None:
        raise_error("ERR_INVALID_REQUEST", "period_start/period_end must be ISO dates")
    if pe < ps:
        raise_error("ERR_INVALID_REQUEST", "period_end must be >= period_start")
    # closed-interval overlap on same program (sharing a boundary day counts)
    for c in db.billing_cycles.values():
        if c["program_id"] == program["id"]:
            cs = parse_date(c["period_start"])
            ce = parse_date(c["period_end"])
            if ps <= ce and pe >= cs:
                raise_error("ERR_BILLING_CYCLE_OVERLAP",
                            "Cycle overlaps an existing cycle of the same program")
    # Subsidy cap snapshot: standing snapshot first (breaks circularity)
    program_lot_ids = {l["id"] for l in db.lots.values() if l["program_id"] == program["id"]}
    eligible = 0
    for p in db.permits.values():
        if p["lot_id"] in program_lot_ids and p["status"] == "ACTIVE":
            if employee_standing(p["employee_id"]) == "GOOD_STANDING":
                eligible += 1
    cap = program["monthly_subsidy_pool_cents"] // max(1, eligible)
    rec = db.new_record({
        "program_id": program["id"],
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "status": "OPEN",
        "subsidy_per_capita_cap_cents": cap,
    })
    db.billing_cycles[rec["id"]] = rec
    # Post full-period PENDING PERMIT_FEE for permits ACTIVE at creation
    for p in sorted(db.permits.values(), key=lambda x: x["created_at"]):
        if p["lot_id"] in program_lot_ids and p["status"] == "ACTIVE":
            post_permit_fee(p, rec, ps, pe, is_truncation=False)
    return success_object(serialize_cycle(rec), 201)


@bp.route("/parking/billing-cycles/<cid>", methods=["GET"])
def get_cycle(cid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.billing_cycles, cid)
    return success_object(serialize_cycle(rec), 200)


@bp.route("/parking/billing-cycles", methods=["GET"])
def list_cycles():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = sorted(db.billing_cycles.values(), key=lambda c: c["created_at"])
    out = []
    for c in items:
        if program_id is not None and c["program_id"] != program_id:
            continue
        if status is not None and c["status"] != status:
            continue
        out.append(serialize_cycle(c))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/billing-cycles/<cid>/close", methods=["POST"])
def close_cycle(cid):
    require_roles("PayrollAdmin")
    cycle = get_or_404(db.billing_cycles, cid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body.get("expected_billing_cycle_version") is None:
        raise_error("ERR_INVALID_REQUEST", "expected_billing_cycle_version is required")
    if (not isinstance(body["expected_billing_cycle_version"], int)
            or isinstance(body["expected_billing_cycle_version"], bool)):
        raise_error("ERR_INVALID_REQUEST", "expected_billing_cycle_version must be an integer")
    # OCC evaluated before the state gate
    if body["expected_billing_cycle_version"] != cycle["version"]:
        raise_error("ERR_STALE_CYCLE_VERSION",
                    "expected_billing_cycle_version does not match BillingCycle.version")
    if cycle["status"] != "OPEN":
        raise_error("ERR_CYCLE_NOT_OPEN", "Cycle is not OPEN")
    for e in db.charge_entries.values():
        if e["cycle_id"] == cycle["id"] and e["status"] == "PENDING":
            e["status"] = "APPLIED"
            touch(e)
    touch(cycle)  # version +1; total recomputed on read
    cycle["status"] = "CLOSED"
    return success_object(serialize_cycle(cycle), 200)


@bp.route("/parking/billing-cycles/<cid>/events", methods=["POST"])
def cycle_event(cid):
    require_roles("PayrollAdmin")
    cycle = get_or_404(db.billing_cycles, cid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    event_type = body.get("event_type")
    if event_type not in ("EXPORT", "REJECT_EXPORT"):
        raise_error("ERR_INVALID_REQUEST", "invalid event_type")
    if event_type == "EXPORT":
        if cycle["status"] != "CLOSED":
            raise_error("ERR_INVALID_STATE", "EXPORT requires the cycle to be CLOSED")
        for e in db.charge_entries.values():
            if e["cycle_id"] == cycle["id"] and e["status"] == "APPLIED":
                e["status"] = "EXPORTED"
                touch(e)
        cycle["status"] = "EXPORTED"
        touch(cycle)
    else:  # REJECT_EXPORT
        if cycle["status"] != "EXPORTED":
            raise_error("ERR_INVALID_STATE", "REJECT_EXPORT requires the cycle to be EXPORTED")
        for e in db.charge_entries.values():
            if e["cycle_id"] == cycle["id"] and e["status"] in ("SETTLED", "DEDUCTION_FAILED"):
                raise_error("ERR_INVALID_STATE",
                            "Cannot reject export once any entry is SETTLED or DEDUCTION_FAILED")
        for e in db.charge_entries.values():
            if e["cycle_id"] == cycle["id"] and e["status"] == "EXPORTED":
                e["status"] = "APPLIED"
                touch(e)
        cycle["status"] = "CLOSED"
        touch(cycle)
    return success_object(serialize_cycle(cycle), 200)


# ---------------------------------------------------------------------------
# Charge entries
# ---------------------------------------------------------------------------

@bp.route("/parking/charge-entries", methods=["POST"])
def create_entry():
    require_roles("PayrollAdmin")
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    for field in ("cycle_id", "employee_id", "charge_type", "amount_cents"):
        if body.get(field) is None:
            raise_error("ERR_INVALID_REQUEST", f"{field} is required")
    cycle = get_or_404(db.billing_cycles, body["cycle_id"])
    employee = get_or_404(db.employees, body["employee_id"])
    ctype = body["charge_type"]
    if ctype not in ("ADJUSTMENT_CREDIT", "ADJUSTMENT_DEBIT"):
        raise_error("ERR_INVALID_REQUEST",
                    "manual charge entries are limited to ADJUSTMENT_CREDIT / ADJUSTMENT_DEBIT")
    amount = body["amount_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool):
        raise_error("ERR_INVALID_REQUEST", "amount_cents must be an integer")
    if ctype == "ADJUSTMENT_CREDIT" and amount >= 0:
        raise_error("ERR_INVALID_REQUEST", "ADJUSTMENT_CREDIT amount must be negative")
    if ctype == "ADJUSTMENT_DEBIT" and amount <= 0:
        raise_error("ERR_INVALID_REQUEST", "ADJUSTMENT_DEBIT amount must be positive")
    if cycle["status"] != "OPEN":
        raise_error("ERR_CYCLE_NOT_OPEN", "Manual adjustments require an OPEN cycle")
    rec = db.new_record({
        "cycle_id": cycle["id"],
        "employee_id": employee["id"],
        "permit_id": None,
        "charge_type": ctype,
        "amount_cents": amount,
        "subsidy_cents": 0,
        "span_start": None,
        "span_end": None,
        "status": "PENDING",
        "description": body.get("description"),
    })
    db.charge_entries[rec["id"]] = rec
    touch(cycle)
    return success_object(serialize_entry(rec), 201)


@bp.route("/parking/charge-entries/<eid>", methods=["GET"])
def get_entry(eid):
    require_roles(*ALL_ROLES)
    rec = get_or_404(db.charge_entries, eid)
    return success_object(serialize_entry(rec), 200)


@bp.route("/parking/charge-entries", methods=["GET"])
def list_entries():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    cycle_id = request.args.get("cycle_id")
    employee_id = request.args.get("employee_id")
    permit_id = request.args.get("permit_id")
    charge_type = request.args.get("charge_type")
    status = request.args.get("status")
    items = sorted(db.charge_entries.values(), key=lambda e: e["created_at"])
    out = []
    for e in items:
        if cycle_id is not None and e["cycle_id"] != cycle_id:
            continue
        if employee_id is not None and e["employee_id"] != employee_id:
            continue
        if permit_id is not None and e.get("permit_id") != permit_id:
            continue
        if charge_type is not None and e["charge_type"] != charge_type:
            continue
        if status is not None and e["status"] != status:
            continue
        out.append(serialize_entry(e))
    total = len(out)
    return success_list(out[offset:offset + limit], limit, offset, total)


@bp.route("/parking/charge-entries/<eid>/settle", methods=["POST"])
def settle_entry(eid):
    require_roles("PayrollAdmin")
    entry = get_or_404(db.charge_entries, eid)
    body = request.get_json(silent=True)
    if body is None:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    outcome = body.get("outcome")
    if outcome not in ("SETTLED", "DEDUCTION_FAILED"):
        raise_error("ERR_INVALID_REQUEST", "outcome must be SETTLED or DEDUCTION_FAILED")
    if entry["status"] == "EXPORTED":
        if outcome == "SETTLED":
            entry["status"] = "SETTLED"
            touch(entry)
            _violation_paid_linkage(entry)
        else:
            entry["status"] = "DEDUCTION_FAILED"
            touch(entry)
    elif entry["status"] == "DEDUCTION_FAILED":
        if outcome == "SETTLED":
            entry["status"] = "SETTLED"
            touch(entry)
            _violation_paid_linkage(entry)
        else:
            raise_error("ERR_INVALID_STATE", "Entry already DEDUCTION_FAILED")
    else:
        raise_error("ERR_INVALID_STATE", "Settle requires EXPORTED or DEDUCTION_FAILED")
    return success_object(serialize_entry(entry), 200)


def _violation_paid_linkage(entry):
    """When a VIOLATION_FINE settles, flip the linked violation UNPAID -> PAID."""
    if entry["charge_type"] != "VIOLATION_FINE":
        return
    for v in db.violations.values():
        if v.get("charge_entry_id") == entry["id"] and v["payment_status"] == "UNPAID":
            v["payment_status"] = "PAID"
            touch(v)
