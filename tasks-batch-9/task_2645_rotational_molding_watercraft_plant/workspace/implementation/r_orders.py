"""Production order routes: release gate, cancellation cascade and cost read."""
from flask import Blueprint

import auth
import calc
import core
import rt
import svc
from core import Checks, S, respond, touch
from errors import fail
from schema import add_schema, body_json, coerce, enum_filter, str_filter

bp = Blueprint("orders", __name__)

ORDER_READ = ("PlantAdmin", "LogisticsPlanner", "MoldingOperator",
              "ResinTechnician", "QualityInspector")
ORDER_WRITE = ("PlantAdmin", "LogisticsPlanner")

ORDER_CREATE = {
    "order_code": {"type": "string", "required": True, "min_len": 3, "max_len": 32},
    "product_model_id": {"type": "string", "required": True},
    "demand_bucket_id": {"type": "string", "required": False},
    "target_warehouse_id": {"type": "string", "required": True},
    "ordered_qty": {"type": "int", "required": True, "min": 1,
                    "bound_error": "ERR_INVALID_QUANTITY"},
}

CANCEL_SPEC = {"cancel_reason": {"type": "string", "required": True,
                                 "min_len": 1, "max_len": 500}}


@bp.route("/production-orders", methods=["POST"])
def create_order():
    auth.authenticate(ORDER_WRITE)
    body = body_json()
    checks = Checks()
    holder = {}
    add_schema(checks, body, ORDER_CREATE)

    def resolve():
        holder["model"] = rt.find("product_models", body.get("product_model_id"))
        holder["site"] = rt.find("warehouses", body.get("target_warehouse_id"))
        if body.get("demand_bucket_id") is not None:
            holder["bucket"] = rt.find("demand_buckets", body.get("demand_bucket_id"))

    def bucket_model():
        bucket = holder.get("bucket")
        if bucket is not None and bucket["product_model_id"] != body["product_model_id"]:
            fail("ERR_VALIDATION",
                 "demand_bucket_id names a bucket of another hull model.")

    checks.add(11, resolve)
    checks.add(23.5, bucket_model)
    checks.add(26, lambda: rt.unique_code("production_orders", "order_code",
                                          body.get("order_code")))
    checks.run()
    row = coerce(body, ORDER_CREATE)
    row["completed_qty"] = 0
    row["scrapped_qty"] = 0
    row["status"] = "DRAFT"
    row["blocked_reason"] = None
    row["material_cost_cents"] = 0
    row["oven_energy_cost_cents"] = 0
    row["overhead_cents"] = 0
    row["total_cost_cents"] = 0
    row["unit_cost_cents"] = None
    core.insert("production_orders", row)
    return rt.one("production_orders", row, 201)


@bp.route("/production-orders", methods=["GET"])
def list_orders():
    auth.authenticate(ORDER_READ)
    checks = Checks()
    items = [None]

    def collect():
        rows = core.rows("production_orders")
        rows = rt.filter_eq(rows, "product_model_id", str_filter("product_model_id"))
        rows = rt.filter_eq(rows, "demand_bucket_id", str_filter("demand_bucket_id"))
        rows = rt.filter_eq(rows, "target_warehouse_id",
                            str_filter("target_warehouse_id"))
        rows = rt.filter_eq(rows, "status", enum_filter("status", rt.ORDER_STATUSES))
        rows = rt.filter_eq(rows, "blocked_reason",
                            enum_filter("blocked_reason", rt.BLOCKED_REASONS))
        items[0] = rows

    checks.add(21, collect)
    checks.run()
    return rt.many("production_orders", items[0])


@bp.route("/production-orders/<production_order_id>", methods=["GET"])
def read_order(production_order_id):
    auth.authenticate(ORDER_READ)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("production_orders", production_order_id)))
    checks.run()
    return rt.one("production_orders", holder["row"])


