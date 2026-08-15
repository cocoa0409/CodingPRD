from flask import Blueprint, request

from auth import parse_auth
from db import store
from envelope import ok, paginate
from errors import not_found
from util import serialize, sort_key

bp = Blueprint("margin_calls", __name__)


@bp.get("/market/margin-calls/<marginCallId>")
def get_one(marginCallId):
    parse_auth()
    mc = store.margin_calls.get(marginCallId)
    if mc is None:
        raise not_found("margin call not found")
    return ok(serialize(mc))


@bp.get("/market/margin-calls")
def list_margin_calls():
    parse_auth()
    rows = sorted(store.margin_calls.values(), key=sort_key)
    pid = request.args.get("market_participant_id")
    status = request.args.get("status")
    if pid is not None:
        rows = [r for r in rows if r["market_participant_id"] == pid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([serialize(r) for r in rows])
