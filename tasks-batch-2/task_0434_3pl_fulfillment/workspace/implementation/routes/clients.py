"""Client endpoints (PRD §3.1, §3.11)."""
from flask import Blueprint

from db import store, new_id, stamp_create, touch
from errors import err
from middleware import get_auth, require_roles
from response import success
from common import get_client, get_json_body, parse_pagination, paginate
from serializers import serialize_client

bp = Blueprint("clients", __name__)


def _require_int(body, field, required=True, default=None, min_value=None, max_value=None):
    if field not in body or body[field] is None:
        if required:
            raise err("ERR_INVALID_REQUEST", "Missing field: %s" % field)
        return default
    val = body[field]
    if isinstance(val, bool) or not isinstance(val, int):
        raise err("ERR_INVALID_REQUEST", "%s must be an integer" % field)
    if min_value is not None and val < min_value:
        raise err("ERR_INVALID_REQUEST", "%s below minimum" % field)
    if max_value is not None and val > max_value:
        raise err("ERR_INVALID_REQUEST", "%s above maximum" % field)
    return val


@bp.route("/clients", methods=["POST"])
def create_client():
    _, role = get_auth()
    require_roles(role, {"BillingClerk"})
    body = get_json_body()

    name = body.get("name")
    if not isinstance(name, str) or name == "":
        raise err("ERR_INVALID_REQUEST", "name is required")

    storage_rate = _require_int(body, "storage_rate_per_pallet_cents", required=True, min_value=0)
    handling_rate = _require_int(body, "handling_rate_per_order_cents", required=True, min_value=0)
    extra_unit = _require_int(body, "handling_rate_per_extra_unit_cents", required=False, default=0, min_value=0)
    extra_carton = _require_int(body, "handling_surcharge_per_extra_carton_cents", required=False, default=0, min_value=0)
    discount_bps = _require_int(body, "carrier_discount_bps", required=False, default=0, min_value=0, max_value=10000)

    rec = stamp_create({
        "id": new_id(),
        "name": name,
        "storage_rate_per_pallet_cents": storage_rate,
        "handling_rate_per_order_cents": handling_rate,
        "handling_rate_per_extra_unit_cents": extra_unit,
        "handling_surcharge_per_extra_carton_cents": extra_carton,
        "carrier_discount_bps": discount_bps,
        "storage_balance_cents": 0,
        "handling_balance_cents": 0,
        "status": "ACTIVE",
    })
    store.clients[rec["id"]] = rec
    return success(serialize_client(rec), status=201)


@bp.route("/clients", methods=["GET"])
def list_clients():
    _, role = get_auth()
    require_roles(role, {"BillingClerk", "ClientUser", "WavePlanner", "ReceivingClerk"})
    limit, offset = parse_pagination()
    page, meta = paginate(list(store.clients.values()), limit, offset)
    return success([serialize_client(r) for r in page], pagination=meta)


@bp.route("/clients/<client_id>", methods=["GET"])
def get_one_client(client_id):
    _, role = get_auth()
    require_roles(role, {"BillingClerk", "ClientUser", "WavePlanner", "ReceivingClerk"})
    rec = get_client(client_id)
    return success(serialize_client(rec))


@bp.route("/clients/<client_id>/suspend", methods=["POST"])
def suspend_client(client_id):
    _, role = get_auth()
    require_roles(role, {"BillingClerk"})
    rec = get_client(client_id)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return success(serialize_client(rec))
