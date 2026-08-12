"""BuyerAccount endpoints: create, read, set-standing (PRD 3.3)."""
from flask import Blueprint

from authz import require_role
from db import store
from errors import forbidden, invalid_state
from helpers import (body, get_or_404, new_record, req_enum, req_int, req_str,
                     touch)
from respond import success
from serialize import buyer_out
from services import BUYER_STANDINGS, buyer_exposure_cents

bp = Blueprint("buyers", __name__)


@bp.post("/api/buyer-accounts")
def create_buyer():
    require_role("Owner")
    data = body()
    rec = new_record({
        "name": req_str(data, "name"),
        "credit_limit_cents": req_int(data, "credit_limit_cents", minimum=0),
        "standing": "GOOD_STANDING",
    })
    store.buyers[rec["id"]] = rec
    return success(buyer_out(rec, 0), status=201)


@bp.get("/api/buyer-accounts/<bid>")
def get_buyer(bid):
    user_id, role = require_role("Owner", "WholesaleBuyer")
    buyer = get_or_404(store.buyers, bid)
    # Entity-backed ownership: a wholesale buyer reads only its own account.
    if role == "WholesaleBuyer" and buyer["id"] != user_id:
        raise forbidden("A wholesale buyer may read only its own account")
    return success(buyer_out(buyer, buyer_exposure_cents(bid)))


@bp.post("/api/buyer-accounts/<bid>/set-standing")
def set_standing(bid):
    require_role("Owner")
    buyer = get_or_404(store.buyers, bid)
    data = body()
    target = req_enum(data, "to_standing", BUYER_STANDINGS)
    cur = buyer["standing"]

    legal = {
        ("GOOD_STANDING", "CREDIT_HOLD"),
        ("CREDIT_HOLD", "GOOD_STANDING"),
        ("GOOD_STANDING", "CLOSED"),
        ("CREDIT_HOLD", "CLOSED"),
    }
    if (cur, target) not in legal:
        raise invalid_state("Standing cannot move from %s to %s" % (cur, target))
    if target == "CLOSED":
        if any(o["buyer_account_id"] == bid
               and o["status"] in ("DRAFT", "SUBMITTED", "ALLOCATED")
               for o in store.orders.values()):
            raise invalid_state("The buyer still has open orders")

    buyer["standing"] = target
    touch(buyer)
    return success(buyer_out(buyer, buyer_exposure_cents(bid)))
