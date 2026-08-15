"""Settlement endpoints (PRD §3.8): year-end tax equalization reconciliation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_SETTLEMENT,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_VENDOR_NOT_FILED,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import hypothetical_tax_final
from services.core import (
    assignment_of, create_chargeback_entry, employee_of_assignment, new_record,
    rerun_overrun_posture_check, touch,
)
from validate import get_body, opt_str, req_field, req_int, require_fk, require_path_resource

bp = Blueprint("settlements", __name__)

OPEN_SETTLEMENT_STATES = {"CALCULATED", "PENDING_REVIEW", "APPROVED", "DISPUTED"}
CREATABLE_ASSIGNMENT_STATES = {"ACTIVE", "REPATRIATION_PENDING", "REPATRIATED"}


def _select_filed_engagement(assignment_id, tax_year):
    """Deterministic selection (PRD §3.8): status FILED or CLOSED with filed
    gross recorded; FILED ranks ahead of CLOSED, then most recently updated,
    then most recently created. None when the eligible set is empty."""
    eligible = [
        ve for ve in db["vendor_engagements"].values()
        if ve["assignment_id"] == assignment_id and ve["tax_year"] == tax_year
        and ve["status"] in ("FILED", "CLOSED") and ve["filed_total_gross_cents"] is not None
    ]
    if not eligible:
        return None
    eligible.sort(
        key=lambda ve: (
            0 if ve["status"] == "FILED" else 1,
            _desc_key(ve["updated_at"]),
            _desc_key(ve["created_at"]),
            _desc_key(ve["id"]),
        )
    )
    return eligible[0]


def _desc_key(s):
    """Invert an ISO timestamp/id string so ascending sort = most recent first."""
    return "".join(chr(0x10FFFF - ord(c)) for c in s)


def _reconcile(settlement):
    """settlement_reconciliation (PRD §3.8): POSTED records only, scoped to the
    settlement's (assignment_id, tax_year); FINAL hypo tax on the filed gross."""
    asg = assignment_of(settlement)
    employee = employee_of_assignment(asg)
    total_withheld = sum(
        r["hypothetical_tax_cents"]
        for r in db["shadow_payroll_records"].values()
        if r["assignment_id"] == asg["id"] and r["tax_year"] == settlement["tax_year"]
        and r["status"] == "POSTED"
    )
    engagement = db["vendor_engagements"].get(settlement["vendor_engagement_id"])
    final_tax = hypothetical_tax_final(engagement["filed_total_gross_cents"], employee["family_size"])
    amount = total_withheld - final_tax
    settlement["total_hypo_withheld_cents"] = total_withheld
    settlement["final_hypo_tax_cents"] = final_tax
    settlement["settlement_amount_cents"] = amount
    settlement["direction"] = (
        "EMPLOYEE_CREDIT" if amount > 0 else "EMPLOYEE_DEBIT" if amount < 0 else "ZERO"
    )


@bp.post("/mobility/settlements")
def create_settlement():
    caller = authorized(["PayrollSpecialist"])
    body = get_body()
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    tax_year = req_int(body, "tax_year")
    # State gate (priority 5).
    if asg["status"] not in CREATABLE_ASSIGNMENT_STATES:
        raise_error(ERR_INVALID_STATE, "settlement creation requires an ACTIVE, REPATRIATION_PENDING, or REPATRIATED assignment")
    # Referential gate (priority 8): a filed engagement must exist for the year.
    engagement = _select_filed_engagement(asg["id"], tax_year)
    if engagement is None:
        raise_error(ERR_VENDOR_NOT_FILED, "no FILED vendor engagement exists for this tax year")
    # Uniqueness (priority 10): at most one open settlement per year.
    for s in db["settlements"].values():
        if (s["assignment_id"] == asg["id"] and s["tax_year"] == tax_year
                and s["status"] in OPEN_SETTLEMENT_STATES):
            raise_error(ERR_DUPLICATE_SETTLEMENT, "an open settlement already exists for this tax year")

    rec = new_record("settlements", {
        "assignment_id": asg["id"],
        "tax_year": tax_year,
        "vendor_engagement_id": engagement["id"],
        "total_hypo_withheld_cents": 0,
        "final_hypo_tax_cents": 0,
        "settlement_amount_cents": 0,
        "direction": "ZERO",
        "status": "CALCULATED",
        "created_by_user_id": caller.user_id,
        "approved_by_user_id": None,
        "dispute_reason": None,
    })
    _reconcile(rec)
    return success_object(public(rec), status=201)


