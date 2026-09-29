"""Component supplies, allocation lines and the distributor-order lifecycle."""

from flask import Blueprint

import calc
import cascade
import db
import derive
import find
import validate
import web
from errors import ApiError
from routes_design import eq_filter, listing
from web import endpoint

bp = Blueprint("supply", __name__)

SUPPLY_READ_ROLES = (
    "PlantAdmin",
    "SupplyPlanner",
    "ProductionPlanner",
    "ReliabilityEngineer",
    "DistributorRep",
)
LINE_READ_ROLES = ("PlantAdmin", "SupplyPlanner", "ProductionPlanner", "DistributorRep")
ORDER_READ_ROLES = ("PlantAdmin", "SupplyPlanner", "ProductionPlanner", "DistributorRep")
CAPA_READ_ROLES = ("PlantAdmin", "ReliabilityEngineer", "SupplyPlanner", "WarrantyAnalyst")


# -------------------------------------------------------- component supplies
@bp.route("/plant/component-supplies", methods=["POST"])
@endpoint(["SupplyPlanner"], 201)
def create_supply():
    payload = web.body()
    component_type = validate.enum_field(
        payload, "component_type", ("COMPRESSOR", "CONTROL_BOARD")
    )
    part_number = validate.str_field(payload, "part_number")
    supplier_lot_code = validate.str_field(payload, "supplier_lot_code")
    supply_month = validate.month_field(payload, "supply_month")
    total_units = validate.int_field(payload, "total_allocatable_units", minimum=1)
    policy = validate.enum_field(
        payload,
        "allocation_policy",
        ("PRIORITY_WATERFALL", "DEMAND_PRORATA"),
        required=False,
        default="PRIORITY_WATERFALL",
    )
    row = db.db.insert(
        "supplies",
        {
            "component_type": component_type,
            "part_number": part_number,
            "supplier_lot_code": supplier_lot_code,
            "supply_month": supply_month,
            "total_allocatable_units": total_units,
            "allocation_policy": policy,
            "derate_pct": 0,
            "status": "ACTIVE",
        },
    )
    return derive.serialize_supply(row)


