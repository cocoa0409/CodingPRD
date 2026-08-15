"""ProductionOrder endpoints (PRD §3.5, §3.6)."""

from decimal import Decimal
from flask import request

from db import STORE, new_record, bump
from errors import ApiError
from middleware import endpoint, ANY_ROLE
from response import ok_object, list_response
from serializers import ser_order
from services import (
    get_batch,
    get_lot,
    get_order,
    get_tool,
    get_spec,
    allocations_of,
    release_allocation,
    compute_provisional_cost,
)
from util import (
    BLEND_CAP,
    GRADE_RANK,
    GRADES,
    PROTO_SHOT_LIMIT,
    RESIN_TYPES,
    TRIM_ALLOWANCE_FACTOR,
    as_bool,
    as_decimal,
    as_enum,
    as_int,
    as_positive_decimal,
    as_positive_int,
    as_string,
    body_dict,
    opt_present,
    q3,
    req_present,
)

from routes import bp


def blend_cap_kg(order):
    return q3(order["required_material_kg"] * BLEND_CAP[order["cleanliness_grade"]])


def reserved_regrind_kg(order):
    total = Decimal("0")
    for a in allocations_of(order["id"]):
        if a["source_type"] == "REGRIND" and a["status"] == "RESERVED":
            total += a["qty_kg"]
    return total


@bp.route("/production-orders", methods=["POST"])
@endpoint({"ProductionScheduler"})
def create_order(user_id, role):
    body = body_dict(request.get_json(silent=True))
    order_code = as_string(req_present(body, "order_code"), "order_code")
    part_number = as_string(req_present(body, "part_number"), "part_number")
    resin_type = as_enum(req_present(body, "resin_type"), "resin_type", RESIN_TYPES)
    ordered_qty = as_positive_int(req_present(body, "ordered_qty"), "ordered_qty")
    required_gauge = as_decimal(req_present(body, "required_gauge_mm"), "required_gauge_mm")
    grade = as_enum(req_present(body, "cleanliness_grade"), "cleanliness_grade", GRADES)
    nominal_wall = as_decimal(req_present(body, "spec_nominal_wall_mm"), "spec_nominal_wall_mm")
    min_wall = as_decimal(req_present(body, "spec_min_wall_mm"), "spec_min_wall_mm")
    if min_wall > nominal_wall:
        raise ApiError("ERR_INVALID_REQUEST", "spec_min_wall_mm must be <= spec_nominal_wall_mm")
    nominal_weight = as_positive_decimal(req_present(body, "nominal_part_weight_kg"), "nominal_part_weight_kg")
    std_cycle = as_positive_int(req_present(body, "std_cycle_time_s"), "std_cycle_time_s")
    std_rate = as_positive_decimal(req_present(body, "std_machine_rate_per_hour"), "std_machine_rate_per_hour")
    tool_id = as_string(req_present(body, "tool_id"), "tool_id")
    spec_id = as_string(req_present(body, "packaging_spec_id"), "packaging_spec_id")
    is_proto = opt_present(body, "is_prototype_order", False)
    is_proto = as_bool(is_proto, "is_prototype_order")

    # p4 existence (body order: tool_id, then packaging_spec_id)
    tool = get_tool(tool_id)
    spec = get_spec(spec_id)
    # p6 state legality
    if tool["status"] not in ("PROTOTYPE", "PRODUCTION"):
        raise ApiError("ERR_TOOL_NOT_QUALIFIED", "Order create requires tool in PROTOTYPE or PRODUCTION")
    if spec["status"] not in ("ACTIVE", "PENDING_APPROVAL", "APPROVED"):
        raise ApiError("ERR_PACK_SPEC_NOT_APPROVED", "Order create against a REJECTED spec is not permitted")
    # p7 cleanliness compatibility: spec grade >= order grade
    if GRADE_RANK[spec["cleanliness_grade"]] < GRADE_RANK[grade]:
        raise ApiError("ERR_GRADE_INCOMPATIBLE", "Packaging spec grade is below the order grade")
    # p9 domain constraints
    if part_number != tool["part_number"]:
        raise ApiError("ERR_INVALID_REQUEST", "part_number must equal the referenced tool's part_number")
    if required_gauge < tool["min_gauge_mm"] or required_gauge > tool["max_gauge_mm"]:
        raise ApiError("ERR_GAUGE_MISMATCH", "required_gauge_mm lies outside the tool's gauge window")
    if tool["status"] == "PROTOTYPE":
        if not is_proto:
            raise ApiError(
                "ERR_PROTOTYPE_ORDER_REQUIRED",
                "Orders on a PROTOTYPE tool must set is_prototype_order=true",
            )
        if ordered_qty > PROTO_SHOT_LIMIT:
            raise ApiError(
                "ERR_PROTOTYPE_SHOT_LIMIT_EXCEEDED",
                "Prototype order quantity exceeds the 500-shot prototype limit",
            )

    required_material = q3(Decimal(ordered_qty) * nominal_weight * TRIM_ALLOWANCE_FACTOR)

    rec = new_record()
    rec.update({
        "order_code": order_code,
        "part_number": part_number,
        "resin_type": resin_type,
        "ordered_qty": ordered_qty,
        "required_gauge_mm": required_gauge,
        "cleanliness_grade": grade,
        "is_prototype_order": is_proto,
        "spec_nominal_wall_mm": nominal_wall,
        "spec_min_wall_mm": min_wall,
        "nominal_part_weight_kg": nominal_weight,
        "std_cycle_time_s": std_cycle,
        "std_machine_rate_per_hour": std_rate,
        "tool_id": tool["id"],
        "packaging_spec_id": spec["id"],
        "required_material_kg": required_material,
        "shots_completed": 0,
        "shots_scrapped": 0,
        "provisional_cost": None,
        "tooling_charge": None,
        "final_cost": None,
        "schedule_status": "QUEUED",
        "quality_status": "PENDING",
    })
    STORE["production_orders"][rec["id"]] = rec
    return ok_object(ser_order(rec), 201)


