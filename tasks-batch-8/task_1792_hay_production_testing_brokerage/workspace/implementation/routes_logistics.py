"""Delivery loads (parallel logistics/settlement dimensions) and load
allocations (manual + waterfall)."""

from flask import Blueprint, request

from auth import authorize
from db import store, new_id, stamp_new
from domain import (
    create_allocation, apply_release, deliver_load, settle_load,
    auto_allocate, contract_remaining,
)
from errors import (
    ApiError, ERR_LOAD_NOT_FOUND, ERR_CONTRACT_NOT_FOUND, ERR_LOT_NOT_FOUND,
    ERR_ALLOCATION_NOT_FOUND, ERR_LOAD_WRONG_STATE, ERR_INVALID_STATE,
    ERR_CONTRACT_NOT_ACTIVE, ERR_LOT_NOT_ACTIVE, ERR_LOT_CONDEMNED_UNSHIPPABLE,
    ERR_TONS_NOT_POSITIVE, ERR_ALLOCATION_EXCEEDS_REMAINING,
    ERR_LOAD_CAPACITY_EXCEEDED, ERR_STALE_VERSION,
)
from response import success
from serializers import delivery_load_out, load_allocation_out
from util import (
    D, req, as_str, as_int, as_number, as_date,
    get_body, paginate, sorted_by_created, invalid,
)
from util import round2

bp = Blueprint("logistics", __name__)


# --- DeliveryLoad -------------------------------------------------------------

@bp.post("/api/delivery-loads")
def create_delivery_load():
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    carrier_name = as_str(req(body, "carrier_name"), "carrier_name")
    capacity_tons = as_number(req(body, "capacity_tons"), "capacity_tons")
    if capacity_tons <= 0:
        invalid("capacity_tons must be greater than zero")
    planned_ship_date = as_date(req(body, "planned_ship_date"), "planned_ship_date")
    from decimal import Decimal
    load = stamp_new({
        "id": new_id(),
        "carrier_name": carrier_name,
        "capacity_tons": capacity_tons,
        "planned_ship_date": planned_ship_date,
        "loaded_tons": Decimal("0.0"),
        "logistics_status": "PLANNED",
        "settlement_status": "OPEN",
    })
    store["delivery_loads"][load["id"]] = load
    return success(delivery_load_out(load), "object", 201)


def _load(load_id):
    load = store["delivery_loads"].get(load_id)
    if load is None:
        raise ApiError(ERR_LOAD_NOT_FOUND, 404, "delivery load not found")
    return load


@bp.get("/api/delivery-loads/<load_id>")
def get_delivery_load(load_id):
    authorize(["PlatformAdmin", "BrokerOps"])
    return success(delivery_load_out(_load(load_id)), "object", 200)


