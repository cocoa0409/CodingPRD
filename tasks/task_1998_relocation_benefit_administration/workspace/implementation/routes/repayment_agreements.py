from flask import Blueprint, request

from db import DB
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
    err_payment_exceeds_balance,
)
from middleware import get_actor, require_role, check_employee_owns_case
from response import success_object, success_list
from serializers import serialize_repayment
from util import require_fields, require_positive_int, get_pagination, add_months
from services.ledger import touch_entity
from services.repayment import arrears_threshold

bp = Blueprint("repayment_agreements", __name__)

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]


def _get_or_404(id):
    r = DB.repayment_agreements.get(id)
    if r is None:
        raise err_not_found("RepaymentAgreement not found")
    return r


@bp.route("/repayment-agreements/<id>", methods=["GET"])
def get_agreement(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        r = _get_or_404(id)
        return success_object(serialize_repayment(r))


@bp.route("/relocation-cases/<case_id>/repayment-agreements", methods=["GET"])
def list_case_agreements(case_id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    limit, offset = get_pagination(request.args)
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        items = [r for r in DB.repayment_agreements.values() if r["case_id"] == case_id]
        items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
        total_count = len(items)
        page = items[offset:offset + limit]
        return success_list([serialize_repayment(r) for r in page], limit, offset, total_count)


@bp.route("/repayment-agreements/<id>/sign", methods=["POST"])
def sign_agreement(id):
    actor = get_actor()
    require_role(actor, ["Employee"])
    with DB.lock:
        r = _get_or_404(id)
        case = DB.cases.get(r["case_id"])
        check_employee_owns_case(actor, case)
        if r["status"] == "SETTLED":
            raise err_already_terminal("Agreement is SETTLED")
        if r["status"] != "DRAFT":
            raise err_invalid_state("Agreement is not DRAFT")
        now = DB.now()
        r["signed_at"] = now
        r["next_due_date"] = add_months(now, 1)
        r["status"] = "ACTIVE"
        touch_entity(r)
        return success_object(serialize_repayment(r))


@bp.route("/repayment-agreements/<id>/payments", methods=["POST"])
def record_payment(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["amount_cents"])
    amount = require_positive_int(payload, "amount_cents")
    with DB.lock:
        r = _get_or_404(id)
        if r["status"] == "SETTLED":
            raise err_already_terminal("Agreement is SETTLED")
        if r["status"] == "DRAFT":
            raise err_invalid_state("Agreement is DRAFT (not yet payable)")
        if r["status"] not in ("ACTIVE", "DEFAULTED"):
            raise err_invalid_state("Agreement not in a payable state")
        if amount > r["balance_cents"]:
            raise err_payment_exceeds_balance("Payment exceeds outstanding balance")
        r["paid_to_date_cents"] = r.get("paid_to_date_cents", 0) + amount
        r["balance_cents"] = r["total_owed_cents"] - r["paid_to_date_cents"]
        # auto transitions
        if r["balance_cents"] == 0:
            r["status"] = "SETTLED"
        elif r["status"] == "DEFAULTED":
            threshold = arrears_threshold(r, DB.now())
            if r["paid_to_date_cents"] >= threshold:
                r["status"] = "ACTIVE"
        touch_entity(r)
        return success_object(serialize_repayment(r))


@bp.route("/repayment-agreements/<id>/reverse-payment", methods=["POST"])
def reverse_payment(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["amount_cents"])
    amount = require_positive_int(payload, "amount_cents")
    with DB.lock:
        r = _get_or_404(id)
        # Reverse can be applied to ACTIVE/SETTLED/DEFAULTED (a settled agreement can reopen)
        if r["status"] == "DRAFT":
            raise err_invalid_state("Agreement is DRAFT")
        new_paid = r.get("paid_to_date_cents", 0) - amount
        if new_paid < 0:
            raise err_invalid_request("Reversal would drive paid_to_date_cents below zero")
        r["paid_to_date_cents"] = new_paid
        r["balance_cents"] = r["total_owed_cents"] - r["paid_to_date_cents"]
        if r["status"] == "SETTLED" and r["balance_cents"] > 0:
            r["status"] = "ACTIVE"
        touch_entity(r)
        return success_object(serialize_repayment(r))


@bp.route("/repayment-agreements/<id>/mark-default", methods=["POST"])
def mark_default(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    with DB.lock:
        r = _get_or_404(id)
        if r["status"] == "SETTLED":
            raise err_already_terminal("Agreement is SETTLED")
        if r["status"] != "ACTIVE":
            raise err_invalid_state("Agreement is not ACTIVE")
        now = DB.now()
        if r.get("next_due_date") is None or now <= r["next_due_date"]:
            raise err_invalid_state("Logical clock has not passed next_due_date")
        threshold = arrears_threshold(r, now)
        if r.get("paid_to_date_cents", 0) >= threshold:
            raise err_invalid_state("Installments not missed")
        r["status"] = "DEFAULTED"
        touch_entity(r)
        return success_object(serialize_repayment(r))
