"""Order intake, freight-sensitive plant assignment, packaging, delivery, cancellation."""

from decimal import Decimal

import calc
import response
import services as svc
from auth import ALL_ROLES, actor, endpoint
from errors import ApiError
from routes import apply_filters
from store import add_days, clock, clock_str, db, fmt_clock, new_row, touch
from validation import (
    COLOR_FAMILIES,
    DURABILITY_GRADES,
    TEXTURES,
    BANDING_TYPES,
    UNLOADING_EQUIPMENT,
    body,
    v_bool,
    v_enum,
    v_int,
    v_str,
)

from flask import Blueprint

bp = Blueprint("orders", __name__)

D = Decimal


@bp.get("/orders/<oid>")
@endpoint(ALL_ROLES)
def get_order(oid):
    return response.entity(svc.order_or_404(oid))


@bp.get("/orders")
@endpoint(ALL_ROLES)
def list_orders():
    rows = apply_filters(
        db.orders.values(),
        {
            "plant_id": "plant_id",
            "fulfillment_status": "fulfillment_status",
            "freight_status": "freight_status",
        },
    )
    return response.collection(rows)


# --------------------------------------------------------------------------
# POST /orders
# --------------------------------------------------------------------------
@bp.post("/orders")
@endpoint(["SalesRep"])
def create_order():
    payload = body()
    order_code = v_str(payload, "order_code")
    grid_x = v_int(payload, "jobsite_grid_x", minv=-5000, maxv=5000)
    grid_y = v_int(payload, "jobsite_grid_y", minv=-5000, maxv=5000)
    requested_units = v_int(payload, "requested_units", minv=1)
    color_family = v_enum(payload, "color_family", COLOR_FAMILIES)
    texture = v_enum(payload, "texture", TEXTURES)
    durability = v_enum(payload, "durability_grade", DURABILITY_GRADES)
    equipment = v_enum(payload, "unloading_equipment_required", UNLOADING_EQUIPMENT)
    banding = v_enum(payload, "banding_type", BANDING_TYPES)
    is_special = v_bool(payload, "is_special_order", default=False)
    needs_panel = v_bool(payload, "requires_panel_approval", default=False)

    svc.require_unique(db.orders, "order_code", order_code)

    row = new_row(
        plant_id=None,
        order_code=order_code,
        jobsite_grid_x=grid_x,
        jobsite_grid_y=grid_y,
        requested_units=requested_units,
        color_family=color_family,
        texture=texture,
        durability_grade=durability,
        is_special_order=is_special,
        requires_panel_approval=needs_panel,
        unloading_equipment_required=equipment,
        banding_type=banding,
        pallet_count=None,
        band_count=None,
        unloading_equipment_provided=None,
        distance_miles=None,
        estimated_billable_tons=None,
        estimated_base_freight_cents=None,
        estimated_fuel_surcharge_cents=None,
        estimated_freight_cents=None,
        final_billable_tons=None,
        final_base_freight_cents=None,
        final_fuel_surcharge_cents=None,
        final_freight_cents=None,
        freight_variance_cents=None,
        lead_time_days=None,
        promised_ship_date=None,
        assigned_by_user_id=None,
        packaged_by_user_id=None,
        assigned_at=None,
        delivered_at=None,
        invoiced_at=None,
        cancellation_reason=None,
        fulfillment_status="DRAFT",
        freight_status="UNQUOTED",
    )
    db.orders[row["id"]] = row
    return response.entity_created(row)


# --------------------------------------------------------------------------
# POST /orders/{id}/assign-plant
# --------------------------------------------------------------------------
@bp.post("/orders/<oid>/assign-plant")
@endpoint(["SalesRep"])
def assign_plant(oid):
    order = svc.order_or_404(oid)
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_ORDER_STATE_INVALID", "The order's fulfillment_status is not DRAFT.")

    quote = svc.select_plant(order)
    plant = quote["plant"]

    order["plant_id"] = plant["id"]
    order["distance_miles"] = quote["distance_miles"]
    order["estimated_billable_tons"] = quote["estimated_billable_tons"]
    order["estimated_base_freight_cents"] = quote["estimated_base_freight_cents"]
    order["estimated_fuel_surcharge_cents"] = quote["estimated_fuel_surcharge_cents"]
    order["estimated_freight_cents"] = quote["estimated_freight_cents"]

    days = calc.lead_time_days(
        order["requested_units"],
        plant["base_capacity_green_units_per_day"],
        order["is_special_order"],
        order["requires_panel_approval"],
    )
    order["lead_time_days"] = days
    order["promised_ship_date"] = fmt_clock(add_days(clock(), days))
    order["assigned_at"] = clock_str()
    order["assigned_by_user_id"] = actor()
    order["fulfillment_status"] = "ASSIGNED"
    order["freight_status"] = "ESTIMATED"
    touch(order)
    return response.entity(order)


