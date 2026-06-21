"""Test-driving clock endpoint (PRD §2.7)."""
from flask import Blueprint

from db import store, touch
from clock import parse_iso8601, to_iso8601_millis
from errors import err
from middleware import endpoint
from response import success
from serialize import view
from validation import get_body, require_str
from services.lookups import get_shop

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("ShopManager")
def set_current_utc():
    body = get_body()
    shop_id = require_str(body, "shop_id")
    shop = get_shop(shop_id)
    to_iso = require_str(body, "to_iso8601")
    dt = parse_iso8601(to_iso)
    if dt is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO 8601 datetime")
    shop["current_utc"] = to_iso8601_millis(dt)
    touch(shop)
    return success(view(shop), status=200)
