from flask import Blueprint

import db
from errors import raise_err, ERR_SELLER_NOT_FOUND
from middleware import require_role
from response import success
from routes._helpers import get_json_body, require_string
from services.lot_service import serialize_seller, recompute_seller_counters

bp = Blueprint("sellers", __name__)


@bp.post("/sellers")
def create_seller():
    require_role({"PlatformAdmin"})
    body = get_json_body()
    display_name = require_string(body, "display_name", min_len=1, max_len=80)
    sid = db.gen_id()
    now = db.now()
    s = {
        "id": sid,
        "display_name": display_name,
        "status": "ACTIVE",
        "total_lots_listed": 0,
        "gross_proceeds_cents": 0,
        "net_proceeds_cents": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.sellers[sid] = s
    return success(serialize_seller(s), http_status=201)


@bp.get("/sellers/<seller_id>")
def get_seller(seller_id):
    require_role({"PlatformAdmin", "Seller", "Bidder", "ArbitratorOps", "Anonymous"})
    s = db.sellers.get(seller_id)
    if s is None:
        raise_err(ERR_SELLER_NOT_FOUND)
    recompute_seller_counters(s)
    return success(serialize_seller(s))
