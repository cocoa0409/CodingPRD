"""Lane-bid reads and withdrawal — PRD §3.5."""
from flask import Blueprint

import auth
import helpers
import responses
import store
import validators as v
from errors import ApiError
from numeric import D
from services import bidding

bp = Blueprint("lanebids", __name__)


@bp.get("/freight-procurement/lane-bids/<bid_id>")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "CarrierRep")
def get_bid(bid_id):
    return responses.ok(helpers.get_bid(bid_id))


@bp.get("/freight-procurement/lane-bids")
@auth.roles_required("ProcurementAnalyst", "CategoryManager", "CarrierRep")
def list_bids():
    rows = list(store.lane_bids.values())
    rows.sort(key=lambda b: (int(b["rank_in_lane"]), b["created_at"], b["_seq"]))
    rows = helpers.filter_rows(rows, {"bid_round_id": "bid_round_id",
                                      "lane_id": "lane_id",
                                      "carrier_id": "carrier_id",
                                      "status": "status"})
    return responses.listing(rows)


@bp.post("/freight-procurement/lane-bids/<bid_id>/withdraw")
@auth.roles_required("CarrierRep")
def withdraw(bid_id):
    bid = helpers.get_bid(bid_id)
    v.body()
    auth.own_carrier_or_raise(bid["carrier_id"])

    round_row = store.rounds.get(bid["bid_round_id"])
    if bid["status"] != "SUBMITTED" or round_row is None or round_row["status"] != "OPEN":
        raise ApiError("ERR_ROUND_NOT_OPEN")

    bid["status"] = "WITHDRAWN"
    bid["withdrawn_at"] = store.now_iso()
    store.touch(bid)

    bidding.rerank_lane(round_row["id"], bid["lane_id"])
    bidding.recompute_round_counters(round_row)
    store.touch(round_row)
    return responses.ok(bid)
