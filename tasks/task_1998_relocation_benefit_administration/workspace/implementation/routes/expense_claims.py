from flask import Blueprint, request

from db import DB
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_already_terminal,
    err_case_not_open, err_stale_version, err_cap_exceeded,
)
from middleware import get_actor, require_role, check_employee_owns_case
from response import success_object, success_list
from serializers import serialize_claim
from util import (
    require_fields, require_enum, require_string, get_pagination,
)
from services.caps import remaining_headroom
from services.ledger import touch_entity, commit, pay
from services.gross_up import compute_gross_up

bp = Blueprint("expense_claims", __name__)

ALL_ROLES = ["MobilityCoordinator", "FinanceSpecialist", "ProgramManager", "Employee", "Vendor"]

CATEGORIES = {"MEALS", "LODGING", "TRANSPORT", "MISC"}
PAYMENT_METHODS = {"REIMBURSEMENT", "DIRECT_BILL"}

TERMINAL = {"PAID"}


def _get_or_404(id):
    c = DB.expense_claims.get(id)
    if c is None:
        raise err_not_found("ExpenseClaim not found")
    return c


def _validate_lines(lines):
    if not isinstance(lines, list) or len(lines) == 0:
        raise err_invalid_request("lines must be a non-empty array")
    for line in lines:
        if not isinstance(line, dict):
            raise err_invalid_request("each line must be an object")
        desc = line.get("description")
        amt = line.get("amount_cents")
        if not isinstance(desc, str) or not desc:
            raise err_invalid_request("line.description must be a non-empty string")
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            raise err_invalid_request("line.amount_cents must be a positive integer")


@bp.route("/expense-claims", methods=["POST"])
def create_claim():
    actor = get_actor()
    require_role(actor, ["Employee"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["case_id", "category", "payment_method", "lines"])
    case_id = require_string(payload, "case_id")
    category = require_enum(payload, "category", CATEGORIES)
    payment_method = require_enum(payload, "payment_method", PAYMENT_METHODS)
    lines = payload.get("lines")
    _validate_lines(lines)

    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        check_employee_owns_case(actor, case)
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        policy = DB.policies.get(case["policy_id"])
        amount_cents = sum(l["amount_cents"] for l in lines)
        headroom = remaining_headroom(case, policy, "MISC")
        if amount_cents > headroom:
            raise err_cap_exceeded("Claim exceeds remaining MISC headroom")
        now = DB.now()
        c = {
            "id": DB.new_id(),
            "case_id": case_id,
            "category": category,
            "payment_method": payment_method,
            "lines": [{"description": l["description"], "amount_cents": l["amount_cents"]} for l in lines],
            "amount_cents": amount_cents,
            "taxable": payment_method == "REIMBURSEMENT",
            "gross_up_cents": 0,
            "total_payment_cents": 0,
            "status": "SUBMITTED",
            "reject_reason": None,
            "paid_at": None,
            "created_at": now,
            "updated_at": now,
            "version": 0,
            "_seq": DB.next_seq(),
        }
        DB.expense_claims[c["id"]] = c
        return success_object(serialize_claim(c), status=201)


@bp.route("/expense-claims/<id>", methods=["GET"])
def get_claim(id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    with DB.lock:
        c = _get_or_404(id)
        return success_object(serialize_claim(c))


@bp.route("/relocation-cases/<case_id>/expense-claims", methods=["GET"])
def list_case_claims(case_id):
    actor = get_actor()
    require_role(actor, ALL_ROLES)
    limit, offset = get_pagination(request.args)
    status = request.args.get("status")
    with DB.lock:
        case = DB.cases.get(case_id)
        if case is None:
            raise err_not_found("Case not found")
        items = [c for c in DB.expense_claims.values() if c["case_id"] == case_id]
        if status is not None:
            items = [c for c in items if c["status"] == status]
        items.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))
        total_count = len(items)
        page = items[offset:offset + limit]
        return success_list([serialize_claim(c) for c in page], limit, offset, total_count)


