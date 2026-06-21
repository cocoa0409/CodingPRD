"""Customer and Dasher endpoints (PRD §3.3)."""
from flask import Blueprint, request

import common
import errors
import lookups
from db import store
from middleware import get_user_context, require_roles
from response import success, list_success
from serializers import serialize_customer, serialize_dasher, serialize_earnings_record

bp = Blueprint("parties", __name__)


# ---------------------------------------------------------------------------
# Customer
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
def create_customer():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer"])
    body = common.get_json_body()
    name = common.require_str(body, "name")

    c = common.init_common(versioned=True)
    c.update({
        "name": name,
        "wallet_credit_cents": 0,
    })
    store.customers[c["id"]] = c
    return success(serialize_customer(c), status=201)


@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Customer"])
    c = lookups.get_customer(cid)
    return success(serialize_customer(c))


# ---------------------------------------------------------------------------
# Dasher
# ---------------------------------------------------------------------------
@bp.route("/dashers", methods=["POST"])
def create_dasher():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher"])
    body = common.get_json_body()

    name = common.require_str(body, "name")
    home_zone_id = common.require_str(body, "home_zone_id")
    max_batch_size = common.optional_int(body, "max_batch_size", default=2, minimum=1)
    availability = common.optional_enum(body, "availability", ["ONLINE", "OFFLINE"], default="ONLINE")

    lookups.get_zone(home_zone_id)  # FK existence

    d = common.init_common(versioned=True)
    d.update({
        "name": name,
        "home_zone_id": home_zone_id,
        "max_batch_size": max_batch_size,
        "availability": availability,
    })
    store.dashers[d["id"]] = d
    return success(serialize_dasher(d), status=201)


@bp.route("/dashers", methods=["GET"])
def list_dashers():
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher"])
    limit, offset = common.parse_pagination()
    home_zone = request.args.get("home_zone_id")
    items = list(store.dashers.values())
    if home_zone is not None:
        items = [d for d in items if d["home_zone_id"] == home_zone]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_dasher(d) for d in page], limit, offset, total)


@bp.route("/dashers/<did>", methods=["GET"])
def get_dasher(did):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher"])
    d = lookups.get_dasher(did)
    return success(serialize_dasher(d))


@bp.route("/dashers/<did>", methods=["PATCH"])
def update_dasher(did):
    user_id, role = get_user_context()
    require_roles(role, ["Dasher"])
    d = lookups.get_dasher(did)
    if role == "Dasher" and d["id"] != user_id:
        raise errors.err(errors.ERR_NOT_RESOURCE_OWNER)
    body = common.get_json_body()

    changed = False
    if "availability" in body and body["availability"] is not None:
        d["availability"] = common.optional_enum(body, "availability", ["ONLINE", "OFFLINE"])
        changed = True
    if "max_batch_size" in body and body["max_batch_size"] is not None:
        d["max_batch_size"] = common.optional_int(body, "max_batch_size", minimum=1)
        changed = True
    if changed:
        common.touch(d)
    return success(serialize_dasher(d))


@bp.route("/dashers/<did>/earnings", methods=["GET"])
def list_dasher_earnings(did):
    _, role = get_user_context()
    require_roles(role, ["PlatformAdmin", "Dasher"])
    lookups.get_dasher(did)
    limit, offset = common.parse_pagination()
    items = [e for e in store.earnings_records.values() if e["dasher_id"] == did]
    items = common.sorted_by_creation(items)
    page, total = common.paginate(items, limit, offset)
    return list_success([serialize_earnings_record(e) for e in page], limit, offset, total)
