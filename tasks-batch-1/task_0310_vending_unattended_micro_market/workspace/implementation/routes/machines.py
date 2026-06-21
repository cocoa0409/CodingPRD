"""Machine endpoints (PRD 3.2): create, list, get, cash-collection, spoilage-purge."""
from flask import Blueprint, request

from common import (get_json_body, get_or_404, list_response, require_number,
                    require_str, require_enum, require_int)
from db import db, stamp_create, touch
from errors import ApiError
from middleware import require_roles
from response import object_response
from services import serialize
from services.inventory import (rederive_machine_cash, rederive_machine_stock)

bp = Blueprint("machines", __name__)

ALL_ROLES = ("FieldOps", "RouteDriver", "HostManager", "FinanceClerk")
MACHINE_TYPES = {"SNACK_VENDOR", "BEVERAGE_VENDOR", "MICRO_MARKET_KIOSK"}


@bp.route("/operations/machines", methods=["POST"])
@require_roles("FieldOps")
def create_machine():
    body = get_json_body()
    host_site_id = require_str(body, "host_site_id")
    asset_tag = require_str(body, "asset_tag")
    machine_type = require_enum(body, "machine_type", MACHINE_TYPES)
    cash_capacity = require_int(body, "cash_capacity_cents", allow_missing=True, default=50000)
    if cash_capacity <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "cash_capacity_cents must be > 0")
    cash_alert = require_number(body, "cash_alert_threshold_pct", allow_missing=True, default=0.80)
    par_fill = require_number(body, "par_fill_threshold_pct", allow_missing=True, default=0.25)

    # FK existence (priority 4)
    host = db.host_sites.get(host_site_id)
    if host is None:
        raise ApiError("ERR_HOST_SITE_NOT_FOUND", "Host site not found")

    # business constraint (priority 11): host must be ACTIVE
    if host["status"] == "SUSPENDED":
        raise ApiError("ERR_HOST_SUSPENDED", "Cannot place a machine at a suspended host")

    # asset_tag unique
    for m in db.machines.values():
        if m["asset_tag"] == asset_tag:
            raise ApiError("ERR_DUPLICATE_ASSET_TAG", "Machine asset_tag already exists")

    obj = {
        "host_site_id": host_site_id,
        "asset_tag": asset_tag,
        "machine_type": machine_type,
        "cash_capacity_cents": cash_capacity,
        "cash_on_hand_cents": 0,
        "cash_alert_threshold_pct": cash_alert,
        "par_fill_threshold_pct": par_fill,
        "stock_status": "STOCKOUT",  # no slots yet
        "cash_status": "CASH_OK",
        "service_status": "IN_SERVICE",
    }
    stamp_create(obj)
    db.machines[obj["id"]] = obj
    return object_response(serialize.machine(obj), 201)


@bp.route("/operations/machines", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_machines():
    rows = list(db.machines.values())
    host_site_id = request.args.get("host_site_id")
    if host_site_id is not None:
        rows = [m for m in rows if m["host_site_id"] == host_site_id]
    return list_response(rows, serialize.machine)


@bp.route("/operations/machines/<machine_id>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_machine(machine_id):
    obj = get_or_404("machines", machine_id)
    return object_response(serialize.machine(obj))


@bp.route("/operations/machines/<machine_id>/cash-collections", methods=["POST"])
@require_roles("FieldOps")
def cash_collection(machine_id):
    machine = get_or_404("machines", machine_id)
    machine["cash_on_hand_cents"] = 0
    # re-derive cash status (will become CASH_OK); then bump version once.
    # PRD 3.2: a cash collection increments version by one.
    machine["cash_status"] = "CASH_OK"
    touch(machine)
    return object_response(serialize.machine(machine))


@bp.route("/operations/machines/<machine_id>/spoilage-purge", methods=["POST"])
@require_roles("FieldOps")
def spoilage_purge(machine_id):
    machine = get_or_404("machines", machine_id)
    clock = db.clock()

    # cascade hop 1: every AVAILABLE lot whose expiration_date <= clock -> SPOILED
    touched_slot_ids = set()
    for lot in db.lots.values():
        if lot["machine_id"] != machine_id:
            continue
        if lot["status"] != "AVAILABLE":
            continue
        exp = lot.get("_expiration_dt")
        if exp is None:
            continue  # non-perishable, never expires
        if exp <= clock:
            lot["remaining_units"] = 0
            lot["status"] = "SPOILED"
            touch(lot)
            touched_slot_ids.add(lot["slot_id"])

    # cascade hop 2: recompute affected slot on_hand
    from services.inventory import recompute_slot_on_hand
    for slot_id in touched_slot_ids:
        slot = db.slots.get(slot_id)
        if slot:
            recompute_slot_on_hand(slot)

    # cascade hop 3: re-derive machine stock_status
    rederive_machine_stock(machine)

    return object_response(serialize.machine(machine))
