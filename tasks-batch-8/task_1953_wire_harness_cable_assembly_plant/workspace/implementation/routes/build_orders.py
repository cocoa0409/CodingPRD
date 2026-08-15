"""Build orders: creation, OCC edit, release to kitting, cancel, harness build (PRD 3.5, 3.7)."""
from flask import Blueprint, request

from db import db
from errors import (raise_error, ERR_INVALID_REQUEST, ERR_DRAWING_NOT_RELEASED,
                    ERR_STALE_BUILD_ORDER_VERSION, ERR_BUILD_ORDER_NOT_OPEN,
                    ERR_NO_QUALIFIED_PROGRAM, ERR_BUILD_ORDER_NOT_IN_BUILD)
from middleware import authenticate, ALL_ROLES
from response import success_object
from services import (common_fields, touch, bom_lines, order_kits,
                      kit_shortage_count, recompute_order_counters,
                      order_status_checks, ser_build_order, ser_harness_unit,
                      paginated)
from util import CLOCK
from validate import (get_body, req_str, req_int, opt_nullable_int, _UNSET,
                      require_path, require_fk)

bp = Blueprint("build_orders", __name__)

PRODUCTION_PLANNER = {"ProductionPlanner"}
LINE_OPERATOR = {"LineOperator"}

RELEASEABLE_STATUSES = {"OPEN", "KITTING", "IN_BUILD", "TESTING"}


@bp.route("/plant/build-orders", methods=["POST"])
def create_build_order():
    body = get_body()
    order_code = req_str(body, "order_code")
    drawing_id = req_str(body, "drawing_id")
    qty_ordered = req_int(body, "qty_ordered", minimum=1)
    budget = opt_nullable_int(body, "material_budget_cents", minimum=0)
    if budget is _UNSET:
        budget = None
    authenticate(PRODUCTION_PLANNER)
    drawing = require_fk("drawings", drawing_id, "drawing_id")
    if drawing["status"] != "RELEASED":
        raise_error(ERR_DRAWING_NOT_RELEASED,
                    "build orders require a RELEASED drawing")
    for o in db["build_orders"].values():
        if o["order_code"] == order_code:
            raise_error(ERR_INVALID_REQUEST, f"duplicate order_code: {order_code}")

    order = common_fields()
    order.update({
        "order_code": order_code,
        "drawing_id": drawing["id"],
        # Revision and class are pinned at creation and never change (PRD 3.5).
        "drawing_revision_pinned": drawing["revision"],
        "workmanship_class": drawing["workmanship_class"],
        "qty_ordered": qty_ordered,
        "material_budget_cents": budget,
        "material_spent_cents": 0,
        "qty_built": 0,
        "qty_scrapped": 0,
        "standard_cost_cents": 0,
        "actual_cost_cents": 0,
        "scrap_recovery_credit_cents": 0,
        "status": "OPEN",
        "qc_hold_return_status": None,
        "held_by_program_id": None,
        "use_as_is_flag": False,
        "next_unit_seq": 1,
    })
    db["build_orders"][order["id"]] = order
    return success_object(ser_build_order(order), 201)


@bp.route("/plant/build-orders/<oid>", methods=["GET"])
def get_build_order(oid):
    authenticate(ALL_ROLES)
    order = require_path("build_orders", oid)
    return success_object(ser_build_order(order), 200)


@bp.route("/plant/build-orders", methods=["GET"])
def list_build_orders():
    authenticate(ALL_ROLES)
    items = list(db["build_orders"].values())
    drawing_id = request.args.get("drawing_id")
    if drawing_id is not None:
        items = [o for o in items if o["drawing_id"] == drawing_id]
    status = request.args.get("status")
    if status is not None:
        items = [o for o in items if o["status"] == status]
    held_by_program_id = request.args.get("held_by_program_id")
    if held_by_program_id is not None:
        items = [o for o in items if o["held_by_program_id"] == held_by_program_id]
    return paginated(items, ser_build_order)


