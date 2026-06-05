"""Merchant endpoints (PRD §3.1, §3.8)."""
from flask import Blueprint

import db
from errors import err
from middleware import authenticate, require_role, require_merchant_owns
from response import success
from services import engine
from services.engine import stamp_new, touch
from routes.common import get_json_body, require_str, require_int, require_merchant

bp = Blueprint("merchants", __name__)


@bp.route("/merchants", methods=["POST"])
def create_merchant():
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    body = get_json_body()

    display_name = require_str(body, "display_name")
    mdr_bps = require_int(body, "mdr_bps", minimum=0, maximum=1000)
    settlement_hold_days = require_int(
        body, "settlement_hold_days", required=False, default=2,
        minimum=0, maximum=30)

    m = {
        "display_name": display_name,
        "mdr_bps": mdr_bps,
        "settlement_hold_days": settlement_hold_days,
        "status": "ACTIVE",
    }
    stamp_new(m)
    db.merchants[m["id"]] = m
    return success(engine.serialize_merchant(m), status=201)


@bp.route("/merchants/<merchant_id>", methods=["GET"])
def get_merchant(merchant_id):
    uid, role = authenticate()
    require_role(role, {"Servicer", "Merchant"})
    m = require_merchant(merchant_id)
    require_merchant_owns(role, uid, m["id"])
    return success(engine.serialize_merchant(m), status=200)


@bp.route("/merchants/<merchant_id>/suspend", methods=["POST"])
def suspend_merchant(merchant_id):
    _uid, role = authenticate()
    require_role(role, {"Servicer"})
    m = require_merchant(merchant_id)
    m["status"] = "SUSPENDED"
    touch(m)
    return success(engine.serialize_merchant(m), status=200)
