"""BiddingInstruction routes: submission (OCC on the case version), list,
withdrawal.

Submission order (PRD §3.5): caller ownership -> schema -> case state ->
version staleness -> opening-bid ceiling. Instruction activity is never
blocked by a stay hold.
"""
from flask import Blueprint, request

import db
from db import stamp_new, touch
from errors import (err_invalid_case_state, err_stale_case_version,
                    err_opening_exceeds_max, err_invalid_instruction_state,
                    err_invalid_sale_state)
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from services.domain import (get_case, get_instruction, view,
                             check_beneficiary_owns_case, case_instructions,
                             case_sales)
from services.validate import get_body, check_unknown, req_int, req_enum

bp = Blueprint("instructions", __name__)

INSTRUCTABLE_STATES = ("NOTS_RECORDED", "SALE_SCHEDULED")
STRATEGIES = ("OPENING_ONLY", "UP_TO_MAX")


@bp.route("/api/foreclosure-cases/<case_id>/bidding-instructions", methods=["POST"], strict_slashes=False)
@require_roles("Beneficiary")
def submit_instruction(user_id, role, case_id):
    case = get_case(case_id)
    # caller ownership first (PRD §3.5)
    check_beneficiary_owns_case(case, user_id, role)
    body = get_body()
    check_unknown(body, {"opening_bid_cents", "max_bid_cents", "strategy",
                         "expected_foreclosure_case_version"})
    opening = req_int(body, "opening_bid_cents", minimum=1)
    maximum = req_int(body, "max_bid_cents", minimum=1)
    strategy = req_enum(body, "strategy", STRATEGIES)
    expected = req_int(body, "expected_foreclosure_case_version")
    if case["lifecycle_status"] not in INSTRUCTABLE_STATES:
        raise err_invalid_case_state("instructions require NOTS_RECORDED or SALE_SCHEDULED")
    if expected != case["version"]:
        raise err_stale_case_version()
    if opening > maximum:
        raise err_opening_exceeds_max()
    # supersede the prior ACTIVE instruction
    for ins in case_instructions(case["id"]):
        if ins["status"] == "ACTIVE":
            ins["status"] = "SUPERSEDED"
            touch(ins)
    ins = {
        "foreclosure_case_id": case["id"],
        "opening_bid_cents": opening,
        "max_bid_cents": maximum,
        "strategy": strategy,
        "status": "ACTIVE",
    }
    stamp_new(ins)
    db.bidding_instructions[ins["id"]] = ins
    touch(case)
    return success_object(view(ins), status=201)


@bp.route("/api/foreclosure-cases/<case_id>/bidding-instructions", methods=["GET"], strict_slashes=False)
@require_roles("TrusteeAdmin", "CaseManager", "Auctioneer", "Beneficiary")
def list_instructions(user_id, role, case_id):
    case = get_case(case_id)
    check_beneficiary_owns_case(case, user_id, role)
    items = case_instructions(case_id)
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    limit, offset = parse_pagination(request.args)
    page = [view(i) for i in items[offset:offset + limit]]
    return success_list(page, limit, offset, len(items))


@bp.route("/api/bidding-instructions/<instruction_id>/withdraw", methods=["POST"], strict_slashes=False)
@require_roles("Beneficiary")
def withdraw_instruction(user_id, role, instruction_id):
    ins = get_instruction(instruction_id)
    body = get_body()
    check_unknown(body, set())
    case = get_case(ins["foreclosure_case_id"])
    check_beneficiary_owns_case(case, user_id, role)
    if ins["status"] != "ACTIVE":
        raise err_invalid_instruction_state()
    if case["lifecycle_status"] not in INSTRUCTABLE_STATES:
        raise err_invalid_case_state("withdrawal requires NOTS_RECORDED or SALE_SCHEDULED")
    # the instruction is locked from the moment the auctioneer cries the sale
    if any(s["status"] == "CONDUCTED" for s in case_sales(case["id"])):
        raise err_invalid_sale_state("a sale of the case is CONDUCTED; instruction locked")
    ins["status"] = "WITHDRAWN"
    touch(ins)
    return success_object(view(ins))