@bp.route("/production-orders", methods=["GET"])
@endpoint(ANY_ROLE)
def list_orders(user_id, role):
    items = list(STORE["production_orders"].values())
    schedule_status = request.args.get("schedule_status")
    if schedule_status is not None:
        items = [o for o in items if o["schedule_status"] == schedule_status]
    tool_id = request.args.get("tool_id")
    if tool_id is not None:
        items = [o for o in items if o["tool_id"] == tool_id]
    spec_id = request.args.get("packaging_spec_id")
    if spec_id is not None:
        items = [o for o in items if o["packaging_spec_id"] == spec_id]
    return list_response(items, ser_order)


@bp.route("/production-orders/<orderId>", methods=["GET"])
@endpoint(ANY_ROLE)
def get_one_order(user_id, role, orderId):
    return ok_object(ser_order(get_order(orderId)))


@bp.route("/production-orders/<orderId>/stage", methods=["POST"])
@endpoint({"ProductionScheduler"})
def stage_order(user_id, role, orderId):
    body = body_dict(request.get_json(silent=True))
    expected = as_int(req_present(body, "expected_production_order_version"), "expected_production_order_version")

    order = get_order(orderId)
    # p5 OCC freshness (before state, per PRD §2.9)
    if expected != order["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_production_order_version does not match the order's current version",
        )
    # p6 state
    if order["schedule_status"] != "QUEUED":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Stage requires schedule_status QUEUED")
    tool = get_tool(order["tool_id"])
    if tool["status"] not in ("PROTOTYPE", "PRODUCTION"):
        raise ApiError("ERR_TOOL_NOT_QUALIFIED", "Stage requires tool in PROTOTYPE or PRODUCTION")
    # p9 domain: regrind blend re-check against cumulative RESERVED regrind mass
    if reserved_regrind_kg(order) > blend_cap_kg(order):
        raise ApiError("ERR_BLEND_CAP_EXCEEDED", "Cumulative RESERVED regrind exceeds the blend cap")
    # p10 material sufficiency: RESERVED coverage >= required_material_kg
    coverage = Decimal("0")
    for a in allocations_of(order["id"]):
        if a["status"] == "RESERVED":
            coverage += a["qty_kg"]
    if coverage < order["required_material_kg"]:
        raise ApiError(
            "ERR_INSUFFICIENT_MATERIAL",
            "RESERVED coverage is below required_material_kg",
        )

    provisional, tooling = compute_provisional_cost(order)
    order["provisional_cost"] = provisional
    order["tooling_charge"] = tooling
    order["schedule_status"] = "STAGED"
    bump(order)
    return ok_object(ser_order(order))


@bp.route("/production-orders/<orderId>/hold", methods=["POST"])
@endpoint({"ProductionScheduler"})
def hold_order(user_id, role, orderId):
    order = get_order(orderId)
    if order["schedule_status"] != "RUNNING":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Hold requires schedule_status RUNNING")
    order["schedule_status"] = "ON_HOLD"
    bump(order)
    return ok_object(ser_order(order))


@bp.route("/production-orders/<orderId>/resume", methods=["POST"])
@endpoint({"ProductionScheduler"})
def resume_order(user_id, role, orderId):
    order = get_order(orderId)
    if order["schedule_status"] != "ON_HOLD":
        raise ApiError("ERR_INVALID_ORDER_STATE", "Resume requires schedule_status ON_HOLD")
    tool = get_tool(order["tool_id"])
    if tool["status"] not in ("PROTOTYPE", "PRODUCTION"):
        raise ApiError("ERR_TOOL_NOT_QUALIFIED", "Resume requires tool in PROTOTYPE or PRODUCTION")
    # Re-validate every REVIEW allocation (atomically: all must pass before any flips)
    review = [a for a in allocations_of(order["id"]) if a["status"] == "REVIEW"]
    for a in review:
        if a["source_type"] == "VIRGIN_LOT":
            lot = get_lot(a["lot_id"])
            ok = lot["status"] == "CERTIFIED" and lot["available_kg"] >= a["qty_kg"]
        else:
            batch = get_batch(a["regrind_batch_id"])
            ok = batch["status"] in ("CERTIFIED", "DOWNGRADED") and batch["available_kg"] >= a["qty_kg"]
        if not ok:
            raise ApiError(
                "ERR_ALLOCATION_REVIEW_FAILED",
                "Resume re-validation failed for at least one REVIEW allocation",
            )
    for a in review:
        a["status"] = "RESERVED"
        bump(a)
    if order["quality_status"] == "REWORK_HOLD":
        order["quality_status"] = "PENDING"
    order["schedule_status"] = "RUNNING"
    bump(order)
    return ok_object(ser_order(order))


@bp.route("/production-orders/<orderId>/cancel", methods=["POST"])
@endpoint({"ProductionScheduler"})
def cancel_order(user_id, role, orderId):
    order = get_order(orderId)
    if order["schedule_status"] not in ("QUEUED", "STAGED", "RUNNING", "ON_HOLD"):
        raise ApiError(
            "ERR_INVALID_ORDER_STATE",
            "Cancel requires schedule_status QUEUED, STAGED, RUNNING, or ON_HOLD",
        )
    for a in allocations_of(order["id"]):
        if a["status"] in ("RESERVED", "REVIEW"):
            release_allocation(a)
    order["schedule_status"] = "CANCELLED"
    bump(order)
    return ok_object(ser_order(order))
