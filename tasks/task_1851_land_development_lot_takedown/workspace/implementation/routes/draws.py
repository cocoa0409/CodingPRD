"""LoanDraw endpoints (PRD 3.6): request/approve/fund/reverse with SoD."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DRAW_EXCEEDS_COMMITMENT,
    ERR_DRAW_INVALID_STATE,
    ERR_LOAN_NOT_ACTIVE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_INVALID_REQUEST,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services import calculations as calc
from services.core import new_record, touch
from validate import check_body_fk_exists, get_body, req_str, require_path

bp = Blueprint("draws", __name__)

OPEN_DRAW_STATUSES = ("REQUESTED", "APPROVED", "FUNDED")


def _validate_line_items(body):
    """Priority 4: line_items must be a non-empty array of {description,
    amount_cents >= 1}."""
    items = body.get("line_items")
    if not isinstance(items, list) or len(items) < 1:
        raise_error(ERR_INVALID_REQUEST, "line_items must be a non-empty array")
    for item in items:
        if not isinstance(item, dict):
            raise_error(ERR_INVALID_REQUEST, "line_items entries must be objects")
        desc = item.get("description")
        if not isinstance(desc, str):
            raise_error(ERR_INVALID_REQUEST, "line_items[].description must be a string")
        amount = item.get("amount_cents")
        if amount is None or isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            raise_error(ERR_INVALID_REQUEST, "line_items[].amount_cents must be an integer >= 1")
    return [{"description": item["description"], "amount_cents": item["amount_cents"]}
            for item in items]


@bp.post("/loan-draws")
def create_draw():
    caller = authorized(["DeveloperOperator"])
    body = get_body()
    # Priority 3: body FK existence
    check_body_fk_exists("loans", body, "loan_id")
    # Priority 4: shape
    loan_id = req_str(body, "loan_id")
    line_items = _validate_line_items(body)
    loan = db["loans"][loan_id]
    # Priority 10 (referential): the loan must be ACTIVE
    if loan["status"] != "ACTIVE":
        raise_error(ERR_LOAN_NOT_ACTIVE, "draws require an ACTIVE loan")
    # Disbursement arithmetic frozen at creation in pinned rounding order
    gross, retainage, fee, net = calc.draw_disbursement(line_items)
    # Priority 11 (fiscal): cumulative gross of non-terminal draws + new gross
    # must not exceed the commitment
    cumulative = sum(
        d["gross_amount_cents"]
        for d in db["draws"].values()
        if d["loan_id"] == loan_id and d["status"] in OPEN_DRAW_STATUSES
    )
    if cumulative + gross > loan["commitment_amount_cents"]:
        raise_error(ERR_DRAW_EXCEEDS_COMMITMENT,
                    "cumulative draw gross would exceed commitment_amount_cents")
    rec = new_record("draws", {
        "loan_id": loan_id,
        "requested_by_user_id": caller.user_id,
        "line_items": line_items,
        "gross_amount_cents": gross,
        "retainage_cents": retainage,
        "draw_fee_cents": fee,
        "net_disbursed_cents": net,
        "approved_by_user_id": None,
        "status": "REQUESTED",
    })
    return success_object(public(rec), status=201)


@bp.get("/loan-draws")
def list_draws():
    return list_response("draws", {
        "loan_id": request.args.get("loan_id"),
        "status": request.args.get("status"),
    })


@bp.get("/loan-draws/<rid>")
def get_draw(rid):
    return get_one("draws", rid)


@bp.post("/loan-draws/<rid>/approve")
def approve_draw(rid):
    caller = authorized(["LenderOfficer"])
    draw = require_path("draws", rid)
    # Priority 6 (state) before Priority 7 (SoD)
    if draw["status"] != "REQUESTED":
        raise_error(ERR_DRAW_INVALID_STATE, "approve requires REQUESTED")
    # Priority 7: the approver must differ from the requester
    if caller.user_id == draw["requested_by_user_id"]:
        raise_error(ERR_SEGREGATION_OF_DUTIES,
                    "draw approver must differ from the requester")
    draw["approved_by_user_id"] = caller.user_id
    draw["status"] = "APPROVED"
    touch(draw)
    return success_object(public(draw))


@bp.post("/loan-draws/<rid>/reject")
def reject_draw(rid):
    authorized(["LenderOfficer"])
    draw = require_path("draws", rid)
    if draw["status"] != "REQUESTED":
        raise_error(ERR_DRAW_INVALID_STATE, "reject requires REQUESTED")
    draw["status"] = "REJECTED"
    touch(draw)
    return success_object(public(draw))


@bp.post("/loan-draws/<rid>/fund")
def fund_draw(rid):
    authorized(["LenderOfficer"])
    draw = require_path("draws", rid)
    if draw["status"] != "APPROVED":
        raise_error(ERR_DRAW_INVALID_STATE, "fund requires APPROVED")
    # Priority 10 (referential): the loan must still be ACTIVE
    loan = db["loans"][draw["loan_id"]]
    if loan["status"] != "ACTIVE":
        raise_error(ERR_LOAN_NOT_ACTIVE, "funding requires the loan to be ACTIVE")
    loan["outstanding_balance_cents"] += draw["net_disbursed_cents"]
    loan["total_drawn_cents"] += draw["net_disbursed_cents"]
    touch(loan)
    draw["status"] = "FUNDED"
    touch(draw)
    return success_object(public(draw))


@bp.post("/loan-draws/<rid>/reverse")
def reverse_draw(rid):
    authorized(["LenderOfficer"])
    draw = require_path("draws", rid)
    if draw["status"] != "FUNDED":
        raise_error(ERR_DRAW_INVALID_STATE, "reverse requires FUNDED")
    # Compensating action: fund + reverse leaves loan balances unchanged
    loan = db["loans"][draw["loan_id"]]
    loan["outstanding_balance_cents"] -= draw["net_disbursed_cents"]
    loan["total_drawn_cents"] -= draw["net_disbursed_cents"]
    touch(loan)
    draw["status"] = "REVERSED"
    touch(draw)
    return success_object(public(draw))