# --------------------------------------------------------------------------
# POST /orders/{id}/package
# --------------------------------------------------------------------------
@bp.post("/orders/<oid>/package")
@endpoint(["LogisticsCoordinator"])
def package_order(oid):
    order = svc.order_or_404(oid)
    payload = body()
    pallet_count = v_int(payload, "pallet_count", minv=1)
    band_count = v_int(payload, "band_count", minv=1)

    if order["fulfillment_status"] != "IN_BLENDING":
        raise ApiError(
            "ERR_ORDER_STATE_INVALID", "The order's fulfillment_status is not IN_BLENDING."
        )
    blend = svc.live_blend_of_order(oid)
    if blend is None or blend["status"] != "CERTIFIED":
        raise ApiError("ERR_BLEND_NOT_CERTIFIED", "The order's shipped blend is not CERTIFIED.")

    allocated = int(blend["allocated_units"])
    if pallet_count * calc.PALLET_UNITS < allocated:
        raise ApiError(
            "ERR_PALLET_COUNT_INSUFFICIENT",
            "pallet_count does not cover the certified blend's allocated units.",
        )
    if band_count < pallet_count:
        raise ApiError("ERR_BAND_COUNT_INSUFFICIENT", "band_count must be at least pallet_count.")

    plant = db.plants.get(order["plant_id"])
    tons = calc.final_billable_tons(
        pallet_count, band_count, order["banding_type"], allocated
    )
    base, surcharge, total = calc.freight(
        order["distance_miles"], plant["freight_rate_cents_per_ton_mile"], tons
    )

    order["pallet_count"] = pallet_count
    order["band_count"] = band_count
    order["final_billable_tons"] = tons
    order["final_base_freight_cents"] = base
    order["final_fuel_surcharge_cents"] = surcharge
    order["final_freight_cents"] = total
    order["freight_variance_cents"] = total - int(order["estimated_freight_cents"])
    order["packaged_by_user_id"] = actor()
    order["fulfillment_status"] = "PACKAGED"
    order["freight_status"] = "FINALIZED"
    touch(order)
    return response.entity(order)


# --------------------------------------------------------------------------
# POST /orders/{id}/deliver
# --------------------------------------------------------------------------
@bp.post("/orders/<oid>/deliver")
@endpoint(["LogisticsCoordinator"])
def deliver_order(oid):
    order = svc.order_or_404(oid)
    payload = body()
    provided = v_enum(payload, "unloading_equipment_provided", UNLOADING_EQUIPMENT)

    if order["fulfillment_status"] != "PACKAGED":
        raise ApiError(
            "ERR_ORDER_STATE_INVALID", "The order's fulfillment_status is not PACKAGED."
        )
    plant = db.plants.get(order["plant_id"])
    available = (plant.get("unloading_equipment_available") or []) if plant else []
    if provided not in available:
        raise ApiError(
            "ERR_UNLOADING_EQUIPMENT_UNAVAILABLE",
            "The assigned plant does not operate that unloading equipment.",
        )
    if provided != order["unloading_equipment_required"]:
        raise ApiError(
            "ERR_UNLOADING_EQUIPMENT_MISMATCH",
            "The unloading equipment provided does not match the order's requirement.",
        )

    order["unloading_equipment_provided"] = provided
    svc.deliver_cascade(order, svc.live_blend_of_order(oid))
    return response.entity(order)


# --------------------------------------------------------------------------
# POST /orders/{id}/cancel
# --------------------------------------------------------------------------
@bp.post("/orders/<oid>/cancel")
@endpoint(["SalesRep"])
def cancel_order(oid):
    order = svc.order_or_404(oid)
    payload = body()
    reason = v_str(payload, "cancellation_reason")

    if order["fulfillment_status"] not in ("DRAFT", "ASSIGNED", "IN_BLENDING", "PACKAGED"):
        raise ApiError(
            "ERR_ORDER_STATE_INVALID", "The order can no longer be cancelled."
        )

    svc.cancel_cascade(order, reason)
    return response.entity(order)
