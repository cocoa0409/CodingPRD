"""Equipment assets: registration, decommission, inspection scheduling with
OCC and closed-interval conflict (PRD §3.1, §3.7, §2.9, §2.10)."""

from flask import Blueprint, request

from db import store, new_entity, touch
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_INVALID_WINDOW,
    ERR_INSPECTION_WINDOW_CONFLICT, ERR_ASSET_NOT_ACTIVE,
)
from middleware import (
    require_roles, body, get_or_404, check_customer_scope,
    get_str, get_dt, get_int, present,
)
from response import success, list_response
from services import serialize_asset, compliance_posture, touch_customer

bp = Blueprint("assets", __name__)

ASSET_READ_ROLES = ("ShopManager", "CounterSales", "ShopTechnician",
                    "FieldTechnician", "Customer")


@bp.post("/api/equipment-assets")
def create_asset():
    require_roles("ShopManager", "CounterSales")
    data = body()
    # existence (priority 3): body FK customer_id
    customer = get_or_404(store.customers, get_str(data, "customer_id"), "customer")
    asset = new_entity()
    asset.update({
        "customer_id": customer["id"],
        "asset_tag": get_str(data, "asset_tag"),
        "machine_type": get_str(data, "machine_type"),
        "installed_at": get_dt(data, "installed_at", required=False, default=None),
        "status": "ACTIVE",
        "installed_assembly_order_id": None,
        "last_passed_inspection_at": None,
        "frozen_posture": None,
    })
    store.assets[asset["id"]] = asset
    # registration recomputes the owning customer's scores (cascade touch)
    touch_customer(customer["id"])
    return success(serialize_asset(asset), status=201)


@bp.get("/api/equipment-assets")
def list_assets():
    uid, role = require_roles(*ASSET_READ_ROLES)
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    installed_order = request.args.get("installed_assembly_order_id")
    items = list(store.assets.values())
    if role == "Customer":
        # portal customers read only their own assets (PRD §2.1)
        items = [a for a in items if a["customer_id"] == uid]
        if customer_id is not None and customer_id != uid:
            items = []
    elif customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if installed_order is not None:
        items = [a for a in items
                 if a["installed_assembly_order_id"] == installed_order]
    return list_response([serialize_asset(a) for a in items])


@bp.get("/api/equipment-assets/<aid>")
def get_asset(aid):
    uid, role = require_roles(*ASSET_READ_ROLES)
    asset = get_or_404(store.assets, aid, "asset")
    check_customer_scope(role, uid, asset["customer_id"])
    return success(serialize_asset(asset), status=200)


@bp.post("/api/equipment-assets/<aid>/decommission")
def decommission_asset(aid):
    require_roles("ShopManager")
    asset = get_or_404(store.assets, aid, "asset")
    if asset["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Asset is already DECOMMISSIONED")
    # freeze the last computed posture; decommissioned assets keep it forever
    asset["frozen_posture"] = compliance_posture(asset)
    asset["status"] = "DECOMMISSIONED"
    touch(asset)
    # excluded from score denominators; recompute is a cascade touch
    touch_customer(asset["customer_id"])
    return success(serialize_asset(asset), status=200)


@bp.post("/api/equipment-assets/<aid>/inspections")
def create_inspection(aid):
    require_roles("ShopManager", "CounterSales")
    asset = get_or_404(store.assets, aid, "asset")
    data = body()
    # OCC (priority 6, PRD §2.10): the request must carry the token
    expected = data.get("expected_equipment_asset_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        from errors import ERR_INVALID_REQUEST
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Missing required field: expected_equipment_asset_version")
    if expected != asset["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_equipment_asset_version does not match the "
                       "asset's current version")
    # window shape (priority 11)
    start = get_dt(data, "scheduled_window_start")
    end = get_dt(data, "scheduled_window_end")
    if not end > start:
        raise ApiError(ERR_INVALID_WINDOW, 400,
                       "scheduled_window_end must be strictly after "
                       "scheduled_window_start")
    # closed-interval conflict vs IN_PROGRESS inspections on the same asset
    # (priority 13): touching endpoints count as overlap
    for insp in store.inspections.values():
        if (insp["equipment_asset_id"] == aid and insp["status"] == "IN_PROGRESS"
                and not (end < insp["scheduled_window_start"]
                         or start > insp["scheduled_window_end"])):
            raise ApiError(ERR_INSPECTION_WINDOW_CONFLICT, 409,
                           "Window overlaps an in-progress inspection on this asset")
    # asset-active (priority 16)
    if asset["status"] != "ACTIVE":
        raise ApiError(ERR_ASSET_NOT_ACTIVE, 422,
                       "Equipment asset is DECOMMISSIONED")
    inspector = get_str(data, "inspector_name", required=False, default=None)
    # supersede every prior SCHEDULED inspection of the asset, atomically
    for insp in store.inspections.values():
        if insp["equipment_asset_id"] == aid and insp["status"] == "SCHEDULED":
            insp["status"] = "SUPERSEDED"
            touch(insp)
    inspection = new_entity()
    inspection.update({
        "equipment_asset_id": aid,
        "inspector_name": inspector,
        "scheduled_window_start": start,
        "scheduled_window_end": end,
        "status": "SCHEDULED",
        "result": None,
        "performed_at": None,
        "was_overdue": False,
    })
    store.inspections[inspection["id"]] = inspection
    # creating an inspection increments the asset version by one (PRD §2.10)
    touch(asset)
    from db import pub
    return success(pub(inspection), status=201)


@bp.get("/api/equipment-assets/<aid>/inspections")
def list_asset_inspections(aid):
    uid, role = require_roles(*ASSET_READ_ROLES)
    asset = get_or_404(store.assets, aid, "asset")
    check_customer_scope(role, uid, asset["customer_id"])
    items = [i for i in store.inspections.values()
             if i["equipment_asset_id"] == aid]
    from db import pub
    return list_response([pub(i) for i in items])