@bp.route("/expense-claims/<id>/approve", methods=["POST"])
def approve_claim(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["expected_case_version"])
    expected_case_version = payload.get("expected_case_version")
    if isinstance(expected_case_version, bool) or not isinstance(expected_case_version, int):
        raise err_invalid_request("expected_case_version must be an integer")
    with DB.lock:
        c = _get_or_404(id)
        if c["status"] in TERMINAL:
            raise err_already_terminal("Claim is PAID")
        if c["status"] != "SUBMITTED":
            raise err_invalid_state("Claim is not SUBMITTED")
        case = DB.cases.get(c["case_id"])
        if case is None:
            raise err_not_found("Case not found")
        if expected_case_version != case["version"]:
            raise err_stale_version("expected_case_version does not match current case version")
        if case["status"] != "IN_PROGRESS":
            raise err_case_not_open("Case is not IN_PROGRESS")
        policy = DB.policies.get(case["policy_id"])
        headroom = remaining_headroom(case, policy, "MISC")
        if c["amount_cents"] > headroom:
            raise err_cap_exceeded("Claim exceeds remaining MISC headroom")
        c["status"] = "APPROVED"
        touch_entity(c)
        commit(case, c["amount_cents"])
        return success_object(serialize_claim(c))


@bp.route("/expense-claims/<id>/reject", methods=["POST"])
def reject_claim(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["reject_reason"])
    reason = require_string(payload, "reject_reason")
    with DB.lock:
        c = _get_or_404(id)
        if c["status"] in TERMINAL:
            raise err_already_terminal("Claim is PAID")
        if c["status"] != "SUBMITTED":
            raise err_invalid_state("Claim is not SUBMITTED")
        c["status"] = "REJECTED"
        c["reject_reason"] = reason
        touch_entity(c)
        return success_object(serialize_claim(c))


@bp.route("/expense-claims/<id>/resubmit", methods=["POST"])
def resubmit_claim(id):
    actor = get_actor()
    require_role(actor, ["Employee"])
    payload = request.get_json(silent=True) or {}
    lines = payload.get("lines")
    if lines is not None:
        _validate_lines(lines)
    with DB.lock:
        c = _get_or_404(id)
        case = DB.cases.get(c["case_id"])
        check_employee_owns_case(actor, case)
        if c["status"] in TERMINAL:
            raise err_already_terminal("Claim is PAID")
        if c["status"] != "REJECTED":
            raise err_invalid_state("Claim is not REJECTED")
        if lines is not None:
            c["lines"] = [{"description": l["description"], "amount_cents": l["amount_cents"]} for l in lines]
            c["amount_cents"] = sum(l["amount_cents"] for l in c["lines"])
        c["reject_reason"] = None
        c["status"] = "SUBMITTED"
        touch_entity(c)
        return success_object(serialize_claim(c))


@bp.route("/expense-claims/<id>/pay", methods=["POST"])
def pay_claim(id):
    actor = get_actor()
    require_role(actor, ["FinanceSpecialist"])
    with DB.lock:
        c = _get_or_404(id)
        if c["status"] in TERMINAL:
            raise err_already_terminal("Claim is PAID")
        if c["status"] != "APPROVED":
            raise err_invalid_state("Claim is not APPROVED")
        case = DB.cases.get(c["case_id"])
        if case is None:
            raise err_not_found("Case not found")
        policy = DB.policies.get(case["policy_id"])
        gross_up = compute_gross_up(c, case, policy)
        c["gross_up_cents"] = gross_up
        c["total_payment_cents"] = c["amount_cents"] + gross_up
        c["paid_at"] = DB.now()
        c["status"] = "PAID"
        touch_entity(c)
        # ledger: committed -= amount_cents; paid += total_payment_cents
        pay(case, c["amount_cents"], c["total_payment_cents"])
        if c.get("taxable"):
            case["cumulative_taxable_paid_cents"] = case.get("cumulative_taxable_paid_cents", 0) + c["amount_cents"]
        return success_object(serialize_claim(c))
