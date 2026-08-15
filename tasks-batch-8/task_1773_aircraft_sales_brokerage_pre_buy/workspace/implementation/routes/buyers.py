"""Buyer registration and qualification endpoints (PRD 3.3)."""
from flask import Blueprint

import db as dbmod
from errors import ERR_BUYER_NOT_FOUND, ERR_INVALID_STATE, raise_error
from middleware import require_roles
from response import success_object
from services.core import new_record, serialize, touch
from validate import body, req_money, req_str

bp = Blueprint("buyers", __name__)


@bp.post("/api/buyers")
@require_roles(["BuyerAgent"])
def create_buyer():
    b = body()
    rec = new_record(
        "buyers",
        {
            "full_name": req_str(b, "full_name"),
            "email": req_str(b, "email"),
            "qualification_status": "UNQUALIFIED",
            "qualified_budget_usd": None,
            "proof_of_funds_ref": None,
        },
    )
    return success_object(serialize("buyers", rec), 201)


@bp.post("/api/buyers/<buyer_id>/qualify")
@require_roles(["BuyerAgent"])
def qualify_buyer(buyer_id):
    buyer = dbmod.db["buyers"].get(buyer_id)
    if buyer is None:
        raise_error(ERR_BUYER_NOT_FOUND, "buyer id does not exist")
    b = body()
    budget = req_money(b, "qualified_budget_usd", allow_zero=True)
    proof = req_str(b, "proof_of_funds_ref")
    if buyer["qualification_status"] != "UNQUALIFIED":
        raise_error(ERR_INVALID_STATE, "buyer is already QUALIFIED")
    buyer["qualification_status"] = "QUALIFIED"
    buyer["qualified_budget_usd"] = budget
    buyer["proof_of_funds_ref"] = proof
    touch(buyer)
    return success_object(serialize("buyers", buyer))
