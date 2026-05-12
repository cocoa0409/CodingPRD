"""ComplianceDeclaration and PenaltyOrder endpoints."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import clock
import db
import errors
import helpers
import response
from middleware import auth_required, get_actor
from serializers import compliance_declaration_dict, penalty_order_dict
from services import audit
from services.calculations import (
    calc_compliance_balance,
    calc_penalty,
    ccer_cap_value,
    borrow_cap_value,
)
from helpers import to_dec, bump


bp = Blueprint("compliance", __name__)


@bp.route("/enterprises/<eid>/compliance-declarations", methods=["POST"])
@auth_required("Enterprise")
def create_declaration(eid):
    if eid not in db.enterprises:
        errors.raise_error(errors.ERR_NOT_FOUND, f"Enterprise {eid} not found.")
    user_id, _ = get_actor()
    if user_id != eid:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Enterprise can only create declarations for itself.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["cycle_year"])
    cycle_year = int(body["cycle_year"])
    common = helpers.common_create()
    d = {
        "id": db.new_id(),
        "enterprise_id": eid,
        "cycle_year": cycle_year,
        "declared_offset_quota": Decimal("0"),
        "declared_offset_ccer": Decimal("0"),
        "declared_borrow_amount": Decimal("0"),
        "declared_bank_amount": Decimal("0"),
        "status": "DRAFT",
        "deficit_amount": Decimal("0"),
        "surplus_amount": Decimal("0"),
        **common,
    }
    db.compliance_declarations[d["id"]] = d
    return response.created(compliance_declaration_dict(d))


@bp.route("/compliance-declarations/<did>/submit", methods=["POST"])
@auth_required("Enterprise")
def submit_declaration(did):
    d = db.compliance_declarations.get(did)
    if d is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"ComplianceDeclaration {did} not found.")
    if d["status"] != "DRAFT":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Declaration must be DRAFT to submit; is {d['status']}.")
    user_id, _ = get_actor()
    if d["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION,
                           "Acting enterprise does not own this declaration.")
    body = helpers.get_json_body()
    helpers.require_fields(body, ["declared_offset_quota", "declared_offset_ccer"])
    helpers.check_occ(d, body.get("version"))

    declared_offset_quota = to_dec(body["declared_offset_quota"])
    declared_offset_ccer = to_dec(body["declared_offset_ccer"])
    declared_borrow_amount = to_dec(body.get("declared_borrow_amount", 0))
    declared_bank_amount = to_dec(body.get("declared_bank_amount", 0))

    # Look up cycle.
    cycle = None
    for c in db.allocation_cycles.values():
        if c["cycle_year"] == d["cycle_year"]:
            cycle = c
            break
    if cycle is None:
        errors.raise_error(errors.ERR_NOT_FOUND,
                           f"AllocationCycle for cycle_year {d['cycle_year']} not found.")

    # Find FINALIZED emission report for this enterprise / cycle.
    finalized_report = None
    for r in db.emission_reports.values():
        if (r["enterprise_id"] == d["enterprise_id"]
                and r["cycle_year"] == d["cycle_year"]
                and r["status"] == "FINALIZED"):
            finalized_report = r
            break
    if finalized_report is None:
        errors.raise_error(errors.ERR_INVALID_STATE,
                           "No FINALIZED EmissionReport for this enterprise/cycle.")

    if clock.now() > cycle["compliance_deadline"]:
        errors.raise_error(errors.ERR_WINDOW_CLOSED,
                           "Past compliance deadline.")

    # Check no existing SUBMITTED/COMPLIANT/NON_COMPLIANT/PENALIZED/FINALIZED declaration
    # for (enterprise, cycle_year) — only one allowed.
    for other in db.compliance_declarations.values():
        if (other["id"] != did
                and other["enterprise_id"] == d["enterprise_id"]
                and other["cycle_year"] == d["cycle_year"]
                and other["status"] != "DRAFT"):
            errors.raise_error(errors.ERR_DECLARATION_ALREADY_SUBMITTED,
                               "A declaration for this enterprise+cycle is already submitted.")

    verified = to_dec(finalized_report["total_verified_emissions"])
    # Cap validations (priority order: CCER cap, borrow cap, balance).
    ccer_cap = ccer_cap_value(verified, cycle["ccer_cap_pct"])
    if declared_offset_ccer > ccer_cap:
        errors.raise_error(errors.ERR_CCER_CAP_EXCEEDED,
                           f"declared_offset_ccer {declared_offset_ccer} exceeds cap {ccer_cap}.")
    borrow_cap = borrow_cap_value(verified)
    if declared_borrow_amount > borrow_cap:
        errors.raise_error(errors.ERR_BORROW_CAP_EXCEEDED,
                           f"declared_borrow_amount {declared_borrow_amount} exceeds cap {borrow_cap}.")
    e = db.enterprises[d["enterprise_id"]]
    free_plus_paid = to_dec(e["quota_balance"]) + to_dec(e["paid_quota_balance"])
    if free_plus_paid < declared_offset_quota:
        errors.raise_error(errors.ERR_INSUFFICIENT_BALANCE,
                           "Insufficient quota balance for declared offset.")
    if to_dec(e["ccer_balance"]) < declared_offset_ccer:
        errors.raise_error(errors.ERR_INSUFFICIENT_BALANCE,
                           "Insufficient CCER balance for declared offset.")

    # Apply: compute deficit/surplus, then retire, then status.
    deficit, surplus = calc_compliance_balance(
        verified, declared_offset_quota, declared_offset_ccer, declared_borrow_amount,
    )
    d["declared_offset_quota"] = declared_offset_quota
    d["declared_offset_ccer"] = declared_offset_ccer
    d["declared_borrow_amount"] = declared_borrow_amount
    d["declared_bank_amount"] = declared_bank_amount
    d["deficit_amount"] = deficit
    d["surplus_amount"] = surplus
    d["status"] = "SUBMITTED"
    bump(d)

    # Retire balances: free quota first, then paid.
    spend_free = min(to_dec(e["quota_balance"]), declared_offset_quota)
    e["quota_balance"] = to_dec(e["quota_balance"]) - spend_free
    remaining = declared_offset_quota - spend_free
    if remaining > 0:
        e["paid_quota_balance"] = to_dec(e["paid_quota_balance"]) - remaining
    e["ccer_balance"] = to_dec(e["ccer_balance"]) - declared_offset_ccer
    bump(e)

    audit.append(
        subject_type="QUOTA_CHANGE",
        subject_id=d["id"],
        enterprise_id=e["id"],
        action="COMPLIANCE_RETIRE",
        delta_quota=-declared_offset_quota,
        delta_ccer=-declared_offset_ccer,
    )

    # Auto-transition: deficit==0 -> COMPLIANT; deficit>0 -> NON_COMPLIANT + create penalty.
    if deficit == 0:
        d["status"] = "COMPLIANT"
        bump(d)
        # Sync to RegulatorSystem (audit log).
        audit.append(
            subject_type="EXTERNAL_SYNC",
            subject_id=d["id"],
            enterprise_id=e["id"],
            action="COMPLIANCE_SYNC",
            external_system="REGULATOR",
        )
    else:
        d["status"] = "NON_COMPLIANT"
        bump(d)
        severity, penalty_rate, penalty_amount, mandatory_deduction = calc_penalty(
            deficit, verified, e["jurisdiction_code"],
        )
        now = clock.now()
        common = helpers.common_create()
        p = {
            "id": db.new_id(),
            "declaration_id": d["id"],
            "enterprise_id": e["id"],
            "cycle_year": d["cycle_year"],
            "severity": severity,
            "penalty_rate": penalty_rate,
            "deficit_amount": deficit,
            "penalty_amount": penalty_amount,
            "mandatory_deduction_amount": mandatory_deduction,
            "payment_status": "UNPAID",
            "payment_due_at": now + timedelta(days=30),
            "paid_at": None,
            "credit_record_reported": False,
            **common,
        }
        db.penalty_orders[p["id"]] = p
        audit.append(
            subject_type="EXTERNAL_SYNC",
            subject_id=d["id"],
            enterprise_id=e["id"],
            action="COMPLIANCE_SYNC",
            external_system="REGULATOR",
        )
        # Surface the cascade-created PenaltyOrder id so callers can read
        # it without scanning audit logs (PRD §3.6: NON_COMPLIANT cascade
        # auto-creates a PenaltyOrder).
        out = compliance_declaration_dict(d)
        out["penalty_order_id"] = p["id"]
        return response.ok(out)

    return response.ok(compliance_declaration_dict(d))


@bp.route("/penalty-orders/<pid>/pay", methods=["POST"])
@auth_required("Enterprise")
def pay_penalty(pid):
    p = db.penalty_orders.get(pid)
    if p is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"PenaltyOrder {pid} not found.")
    user_id, _ = get_actor()
    if p["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION, "Not your penalty order.")
    if p["payment_status"] == "OVERDUE":
        errors.raise_error(errors.ERR_PENALTY_OVERDUE, "Penalty is OVERDUE.")
    if p["payment_status"] != "UNPAID":
        errors.raise_error(errors.ERR_INVALID_STATE,
                           f"Penalty must be UNPAID to pay; is {p['payment_status']}.")
    body = helpers.get_json_body()
    helpers.check_occ(p, body.get("version"))
    if clock.now() > p["payment_due_at"]:
        errors.raise_error(errors.ERR_PENALTY_OVERDUE, "Past payment_due_at.")
    p["payment_status"] = "PAID"
    p["paid_at"] = clock.now()
    p["credit_record_reported"] = True
    bump(p)
    # Cascade declaration NON_COMPLIANT -> PENALIZED.
    d = db.compliance_declarations[p["declaration_id"]]
    if d["status"] == "NON_COMPLIANT":
        d["status"] = "PENALIZED"
        bump(d)
    # Record pending mandatory deduction against next cycle.
    db.pending_deductions.append({
        "enterprise_id": p["enterprise_id"],
        "amount": to_dec(p["mandatory_deduction_amount"]),
        "source_penalty_id": p["id"],
        "recorded_at": clock.now(),
    })
    # PRD §3.6: 'An AuditLogEntry with action PENALTY_PAID and
    # external_system REGULATOR is appended.' (The §3.8 BANK-system note
    # refers to the BANK_PAYMENT_CONFIRMED event-driven path; the direct
    # pay-action emits with external_system=REGULATOR.)
    audit.append(
        subject_type="QUOTA_CHANGE",
        subject_id=p["id"],
        enterprise_id=p["enterprise_id"],
        action="PENALTY_PAID",
        external_system="REGULATOR",
    )
    return response.ok(penalty_order_dict(p))


@bp.route("/penalty-orders/<pid>", methods=["GET"])
@auth_required("Regulator", "Enterprise")
def read_penalty(pid):
    p = db.penalty_orders.get(pid)
    if p is None:
        errors.raise_error(errors.ERR_NOT_FOUND, f"PenaltyOrder {pid} not found.")
    user_id, user_role = get_actor()
    if user_role == "Enterprise" and p["enterprise_id"] != user_id:
        errors.raise_error(errors.ERR_OWNERSHIP_VIOLATION, "Not your penalty order.")
    return response.ok(penalty_order_dict(p))
