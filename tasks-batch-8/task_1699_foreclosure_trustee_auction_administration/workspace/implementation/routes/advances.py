"""CostAdvance routes: beneficiary submission, list, trustee review.

Review order: schema -> advance SUBMITTED -> (APPROVE: case non-terminal) /
(DENY: reason non-empty). Approval raises the beneficiary's outstanding
advances total; reimbursement is always a cascade (payoff accept or sale
close), never a direct action.
"""
from flask import Blueprint, request

import db
from db import stamp_new, touch
from errors import err_invalid_request, err_invalid_case_state
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services.domain import (get_case, get_advance, view,
                             check_beneficiary_owns_case, case_advances,
                             get_beneficiary, TERMINAL_CASE_STATES)
from services.validate import (get_body, check_unknown, req_enum, req_int,
                               req_date, opt_string)
from util import format_date

bp = Blueprint("advances", __name__)

ADVANCE_CATEGORIES = ("PUBLICATION", "RECORDING", "POSTING", "LEGAL",
                      "PROPERTY_PRESERVATION", "OTHER")


@bp.route("/api/foreclosure-cases/<case_id>/cost-advances", methods=["POST"], strict_slashes=False)
@require_roles("Beneficiary")
def submit_advance(user_id, role, case_id):
    case = get_case(case_id)
    check_beneficiary_owns_case(case, user_id, role)
    body = get_body()
    check_unknown(body, {"category", "amount_cents", "incurred_date"})
    category = req_enum(body, "category", ADVANCE_CATEGORIES)
    amount = req_int(body, "amount_cents", minimum=1)
    incurred = req_date(body, "incurred_date")
    # clock consistency (§2.5): incurred_date must not lie in the future
    if incurred > db.CLOCK.now_date():
        raise err_invalid_request("incurred_date must not lie in the future")
    if case["lifecycle_status"] in TERMINAL_CASE_STATES:
        raise err_invalid_case_state("cost advances require a non-terminal case")
    adv = {
        "foreclosure_case_id": case["id"],
        "category": category,
        "amount_cents": amount,
        "incurred_date": format_date(incurred),
        "status": "SUBMITTED",
        "denial_reason": None,
        "submitted_by_beneficiary_id": user_id,
        "_reimbursed_by_sale_id": None,
    }
    stamp_new(adv)
    db.cost_advances[adv["id"]] = adv
    return success_object(view(adv), status=201)


@bp.route("/api/foreclosure-cases/<case_id>/cost-advances", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Beneficiary")
def list_advances(user_id, role, case_id):
    case = get_case(case_id)
    check_beneficiary_owns_case(case, user_id, role)
    items = case_advances(case_id)
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    limit, offset = parse_pagination(request.args)
    page = [view(a) for a in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/cost-advances/<advance_id>/review", methods=["POST"], strict_slashes=False)
@require_roles("CaseManager")
def review_advance(user_id, role, advance_id):
    adv = get_advance(advance_id)
    body = get_body()
    check_unknown(body, {"decision", "denial_reason"})
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    denial_reason = opt_string(body, "denial_reason")
    if adv["status"] != "SUBMITTED":
        # no dedicated catalog error for advance state; DENIED/REIMBURSED are
        # terminal and APPROVED is past review
        raise err_invalid_request("cost advance is not SUBMITTED")
    case = get_case(adv["foreclosure_case_id"])
    if decision == "APPROVE":
        if case["lifecycle_status"] in TERMINAL_CASE_STATES:
            raise err_invalid_case_state("approval requires a non-terminal case")
        adv["status"] = "APPROVED"
        touch(adv)
        ben = get_beneficiary(case["beneficiary_id"])
        ben["total_outstanding_advances_cents"] += adv["amount_cents"]
        touch(ben)
    else:  # DENY
        if denial_reason is None or denial_reason.strip() == "":
            raise err_invalid_request("denial_reason must be non-empty for DENY")
        adv["status"] = "DENIED"
        adv["denial_reason"] = denial_reason
        touch(adv)
    return success_object(view(adv))