@bp.get("/mobility/settlements/<rid>")
def get_settlement(rid):
    return get_one("settlements", rid)


@bp.get("/mobility/settlements")
def list_settlements():
    return list_response("settlements", {
        "assignment_id": request.args.get("assignment_id"),
        "tax_year": request.args.get("tax_year"),
        "status": request.args.get("status"),
        "vendor_engagement_id": request.args.get("vendor_engagement_id"),
    })


@bp.post("/mobility/settlements/<rid>/submit")
def submit_settlement(rid):
    authorized(["PayrollSpecialist"])
    s = require_path_resource("settlements", rid)
    if s["status"] != "CALCULATED":
        raise_error(ERR_INVALID_STATE, "only a CALCULATED settlement can be submitted")
    s["status"] = "PENDING_REVIEW"
    touch(s)
    return success_object(public(s))


@bp.post("/mobility/settlements/<rid>/approve")
def approve_settlement(rid):
    caller = authorized(["FinanceController"])
    s = require_path_resource("settlements", rid)
    if s["status"] != "PENDING_REVIEW":
        raise_error(ERR_INVALID_STATE, "only a PENDING_REVIEW settlement can be approved")
    if caller.user_id == s["created_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES, "the settlement approver must differ from its creator")
    if s["settlement_amount_cents"] == 0:
        # Zero-amount boundary: skips APPROVED, settles directly, no chargeback.
        s["status"] = "SETTLED"
    else:
        s["status"] = "APPROVED"
        s["approved_by_user_id"] = caller.user_id
    touch(s)
    return success_object(public(s))


@bp.post("/mobility/settlements/<rid>/dispute")
def dispute_settlement(rid):
    caller = authorized(["Assignee"])
    body = get_body()
    s = require_path_resource("settlements", rid)
    # Assignee ownership (validation priority 2): X-User-ID must equal the
    # target assignment's employee_id.
    asg = assignment_of(s)
    if asg is None or caller.user_id != asg["employee_id"]:
        raise_error(ERR_FORBIDDEN_FOR_ROLE, "an assignee may dispute only their own assignment's settlement")
    if s["status"] != "PENDING_REVIEW":
        raise_error(ERR_INVALID_STATE, "only a PENDING_REVIEW settlement can be disputed")
    s["status"] = "DISPUTED"
    s["dispute_reason"] = opt_str(body, "reason", None)
    touch(s)
    return success_object(public(s))


@bp.post("/mobility/settlements/<rid>/recalculate")
def recalculate_settlement(rid):
    authorized(["PayrollSpecialist"])
    s = require_path_resource("settlements", rid)
    if s["status"] != "DISPUTED":
        raise_error(ERR_INVALID_STATE, "only a DISPUTED settlement can be recalculated")
    engagement = db["vendor_engagements"].get(s["vendor_engagement_id"])
    if (engagement is None or engagement["status"] not in ("FILED", "CLOSED")
            or engagement["filed_total_gross_cents"] is None):
        raise_error(ERR_VENDOR_NOT_FILED, "the linked vendor engagement is no longer FILED or CLOSED")
    _reconcile(s)
    s["status"] = "CALCULATED"
    s["dispute_reason"] = None
    touch(s)
    return success_object(public(s))


@bp.post("/mobility/settlements/<rid>/settle")
def settle_settlement(rid):
    authorized(["FinanceController"])
    s = require_path_resource("settlements", rid)
    if s["status"] != "APPROVED" or s["settlement_amount_cents"] == 0:
        raise_error(ERR_INVALID_STATE, "only an APPROVED nonzero settlement can be settled")
    asg = assignment_of(s)
    s["status"] = "SETTLED"
    touch(s)
    # Cascade hop 1: SETTLEMENT chargeback entry (signed; EMPLOYEE_DEBIT is negative).
    entry = create_chargeback_entry(
        asg, "SETTLEMENT", s["settlement_amount_cents"], source_settlement_id=s["id"])
    # Cascade hop 2: assignment YTD chargeback.
    asg["ytd_chargeback_cents"] += entry["amount_cents"]
    touch(asg, bump_version=False)
    # Cascade hop 3: the overrun posture check.
    rerun_overrun_posture_check(asg)
    return success_object(public(s))
