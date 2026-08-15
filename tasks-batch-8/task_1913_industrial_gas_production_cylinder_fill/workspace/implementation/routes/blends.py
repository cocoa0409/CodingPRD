"""BlendOrder endpoints (PRD §3.9)."""
from decimal import Decimal

from flask import Blueprint

from constants import MIN_TANK_RESERVE_LITERS, PRODUCTS
from db import store
from errors import (
    ERR_ACCOUNT_NOT_ACTIVE,
    ERR_BLEND_COMPONENT_SUM_INVALID,
    ERR_BLEND_ORDER_INVALID_STATE,
    ERR_PLANT_NOT_OPERATING,
    ERR_TANK_LEVEL_TOO_LOW,
    ApiError,
    bad_request,
    not_found,
)
from middleware import ANY_ROLE, get_body, locked, req_int, req_list, req_str, require_roles
from response import success
from routes.listing import list_response
from services import calc
from services.ops import base_record, blend_out
from util import dec, is_num, round2, touch

bp = Blueprint("blends", __name__)


def _get_blend(blendOrderId):
    b = store.blends.get(blendOrderId)
    if b is None:
        not_found("blend order not found")
    return b


def _required_qty(comp, batch_qty):
    return round2(dec(comp["target_pct"]) / Decimal("100") * dec(batch_qty))


@bp.post("/api/blend-orders")
@locked
def create_blend():
    require_roles("BillingClerk")
    body = get_body()
    customer_id = req_str(body, "customer_id")
    batch_qty = req_int(body, "batch_qty_liters")
    if batch_qty <= 0:
        bad_request("batch_qty_liters must be > 0")
    raw_components = req_list(body, "components")
    components = []
    for comp in raw_components:
        if not isinstance(comp, dict):
            bad_request("components entries must be objects")
        code = comp.get("product_code")
        if not isinstance(code, str) or code not in PRODUCTS:
            from errors import bad_enum

            bad_enum("invalid product_code in components")
        target = comp.get("target_pct")
        tol = comp.get("tolerance_pct")
        cost = comp.get("unit_cost_cents_per_liter")
        if not is_num(target) or not is_num(tol) or not is_num(cost):
            bad_request("components need numeric target_pct, tolerance_pct, unit_cost_cents_per_liter")
        components.append(
            {
                "product_code": code,
                "target_pct": target,
                "tolerance_pct": tol,
                "unit_cost_cents_per_liter": cost,
                "selected_tank_id": None,
            }
        )
    customer = store.customers.get(customer_id)
    if customer is None:
        not_found("customer not found")
    if customer["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, "customer account is not ACTIVE")
    # blend composition (validation priority 15)
    total_pct = sum((round2(c["target_pct"]) for c in components), Decimal("0"))
    if (
        len(components) < 2
        or total_pct != Decimal("100.00")
        or any(dec(c["tolerance_pct"]) <= 0 for c in components)
        or any(dec(c["unit_cost_cents_per_liter"]) < 0 for c in components)
    ):
        raise ApiError(ERR_BLEND_COMPONENT_SUM_INVALID, 422, "invalid blend composition")
    cost, fee, total = calc.blend_price_quote(components, batch_qty)
    b = base_record()
    b.update(
        {
            "customer_id": customer_id,
            "batch_qty_liters": batch_qty,
            "components": components,
            "component_cost_cents": cost,
            "service_fee_cents": fee,
            "total_price_cents": total,
            "blended_by_user_id": None,
            "status": "DRAFT",
        }
    )
    store.blends[b["id"]] = b
    return success(blend_out(b), status=201)


@bp.get("/api/blend-orders")
@locked
def list_blends():
    require_roles(*ANY_ROLE)
    return list_response(
        store.blends.values(), blend_out, [("customer_id", "customer_id"), ("status", "status")]
    )


@bp.get("/api/blend-orders/<blendOrderId>")
@locked
def get_blend(blendOrderId):
    require_roles(*ANY_ROLE)
    return success(blend_out(_get_blend(blendOrderId)))


@bp.post("/api/blend-orders/<blendOrderId>/approve")
@locked
def approve_blend(blendOrderId):
    require_roles("QualityManager")
    get_body()
    b = _get_blend(blendOrderId)
    if b["status"] != "DRAFT":
        raise ApiError(ERR_BLEND_ORDER_INVALID_STATE, 409, "blend must be DRAFT to approve")
    b["status"] = "APPROVED"
    touch(b)
    return success(blend_out(b))


@bp.post("/api/blend-orders/<blendOrderId>/start-blend")
@locked
def start_blend(blendOrderId):
    require_roles("ProductionOperator")
    get_body()
    b = _get_blend(blendOrderId)
    if b["status"] not in ("APPROVED", "REWORK"):
        raise ApiError(ERR_BLEND_ORDER_INVALID_STATE, 409, "blend must be APPROVED or REWORK to start")
    # Tank selector per component; ALL components must resolve before any change.
    selected = []
    for comp in b["components"]:
        required = _required_qty(comp, b["batch_qty_liters"])
        pool = []
        for t in store.tanks.values():
            if t["product_code"] != comp["product_code"] or t["status"] != "IN_SERVICE":
                continue
            headroom = calc.tank_current_level(t) - t["reserved_liters"]
            if headroom >= required + MIN_TANK_RESERVE_LITERS:
                pool.append(t)
        if not pool:
            raise ApiError(ERR_TANK_LEVEL_TOO_LOW, 409, "no eligible tank for a blend component")
        pool.sort(key=lambda t: (-calc.tank_current_level(t), t["_seq"]))
        selected.append(pool[0])
    # plant gate: plants resolved via the selected tanks
    for t in selected:
        plant = store.plants.get(t["plant_id"])
        if plant is None or plant["status"] != "OPERATING":
            raise ApiError(ERR_PLANT_NOT_OPERATING, 409, "plant is not OPERATING")
    for comp, tank in zip(b["components"], selected):
        comp["selected_tank_id"] = tank["id"]
    b["status"] = "BLENDING"
    touch(b)
    return success(blend_out(b))


@bp.post("/api/blend-orders/<blendOrderId>/complete-blend")
@locked
def complete_blend(blendOrderId):
    uid, _ = require_roles("ProductionOperator")
    get_body()
    b = _get_blend(blendOrderId)
    if b["status"] != "BLENDING":
        raise ApiError(ERR_BLEND_ORDER_INVALID_STATE, 409, "blend must be BLENDING to complete")
    tanks = []
    for comp in b["components"]:
        tank = store.tanks.get(comp.get("selected_tank_id"))
        if tank is None:
            raise ApiError(ERR_TANK_LEVEL_TOO_LOW, 409, "selected tank no longer exists")
        tanks.append(tank)
    for t in tanks:
        plant = store.plants.get(t["plant_id"])
        if plant is None or plant["status"] != "OPERATING":
            raise ApiError(ERR_PLANT_NOT_OPERATING, 409, "plant is not OPERATING")
    touched_tanks = set()
    for comp, tank in zip(b["components"], tanks):
        tank["drawn_liters"] += _required_qty(comp, b["batch_qty_liters"])
        if tank["id"] not in touched_tanks:
            touch(tank)
            touched_tanks.add(tank["id"])
    b["blended_by_user_id"] = uid
    b["status"] = "AWAITING_ANALYSIS"
    touch(b)
    return success(blend_out(b))