@bp.route("/plant/build-orders/<oid>", methods=["PATCH"])
def patch_build_order(oid):
    body = get_body()
    # Tier 1: OCC field is a non-optional input (PRD 2.7).
    expected_version = req_int(body, "expected_build_order_version")
    qty_ordered = None
    if "qty_ordered" in body and body["qty_ordered"] is not None:
        qty_ordered = req_int(body, "qty_ordered", minimum=1)
    budget = opt_nullable_int(body, "material_budget_cents", minimum=0)
    # Tiers 2-3
    authenticate(PRODUCTION_PLANNER)
    # Tier 4
    order = require_path("build_orders", oid)
    # Tier 5: a stale version beats the not-OPEN rejection (PRD 2.6 example).
    if expected_version != order["version"]:
        raise_error(ERR_STALE_BUILD_ORDER_VERSION,
                    "expected_build_order_version does not match current version")
    # Tier 6
    if order["status"] != "OPEN":
        raise_error(ERR_BUILD_ORDER_NOT_OPEN,
                    "only an OPEN build order may be edited")

    if qty_ordered is not None:
        order["qty_ordered"] = qty_ordered
    if budget is not _UNSET:
        order["material_budget_cents"] = budget
    touch(order)
    return success_object(ser_build_order(order), 200)


@bp.route("/plant/build-orders/<oid>/release-to-kitting", methods=["POST"])
def release_to_kitting(oid):
    get_body()
    authenticate(PRODUCTION_PLANNER)
    order = require_path("build_orders", oid)
    # Tier 6: state preconditions — order in a releaseable status with no
    # PICKING/STAGED kit, and at least one QUALIFIED program for the drawing.
    active_kit = any(k["status"] in ("PICKING", "STAGED") for k in order_kits(order["id"]))
    if order["status"] not in RELEASEABLE_STATUSES or active_kit:
        raise_error(ERR_BUILD_ORDER_NOT_OPEN,
                    "order is not releaseable (terminal/QC_HOLD status or an active kit)")
    qualified = any(p["drawing_id"] == order["drawing_id"] and p["status"] == "QUALIFIED"
                    for p in db["machine_programs"].values())
    if not qualified:
        raise_error(ERR_NO_QUALIFIED_PROGRAM,
                    "no QUALIFIED machine program exists for the order's drawing")

    kit = common_fields()
    kit.update({
        "build_order_id": order["id"],
        "kit_seq": len(order_kits(order["id"])) + 1,
        "status": "PICKING",
        "issues": [],
        "shortage_count": sum(c["qty_per_harness"] * order["qty_ordered"]
                              for c in bom_lines(order["drawing_id"])),
        "delivered_at": None,
    })
    db["kits"][kit["id"]] = kit

    if order["status"] == "OPEN":
        order["status"] = "KITTING"
    touch(order)
    return success_object(ser_build_order(order), 200)


@bp.route("/plant/build-orders/<oid>/cancel", methods=["POST"])
def cancel_build_order(oid):
    get_body()
    authenticate(PRODUCTION_PLANNER)
    order = require_path("build_orders", oid)
    if order["status"] != "OPEN":
        raise_error(ERR_BUILD_ORDER_NOT_OPEN, "only an OPEN build order may be cancelled")
    order["status"] = "CANCELLED"
    touch(order)
    return success_object(ser_build_order(order), 200)


@bp.route("/plant/build-orders/<oid>/harness-units", methods=["POST"])
def create_harness_unit(oid):
    get_body()
    caller = authenticate(LINE_OPERATOR)
    order = require_path("build_orders", oid)
    if order["status"] != "IN_BUILD":
        raise_error(ERR_BUILD_ORDER_NOT_IN_BUILD,
                    "harness units may only be recorded while the order is IN_BUILD")

    seq = order["next_unit_seq"]
    order["next_unit_seq"] = seq + 1

    unit = common_fields()
    unit.update({
        "build_order_id": order["id"],
        "serial_number": f"{order['order_code']}-{seq:04d}",
        "drawing_revision_built": order["drawing_revision_pinned"],
        "built_by_operator_id": caller.user_id,
        "status": "BUILT",
        "rework_count": 0,
        "continuity_pass": False,
        "hipot_pass": False,
        "suspect_marked_at": None,
        "scrap_reason": None,
        "_continuity_pass_at": None,
        "_hipot_pass_at": None,
    })
    db["harness_units"][unit["id"]] = unit

    recompute_order_counters(order)
    order_status_checks(order)
    touch(order)
    return success_object(ser_harness_unit(unit), 201)
