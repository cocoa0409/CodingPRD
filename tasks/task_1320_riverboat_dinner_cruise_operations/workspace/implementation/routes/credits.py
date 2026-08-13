"""Cruise credits: read one, redeem a settled credit."""
from flask import Blueprint

import db
from errors import err_invalid_state
from response import ok
from serializers import serialize as _sz, serialize_list as _szl
from services import core as svc
from util import require_auth, get_or_404, get_json

bp = Blueprint("credits", __name__)


@bp.get("/credits/<cid>")
def get_credit(cid):
    require_auth(["OperationsManager", "CharterSalesAgent", "Customer"])
    credit = get_or_404(db.credits, cid, "credit", "Cruise credit not found")
    return ok(_sz("credit", credit))


@bp.post("/credits/<cid>/redeem")
def redeem_credit(cid):
    require_auth(["Customer"])
    get_json()
    credit = get_or_404(db.credits, cid, "credit", "Cruise credit not found")
    if credit["credit_status"] != "SETTLED":
        raise err_invalid_state("Credit is not SETTLED")
    credit["credit_status"] = "REDEEMED"
    customer = db.customers.get(credit["customer_id"])
    if customer is not None:
        svc.recompute_customer_balance(customer)
    return ok(_sz("credit", credit))
