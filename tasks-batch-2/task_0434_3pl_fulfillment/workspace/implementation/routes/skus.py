"""SKU endpoints (PRD §3.1)."""
from flask import Blueprint, request

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import get_client, get_sku, get_json_body, parse_pagination, paginate
from serializers import serialize_sku

bp = Blueprint("skus", __name__)

READ_ROLES = {"ClientUser", "WavePlanner", "ReceivingClerk", "BillingClerk"}


def _filtered_skus():
    client_id = request.args.get("client_id")
    items = list(store.skus.values())
    if client_id is not None:
        items = [s for s in items if s["client_id"] == client_id]
    return items


@bp.route("/skus", methods=["GET"])
def list_skus():
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    limit, offset = parse_pagination()
    page, meta = paginate(_filtered_skus(), limit, offset)
    return success([serialize_sku(r) for r in page], pagination=meta)


@bp.route("/skus/<sku_id>", methods=["GET"])
def get_one_sku(sku_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    rec = get_sku(sku_id)
    return success(serialize_sku(rec))


@bp.route("/clients/<client_id>/skus", methods=["POST"])
def create_sku(client_id):
    _, role = get_auth()
    require_roles(role, {"ClientUser"})
    client = get_client(client_id)
    body = get_json_body()

    code = body.get("code")
    if not isinstance(code, str) or code == "":
        raise err("ERR_INVALID_REQUEST", "code is required")

    unit_volume = body.get("unit_volume_cc")
    if isinstance(unit_volume, bool) or not isinstance(unit_volume, int) or unit_volume < 0:
        raise err("ERR_INVALID_REQUEST", "unit_volume_cc must be a non-negative integer")

    unit_cost = body.get("unit_cost_cents", 0)
    if unit_cost is None:
        unit_cost = 0
    if isinstance(unit_cost, bool) or not isinstance(unit_cost, int) or unit_cost < 0:
        raise err("ERR_INVALID_REQUEST", "unit_cost_cents must be a non-negative integer")

    hazmat = body.get("hazmat", False)
    if hazmat is None:
        hazmat = False
    if not isinstance(hazmat, bool):
        raise err("ERR_INVALID_REQUEST", "hazmat must be a boolean")

    # Uniqueness per (client_id, code) (PRD §3.1).
    for s in store.skus.values():
        if s["client_id"] == client_id and s["code"] == code:
            raise err("ERR_INVALID_REQUEST", "SKU code already exists for this client")

    rec = stamp_create({
        "id": new_id(),
        "client_id": client_id,
        "code": code,
        "unit_volume_cc": unit_volume,
        "unit_cost_cents": unit_cost,
        "hazmat": hazmat,
        "status": "ACTIVE",
    })
    store.skus[rec["id"]] = rec
    return success(serialize_sku(rec), status=201)


@bp.route("/clients/<client_id>/skus", methods=["GET"])
def list_client_skus(client_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    get_client(client_id)
    limit, offset = parse_pagination()
    items = [s for s in store.skus.values() if s["client_id"] == client_id]
    page, meta = paginate(items, limit, offset)
    return success([serialize_sku(r) for r in page], pagination=meta)


@bp.route("/clients/<client_id>/skus/<sku_id>", methods=["GET"])
def get_client_sku(client_id, sku_id):
    _, role = get_auth()
    require_roles(role, READ_ROLES)
    get_client(client_id)
    rec = get_sku(sku_id)
    if rec["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "SKU not owned by path client")
    return success(serialize_sku(rec))


@bp.route("/clients/<client_id>/skus/<sku_id>/discontinue", methods=["POST"])
def discontinue_sku(client_id, sku_id):
    _, role = get_auth()
    require_roles(role, {"ClientUser"})
    get_client(client_id)
    rec = get_sku(sku_id)
    if rec["client_id"] != client_id:
        raise err("ERR_CLIENT_OWNERSHIP_MISMATCH", "SKU not owned by path client")
    rec["status"] = "DISCONTINUED"
    touch(rec)
    return success(serialize_sku(rec))