@bp.route("/production-orders/<production_order_id>/release", methods=["POST"])
def release_order(production_order_id):
    auth.authenticate(ORDER_WRITE)
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("production_orders", production_order_id)))
    add_schema(checks, body, {})

    def state():
        if holder["row"]["status"] != "DRAFT":
            fail("ERR_ORDER_NOT_SCHEDULABLE",
                 "Order status is %s." % holder["row"]["status"])

    def tooling():
        order = holder["row"]
        # PRD.md section 3.3 fixes the order of the release preconditions: "the
        # target site's `posture` is not `FROZEN`, otherwise
        # `ERR_WAREHOUSE_FROZEN` (HTTP 409); at least one mould exists for the
        # order's hull model in `status` `AVAILABLE`, `IN_CYCLE` or
        # `MAINTENANCE`, otherwise `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)".  A frozen
        # site is therefore answered — here by the soft `BLOCKED_WAREHOUSE`
        # outcome below — before the tooling gate is consulted at all.
        site = S.warehouses.get(order["target_warehouse_id"])
        if site is not None and site["posture"] == "FROZEN":
            return
        for mold in core.rows("molds"):
            if mold["product_model_id"] == order["product_model_id"] and \
                    mold["status"] in ("AVAILABLE", "IN_CYCLE", "MAINTENANCE"):
                return
        fail("ERR_NO_ELIGIBLE_MOLD", "No unretired tool exists for this hull model.")

    checks.add(34, state)
    checks.add(70, tooling)
    checks.run()
    order = holder["row"]
    site = S.warehouses.get(order["target_warehouse_id"])
    model = S.product_models.get(order["product_model_id"])
    # The warehouse gate is read before the resin gate: an order that is both
    # frozen out and resin starved lands in BLOCKED_WAREHOUSE.
    if site is not None and site["posture"] == "FROZEN":
        order["status"] = "BLOCKED_WAREHOUSE"
        order["blocked_reason"] = "WAREHOUSE_FROZEN"
    elif calc.qualified_lot_count(model) < 1:
        order["status"] = "BLOCKED_RESIN"
        order["blocked_reason"] = "NO_QUALIFIED_RESIN_LOT"
    else:
        order["status"] = "READY_TO_SCHEDULE"
        order["blocked_reason"] = None
    svc.apply_cost(order)
    touch(order)
    return rt.one("production_orders", order)


@bp.route("/production-orders/<production_order_id>/cancel", methods=["POST"])
def cancel_order(production_order_id):
    auth.authenticate(ORDER_WRITE)
    body = body_json()
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("production_orders", production_order_id)))
    add_schema(checks, body, CANCEL_SPEC)

    def state():
        if holder["row"]["status"] in ("COMPLETE", "CANCELLED"):
            fail("ERR_ORDER_ALREADY_TERMINAL",
                 "Order status is %s." % holder["row"]["status"])

    checks.add(34, state)
    checks.run()
    order = holder["row"]
    revived = False
    for cycle in core.sorted_rows(calc.cycles_of_order(order)):
        if cycle["status"] not in ("SCHEDULED", "OVEN_RUNNING", "COOLING"):
            continue
        svc.abort_cycle(cycle, "ORDER_CANCELLED", "ORDER_CANCELLED")
        revived = True
    order["status"] = "CANCELLED"
    order["blocked_reason"] = None
    order["cancel_reason"] = body["cancel_reason"]
    touch(order)
    if revived:
        svc.sweep_unblock_resin()
    return rt.one("production_orders", order)


@bp.route("/production-orders/<production_order_id>/cost-summary", methods=["GET"])
def order_cost_summary(production_order_id):
    auth.authenticate(ORDER_WRITE)
    checks = Checks()
    holder = {}
    checks.add(10, lambda: holder.update(
        row=rt.find("production_orders", production_order_id)))
    checks.run()
    order = holder["row"]
    figures = calc.order_cost(order)
    return respond({
        "production_order_id": order["id"],
        "consumed_charge_count": figures["consumed_charge_count"],
        "material_cost_cents": figures["material_cost_cents"],
        "demolded_cycle_count": figures["demolded_cycle_count"],
        "oven_energy_cost_cents": figures["oven_energy_cost_cents"],
        "pre_overhead_subtotal_cents": figures["pre_overhead_subtotal_cents"],
        "overhead_rate_pct": figures["overhead_rate_pct"],
        "overhead_cents": figures["overhead_cents"],
        "total_cost_cents": figures["total_cost_cents"],
        "completed_qty": figures["completed_qty"],
        "unit_cost_cents": figures["unit_cost_cents"],
    })