@bp.route("/plant/component-supplies", methods=["GET"])
@endpoint(SUPPLY_READ_ROLES, 200)
def list_supplies():
    rows = db.db.rows("supplies")
    rows = eq_filter(rows, "component_type", web.filter_value("component_type"))
    rows = eq_filter(rows, "part_number", web.filter_value("part_number"))
    rows = eq_filter(rows, "supply_month", web.filter_value("supply_month"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    return listing(rows, derive.serialize_supply)


@bp.route("/plant/component-supplies/<row_id>", methods=["GET"])
@endpoint(SUPPLY_READ_ROLES, 200)
def read_supply(row_id):
    return derive.serialize_supply(find.supply(row_id))


@bp.route("/plant/component-supplies/<row_id>/allocation-lines", methods=["GET"])
@endpoint(("PlantAdmin", "SupplyPlanner", "ProductionPlanner"), 200)
def list_supply_lines(row_id):
    supply = find.supply(row_id)
    rows = [l for l in db.db.rows("lines") if l["component_supply_id"] == supply["id"]]
    rows = eq_filter(rows, "status", web.filter_value("status"))
    return listing(rows, derive.serialize_line)


@bp.route("/plant/component-supplies/<row_id>/corrective-actions", methods=["GET"])
@endpoint(CAPA_READ_ROLES, 200)
def list_supply_capas(row_id):
    supply = find.supply(row_id)
    rows = [c for c in db.db.rows("capas") if c["component_supply_id"] == supply["id"]]
    rows = eq_filter(rows, "status", web.filter_value("status"))
    return listing(rows, derive.serialize_capa)


# ----------------------------------------------------------- allocation lines
@bp.route("/plant/allocation-lines", methods=["GET"])
@endpoint(LINE_READ_ROLES, 200)
def list_lines():
    rows = db.db.rows("lines")
    rows = eq_filter(rows, "distributor_order_id", web.filter_value("distributor_order_id"))
    rows = eq_filter(rows, "component_supply_id", web.filter_value("component_supply_id"))
    rows = eq_filter(rows, "component_type", web.filter_value("component_type"))
    rows = eq_filter(rows, "status", web.filter_value("status"))
    return listing(rows, derive.serialize_line)


# --------------------------------------------------------- distributor orders
@bp.route("/plant/distributor-orders", methods=["POST"])
@endpoint(["DistributorRep"], 201)
def create_order():
    payload = web.body()
    distributor_code = validate.str_field(payload, "distributor_code")
    platform_id = validate.str_field(payload, "platform_id")
    region_code = validate.str_field(payload, "region_code", max_len=32)
    requested_units = validate.int_field(payload, "requested_units", minimum=1)
    priority_score = validate.int_field(payload, "priority_score", minimum=1, maximum=100)
    delivery_month = validate.month_field(payload, "requested_delivery_month")

    platform = find.platform(platform_id)
    if platform["status"] not in ("RELEASED", "RESTRICTED"):
        raise ApiError(
            "ERR_INVALID_PLATFORM_STATE",
            "Only a RELEASED or RESTRICTED platform may take new orders.",
        )
    row = db.db.insert(
        "orders",
        {
            "distributor_code": distributor_code,
            "platform_id": platform_id,
            "region_code": region_code,
            "requested_units": requested_units,
            "priority_score": priority_score,
            "requested_delivery_month": delivery_month,
            "created_by_user_id": web.actor(),
            "allocation_status": "UNALLOCATED",
            "fulfillment_status": "PENDING",
            "shipped_units": 0,
            "staged_at": None,
            "shipped_at": None,
            "cancelled_at": None,
        },
    )
    return derive.serialize_order(row)


@bp.route("/plant/distributor-orders", methods=["GET"])
@endpoint(ORDER_READ_ROLES, 200)
def list_orders():
    rows = db.db.rows("orders")
    rows = eq_filter(rows, "platform_id", web.filter_value("platform_id"))
    rows = eq_filter(rows, "distributor_code", web.filter_value("distributor_code"))
    rows = eq_filter(rows, "region_code", web.filter_value("region_code"))
    rows = eq_filter(
        rows, "requested_delivery_month", web.filter_value("requested_delivery_month")
    )
    rows = eq_filter(rows, "allocation_status", web.filter_value("allocation_status"))
    rows = eq_filter(rows, "fulfillment_status", web.filter_value("fulfillment_status"))
    return listing(rows, derive.serialize_order)


@bp.route("/plant/distributor-orders/<row_id>", methods=["GET"])
@endpoint(ORDER_READ_ROLES, 200)
def read_order(row_id):
    return derive.serialize_order(find.order(row_id))


def _draw(order, pools, units_to_draw, component_type):
    """Draw units from the eligible pools in order, one line per pool."""
    drawn_pools = []
    remaining = units_to_draw
    for pool in pools:
        if remaining <= 0:
            break
        available = derive.available_units(pool)
        if available <= 0:
            continue
        take = min(available, remaining)
        db.db.insert(
            "lines",
            {
                "distributor_order_id": order["id"],
                "component_supply_id": pool["id"],
                "component_type": component_type,
                "units": take,
                "status": "RESERVED",
                "closed_reason": None,
            },
        )
        remaining -= take
        drawn_pools.append(pool)
    return drawn_pools


@bp.route("/plant/distributor-orders/<row_id>/allocate", methods=["POST"])
@endpoint(["SupplyPlanner"], 200)
def allocate_order(row_id):
    payload = web.body()
    expected_version = validate.int_field(payload, "expected_component_supply_version")

    order = find.order(row_id)
    platform = find.platform(order["platform_id"])

    primary = calc.primary_compressor_supply(order, platform)
    if primary is not None and expected_version != primary["version"]:
        raise ApiError(
            "ERR_STALE_SUPPLY_VERSION",
            "expected_component_supply_version does not match the primary supply row.",
        )
    if order["allocation_status"] not in ("UNALLOCATED", "PARTIALLY_ALLOCATED"):
        raise ApiError("ERR_ORDER_STATE_INVALID", "The order is already fully allocated.")
    if order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_STATE_INVALID", "The order is no longer PENDING.")
    if order["region_code"] in derive.blocked_region_codes(platform):
        raise ApiError(
            "ERR_REGION_NOT_CERTIFIED",
            "The platform is not salable into the order's region.",
        )

    plan = calc.allocation_plan(order, platform)
    granted = plan["granted_units"]
    if granted < 1:
        raise ApiError("ERR_NO_ELIGIBLE_SUPPLY", "No eligible supply can fill this order.")

    touched = []
    touched.extend(_draw(order, plan["compressors"], granted, "COMPRESSOR"))
    touched.extend(_draw(order, plan["boards"], granted, "CONTROL_BOARD"))

    seen = set()
    for pool in sorted(touched, key=lambda p: p["_seq"]):
        if pool["id"] in seen:
            continue
        seen.add(pool["id"])
        cascade.refresh_supply_status(pool)
        db.db.touch(pool)

    cascade.reconcile_order_allocation(order)
    return derive.serialize_order(order)


@bp.route("/plant/distributor-orders/<row_id>/allocation-preview", methods=["GET"])
@endpoint(("PlantAdmin", "SupplyPlanner", "DistributorRep"), 200)
def preview_allocation(row_id):
    order = find.order(row_id)
    platform = find.platform(order["platform_id"])
    policy = web.filter_value("policy")
    if policy is not None and policy not in ("PRIORITY_WATERFALL", "DEMAND_PRORATA"):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "policy must be one of PRIORITY_WATERFALL, DEMAND_PRORATA.",
        )
    plan = calc.allocation_plan(order, platform, policy_override=policy)
    return {
        "order_id": order["id"],
        "policy": plan["policy"],
        "compressor_pool": plan["compressor_pool"],
        "board_pool": plan["board_pool"],
        "kit_capacity": plan["kit_capacity"],
        "remaining_need": plan["remaining_need"],
        "total_open_demand": plan["total_open_demand"],
        "granted_units": plan["granted_units"],
    }


@bp.route("/plant/distributor-orders/<row_id>/stage", methods=["POST"])
@endpoint(["ProductionPlanner"], 200)
def stage_order(row_id):
    web.body()
    order = find.order(row_id)
    if order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_STATE_INVALID", "The order is not PENDING.")
    if order["allocation_status"] != "FULLY_ALLOCATED":
        raise ApiError("ERR_ORDER_STATE_INVALID", "The order is not fully allocated.")
    order["staged_at"] = db.db.stamp()
    order["fulfillment_status"] = "STAGED"
    db.db.touch(order)
    return derive.serialize_order(order)


@bp.route("/plant/distributor-orders/<row_id>/ship", methods=["POST"])
@endpoint(["ProductionPlanner"], 200)
def ship_order(row_id):
    payload = web.body()
    shipped_units = validate.int_field(payload, "shipped_units", minimum=0)

    order = find.order(row_id)
    platform = find.platform(order["platform_id"])
    if order["fulfillment_status"] != "STAGED":
        raise ApiError("ERR_ORDER_STATE_INVALID", "The order is not STAGED.")

    program = derive.platform_program(platform)
    if program is not None and db.db.now() >= program["_sell_through_deadline"]:
        raise ApiError(
            "ERR_SELL_THROUGH_DEADLINE_PASSED",
            "The sell-through deadline has passed.",
        )
    if order["region_code"] in derive.blocked_region_codes(platform):
        raise ApiError(
            "ERR_REGION_NOT_CERTIFIED",
            "The platform is not salable into the order's region.",
        )
    if shipped_units != derive.allocated_units(order):
        raise ApiError(
            "ERR_SHIP_UNITS_EXCEED_ALLOCATION",
            "shipped_units must equal the order's allocated_units.",
        )

    order["fulfillment_status"] = "SHIPPED"
    order["shipped_units"] = shipped_units
    order["shipped_at"] = db.db.stamp()
    db.db.touch(order)

    pools = []
    for line in cascade.asc(derive.order_lines(order, ("RESERVED",))):
        line["status"] = "COMMITTED"
        db.db.touch(line)
        pool = db.db.get("supplies", line["component_supply_id"])
        if pool is not None:
            pools.append(pool)
    seen = set()
    for pool in sorted(pools, key=lambda p: p["_seq"]):
        if pool["id"] in seen:
            continue
        seen.add(pool["id"])
        cascade.refresh_supply_status(pool)
        db.db.touch(pool)

    db.db.touch(platform)
    return derive.serialize_order(order)


@bp.route("/plant/distributor-orders/<row_id>/cancel", methods=["POST"])
@endpoint(["DistributorRep"], 200)
def cancel_order(row_id):
    payload = web.body()
    validate.str_field(payload, "reason", required=False, default=None)

    order = find.order(row_id)
    if order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_ORDER_STATE_INVALID", "The order is not PENDING.")
    if web.actor() != order["created_by_user_id"]:
        raise ApiError(
            "ERR_ORDER_NOT_OWNED", "Only the rep who placed the order may cancel it."
        )

    order["fulfillment_status"] = "CANCELLED"
    order["cancelled_at"] = db.db.stamp()
    cascade.release_order_lines(order, "ORDER_CANCELLED")
    order["allocation_status"] = "UNALLOCATED"
    db.db.touch(order)
    return derive.serialize_order(order)


@bp.route("/plant/distributor-orders/<row_id>/allocation-lines", methods=["GET"])
@endpoint(LINE_READ_ROLES, 200)
def list_order_lines(row_id):
    order = find.order(row_id)
    rows = [l for l in db.db.rows("lines") if l["distributor_order_id"] == order["id"]]
    rows = eq_filter(rows, "status", web.filter_value("status"))
    return listing(rows, derive.serialize_line)
