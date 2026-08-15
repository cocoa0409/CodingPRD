"""Bid item read endpoints (creation lives in routes/contracts.py)."""
from flask import Blueprint, request

from routes.helpers import list_response, get_one

bp = Blueprint("bid_items", __name__)


@bp.get("/bid-items")
def list_bid_items():
    filters = {"contract_id": request.args.get("contract_id")}
    return list_response("bid_items", filters)


@bp.get("/bid-items/<bid_item_id>")
def get_bid_item(bid_item_id):
    return get_one("bid_items", bid_item_id)