@bp.post("/api/delivery-loads/<load_id>/start-loading")
def start_loading(load_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    load = _load(load_id)
    if load["logistics_status"] != "PLANNED":
        raise ApiError(ERR_LOAD_WRONG_STATE, 409, "load must be PLANNED to start loading")
    has_open = any(
        a["status"] == "OPEN" and a["delivery_load_id"] == load["id"]
        for a in store["load_allocations"].values()
    )
    if not has_open:
        raise ApiError(ERR_LOAD_WRONG_STATE, 409, "an empty load cannot start loading")
    load["logistics_status"] = "LOADING"
    from db import touch
    touch(load)
    return success(delivery_load_out(load), "object", 200)


@bp.post("/api/delivery-loads/<load_id>/depart")
def depart(load_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    load = _load(load_id)
    if load["logistics_status"] != "LOADING":
        raise ApiError(ERR_LOAD_WRONG_STATE, 409, "load must be LOADING to depart")
    load["logistics_status"] = "IN_TRANSIT"
    from db import touch
    touch(load)
    return success(delivery_load_out(load), "object", 200)


@bp.post("/api/delivery-loads/<load_id>/deliver")
def deliver(load_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    load = _load(load_id)
    if load["logistics_status"] != "IN_TRANSIT":
        raise ApiError(ERR_LOAD_WRONG_STATE, 409, "load must be IN_TRANSIT to deliver")
    deliver_load(load)
    return success(delivery_load_out(load), "object", 200)


@bp.post("/api/delivery-loads/<load_id>/settle")
def settle(load_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    load = _load(load_id)
    if load["settlement_status"] != "OPEN":
        raise ApiError(ERR_LOAD_WRONG_STATE, 409, "load settlement is not OPEN")
    if load["logistics_status"] != "DELIVERED":
        raise ApiError(ERR_LOAD_WRONG_STATE, 409, "load must be DELIVERED before it can settle")
    settle_load(load)
    return success(delivery_load_out(load), "object", 200)


@bp.post("/api/delivery-loads/<load_id>/auto-allocate")
def auto_allocate_load(load_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    load = _load(load_id)
    created = auto_allocate(load)
    return success([load_allocation_out(a) for a in created], "array", 200)


# --- LoadAllocation -------------------------------------------------------------

@bp.post("/api/load-allocations")
def create_load_allocation():
    authorize(["BrokerOps", "PlatformAdmin"])
    body = get_body()
    delivery_load_id = as_str(req(body, "delivery_load_id"), "delivery_load_id")
    contract_id = as_str(req(body, "contract_id"), "contract_id")
    bale_lot_id = as_str(req(body, "bale_lot_id"), "bale_lot_id")
    tons = as_number(req(body, "tons"), "tons")
    expected_version = as_int(req(body, "expected_delivery_load_version"), "expected_delivery_load_version")
    # Priority 4: body FKs resolve in declared field order.
    load = store["delivery_loads"].get(delivery_load_id)
    if load is None:
        raise ApiError(ERR_LOAD_NOT_FOUND, 404, "delivery load not found")
    contract = store["contracts"].get(contract_id)
    if contract is None:
        raise ApiError(ERR_CONTRACT_NOT_FOUND, 404, "contract not found")
    lot = store["bale_lots"].get(bale_lot_id)
    if lot is None:
        raise ApiError(ERR_LOT_NOT_FOUND, 404, "bale lot not found")
    # Priority 6: contract ACTIVE; lot ACTIVE (DEPLETED fails here); OCC on the load.
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_ACTIVE, 409, "contract must be ACTIVE for allocation")
    if lot["status"] not in ("ACTIVE", "CONDEMNED"):
        raise ApiError(ERR_LOT_NOT_ACTIVE, 409, "lot must be ACTIVE for allocation")
    if expected_version != load["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_delivery_load_version does not match the load's current version")
    # Priority 7: condemned hay can never ship.
    if lot["status"] == "CONDEMNED":
        raise ApiError(ERR_LOT_CONDEMNED_UNSHIPPABLE, 422, "a CONDEMNED lot can never be allocated")
    # Priority 10: tons positive; contract remaining; load capacity (equality allowed).
    if tons <= 0:
        raise ApiError(ERR_TONS_NOT_POSITIVE, 422, "tons must be greater than zero")
    if tons > contract_remaining(contract):
        raise ApiError(ERR_ALLOCATION_EXCEEDS_REMAINING, 422,
                       "allocation tons exceed the contract's remaining_tons")
    if D(load["loaded_tons"]) + tons > D(load["capacity_tons"]):
        raise ApiError(ERR_LOAD_CAPACITY_EXCEEDED, 422,
                       "allocation would push the load over capacity_tons")
    alloc = create_allocation(load, contract, lot, tons)
    return success(load_allocation_out(alloc), "object", 201)


@bp.get("/api/load-allocations")
def list_load_allocations():
    authorize(["PlatformAdmin", "BrokerOps"])
    items = list(store["load_allocations"].values())
    load_id = request.args.get("delivery_load_id")
    contract_id = request.args.get("contract_id")
    lot_id = request.args.get("bale_lot_id")
    status = request.args.get("status")
    if load_id is not None:
        items = [a for a in items if a["delivery_load_id"] == load_id]
    if contract_id is not None:
        items = [a for a in items if a["contract_id"] == contract_id]
    if lot_id is not None:
        items = [a for a in items if a["bale_lot_id"] == lot_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    items = sorted_by_created(items)
    page, meta = paginate(items)
    return success([load_allocation_out(a) for a in page], "array", 200, meta)


@bp.get("/api/load-allocations/<alloc_id>")
def get_load_allocation(alloc_id):
    authorize(["PlatformAdmin", "BrokerOps"])
    alloc = store["load_allocations"].get(alloc_id)
    if alloc is None:
        raise ApiError(ERR_ALLOCATION_NOT_FOUND, 404, "load allocation not found")
    return success(load_allocation_out(alloc), "object", 200)


@bp.post("/api/load-allocations/<alloc_id>/release")
def release_allocation(alloc_id):
    authorize(["BrokerOps", "PlatformAdmin"])
    alloc = store["load_allocations"].get(alloc_id)
    if alloc is None:
        raise ApiError(ERR_ALLOCATION_NOT_FOUND, 404, "load allocation not found")
    if alloc["status"] != "OPEN":
        raise ApiError(ERR_INVALID_STATE, 409, "only an OPEN allocation can be released")
    load = store["delivery_loads"].get(alloc["delivery_load_id"])
    if load is not None and load["logistics_status"] not in ("PLANNED", "LOADING"):
        raise ApiError(ERR_LOAD_WRONG_STATE, 409,
                       "the owning load must be PLANNED or LOADING to release an allocation")
    apply_release(alloc)
    return success(load_allocation_out(alloc), "object", 200)
