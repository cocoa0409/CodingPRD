"""Merchant endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import base_common_fields, touch
from errors import err
from middleware import get_identity, require_roles
from response import object_response
from routes.common import list_response
from services.serialize import merchant_out
from state import store
from validation import (
    get_json_body,
    require_string,
    require_int,
    optional_int,
    optional_bool,
)

bp = Blueprint("merchants", __name__)

ALL_ROLES = ["PlatformAdmin", "ReviewAgent", "FinanceAdmin", "Member"]


@bp.route("/merchants", methods=["POST"])
def create_merchant():
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin"])
    body = get_json_body()

    name = require_string(body, "name")
    online_rate_bps = require_int(body, "online_rate_bps", minimum=0)
    instore_rate_bps = require_int(body, "instore_rate_bps", minimum=0)
    if online_rate_bps > 10000:
        raise err("ERR_VALIDATION", "online_rate_bps must be 0..10000.")
    if instore_rate_bps > 10000:
        raise err("ERR_VALIDATION", "instore_rate_bps must be 0..10000.")

    attribution_window_hours = optional_int(body, "attribution_window_hours", 168, minimum=1)
    double_dip_allowed = optional_bool(body, "double_dip_allowed", False)
    maturity_hold_days = optional_int(body, "maturity_hold_days", 30, minimum=0)

    m = base_common_fields(store, full=True)
    m.update({
        "name": name,
        "online_rate_bps": online_rate_bps,
        "instore_rate_bps": instore_rate_bps,
        "attribution_window_hours": attribution_window_hours,
        "double_dip_allowed": double_dip_allowed,
        "maturity_hold_days": maturity_hold_days,
        "status": "ACTIVE",
    })
    store.merchants[m["id"]] = m
    return object_response(store.clock, merchant_out(store, m), status=201)


@bp.route("/merchants/<mid>", methods=["GET"])
def get_merchant(mid):
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    m = store.merchants.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Merchant not found.")
    return object_response(store.clock, merchant_out(store, m))


@bp.route("/merchants", methods=["GET"])
def list_merchants():
    _, role = get_identity()
    require_roles(role, ALL_ROLES)
    status = request.args.get("status")
    items = list(store.merchants.values())
    if status is not None:
        items = [m for m in items if m["status"] == status]
    return list_response(items, merchant_out)


@bp.route("/merchants/<mid>/disable", methods=["POST"])
def disable_merchant(mid):
    _, role = get_identity()
    require_roles(role, ["PlatformAdmin"])
    m = store.merchants.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND", "Merchant not found.")
    if m["status"] != "DISABLED":
        m["status"] = "DISABLED"
        touch(store, m)
    return object_response(store.clock, merchant_out(store, m))
