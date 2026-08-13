"""Production orders and batches (PRD §3.2, §3.3)."""

from flask import request

import services as svc
from db import STORE, bump, new_record
from errors import ApiError
from middleware import ALL_ROLES, PLANT_ROLES, endpoint
from response import list_response, ok_object
from routes import bp
from serializers import batch_out, order_out
from util import (
    PACK_FORMATS,
    as_enum,
    as_int,
    as_positive_decimal,
    as_positive_int,
    as_string,
    body_dict,
    opt_present,
    parse_dt,
    req_present,
)


# ---------------------------------------------------------------------------
# Production orders
# ---------------------------------------------------------------------------

@bp.route("/plant/production-orders", methods=["POST"])
@endpoint({"ProductionPlanner"})
def create_order(user_id, role):
    body = body_dict(request.get_json(silent=True))
    recipe_id = as_string(req_present(body, "recipe_id"), "recipe_id")
    pack_format = as_enum(req_present(body, "pack_format"), "pack_format", PACK_FORMATS)
    units_planned = as_positive_int(req_present(body, "units_planned"), "units_planned")
    customer_id = opt_present(body, "copack_customer_id")
    if customer_id is not None:
        customer_id = as_string(customer_id, "copack_customer_id")
    due_at = opt_present(body, "due_at")
    if due_at is not None:
        due_at = parse_dt(due_at, "due_at")

    # body FK existence (stage 6), in input order: recipe_id, then copack_customer_id
    recipe = svc.require_record("recipes", recipe_id, "Recipe")
    if customer_id is not None:
        svc.require_record("customers", customer_id, "CoPackCustomer")
    # state (stage 8): recipe must be APPROVED at creation
    if recipe["status"] != "APPROVED":
        raise ApiError("ERR_RECIPE_NOT_APPROVED", "Recipe must be APPROVED at order creation")

    rec = new_record()
    rec.update(
        recipe_id=recipe_id,
        copack_customer_id=customer_id,
        pack_format=pack_format,
        units_planned=units_planned,
        due_at=due_at,
        status="PLANNED",
    )
    STORE["orders"][rec["id"]] = rec
    return ok_object(order_out(rec), 201)


@bp.route("/plant/production-orders", methods=["GET"])
@endpoint(ALL_ROLES)
def list_orders(user_id, role):
    recipe_id = request.args.get("recipe_id")
    customer_id = request.args.get("copack_customer_id")
    status = request.args.get("status")
    if role == "CoPackCustomer" and customer_id is not None and customer_id != user_id:
        raise ApiError(
            "ERR_CROSS_CUSTOMER_ACCESS", "CoPackCustomer may read only its own orders"
        )
    recs = list(STORE["orders"].values())
    if role == "CoPackCustomer":
        recs = [o for o in recs if o["copack_customer_id"] == user_id]
    if recipe_id is not None:
        recs = [o for o in recs if o["recipe_id"] == recipe_id]
    if customer_id is not None:
        recs = [o for o in recs if o["copack_customer_id"] == customer_id]
    if status is not None:
        recs = [o for o in recs if o["status"] == status]
    return list_response(recs, order_out)


@bp.route("/plant/production-orders/<orderId>", methods=["GET"])
@endpoint(ALL_ROLES)
def get_order(user_id, role, orderId):
    order = svc.require_record("orders", orderId, "ProductionOrder")
    if role == "CoPackCustomer":
        svc.assert_customer_scope(user_id, order)
    return ok_object(order_out(order))


@bp.route("/plant/production-orders/<orderId>/cancel", methods=["POST"])
@endpoint({"ProductionPlanner"})
def cancel_order(user_id, role, orderId):
    order = svc.require_record("orders", orderId, "ProductionOrder")
    if order["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError("ERR_ORDER_NOT_OPEN", "Order is not open for cancellation")
    batches = svc.batches_of_order(order["id"])
    if any(b["status"] not in ("CREATED", "CANCELLED") for b in batches):
        raise ApiError(
            "ERR_ORDER_NOT_OPEN", "Every batch must be CREATED or CANCELLED to cancel the order"
        )
    for b in batches:
        if b["status"] == "CREATED":
            b["status"] = "CANCELLED"
            bump(b)
    order["status"] = "CANCELLED"
    bump(order)
    return ok_object(order_out(order))


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@bp.route("/plant/production-orders/<orderId>/batches", methods=["POST"])
@endpoint({"ProductionPlanner"})
def create_batch(user_id, role, orderId):
    body = body_dict(request.get_json(silent=True))
    units_planned = as_positive_int(req_present(body, "units_planned"), "units_planned")
    expected = as_int(req_present(body, "expected_order_version"), "expected_order_version")

    order = svc.require_record("orders", orderId, "ProductionOrder")
    # OCC (stage 7) before state (stage 8) per PRD §2.4
    if expected != order["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", "expected_order_version does not match the order's current version"
        )
    if order["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise ApiError("ERR_ORDER_NOT_OPEN", "Order is not open for batch creation")

    rec = new_record()
    rec.update(
        order_id=order["id"],
        units_planned=units_planned,
        cooked_mass_kg=None,
        status="CREATED",
        hold_origin_state=None,
        hold_reason=None,
    )
    STORE["batches"][rec["id"]] = rec
    # batch creation advances the order's version; the first batch under a
    # PLANNED order also auto-transitions it to IN_PROGRESS with its own bump.
    bump(order)
    if order["status"] == "PLANNED":
        order["status"] = "IN_PROGRESS"
        bump(order)
    return ok_object(batch_out(rec), 201)


@bp.route("/plant/production-orders/<orderId>/batches", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_order_batches(user_id, role, orderId):
    svc.require_record("orders", orderId, "ProductionOrder")
    recs = svc.batches_of_order(orderId)
    return list_response(recs, batch_out)


@bp.route("/plant/production-batches", methods=["GET"])
@endpoint(PLANT_ROLES)
def list_batches(user_id, role):
    order_id = request.args.get("order_id")
    status = request.args.get("status")
    recs = list(STORE["batches"].values())
    if order_id is not None:
        recs = [b for b in recs if b["order_id"] == order_id]
    if status is not None:
        recs = [b for b in recs if b["status"] == status]
    return list_response(recs, batch_out)


@bp.route("/plant/production-batches/<batchId>", methods=["GET"])
@endpoint(PLANT_ROLES)
def get_batch(user_id, role, batchId):
    return ok_object(batch_out(svc.require_record("batches", batchId, "ProductionBatch")))


# ---------------------------------------------------------------------------
# Batch transitions (PRD §3.3)
# ---------------------------------------------------------------------------

@bp.route("/plant/production-batches/<batchId>/kit", methods=["POST"])
@endpoint({"LineOperator"})
def kit_batch(user_id, role, batchId):
    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] == "CREATED":
        order = svc.order_of_batch(batch)
        if order is None or order["status"] not in ("PLANNED", "IN_PROGRESS"):
            raise ApiError("ERR_ORDER_NOT_OPEN", "Owning order is not open")
        recipe = svc.recipe_of_order(order)
        if recipe is None or recipe["status"] != "APPROVED":
            raise ApiError("ERR_RECIPE_NOT_APPROVED", "The order's recipe is not APPROVED")
    elif batch["status"] == "REWORK":
        order = svc.order_of_batch(batch)
        if order is None or order["status"] != "IN_PROGRESS":
            raise ApiError("ERR_ORDER_NOT_OPEN", "Owning order is not IN_PROGRESS")
    else:
        raise ApiError("ERR_BATCH_STATE", "Batch cannot be kitted from %s" % batch["status"])
    batch["status"] = "KITTED"
    bump(batch)
    return ok_object(batch_out(batch))


@bp.route("/plant/production-batches/<batchId>/cook", methods=["POST"])
@endpoint({"LineOperator"})
def cook_batch(user_id, role, batchId):
    body = body_dict(request.get_json(silent=True))
    mass = as_positive_decimal(req_present(body, "cooked_mass_kg"), "cooked_mass_kg")
    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] != "KITTED":
        raise ApiError("ERR_BATCH_STATE", "Batch cannot be cooked from %s" % batch["status"])
    batch["cooked_mass_kg"] = mass
    batch["status"] = "COOKED"
    bump(batch)
    return ok_object(batch_out(batch))


@bp.route("/plant/production-batches/<batchId>/complete", methods=["POST"])
@endpoint({"LineOperator"})
def complete_batch(user_id, role, batchId):
    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] != "PACKED":
        raise ApiError("ERR_BATCH_STATE", "Batch cannot be completed from %s" % batch["status"])
    if not svc.lots_of_batch(batch["id"]):
        raise ApiError(
            "ERR_BATCH_STATE", "At least one finished-goods lot must exist before completion"
        )
    batch["status"] = "COMPLETED"
    bump(batch)
    order = svc.order_of_batch(batch)
    if order is not None:
        svc.order_completion_check(order)
    return ok_object(batch_out(batch))


@bp.route("/plant/production-batches/<batchId>/hold", methods=["POST"])
@endpoint({"QATechnician"})
def hold_batch(user_id, role, batchId):
    body = body_dict(request.get_json(silent=True))
    reason = as_string(req_present(body, "reason"), "reason")
    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] not in ("KITTED", "COOKED", "FROZEN", "PACKED"):
        raise ApiError("ERR_BATCH_STATE", "Batch cannot be held from %s" % batch["status"])
    batch["hold_origin_state"] = batch["status"]
    batch["hold_reason"] = reason
    batch["status"] = "ON_HOLD"
    bump(batch)
    return ok_object(batch_out(batch))


@bp.route("/plant/production-batches/<batchId>/resume", methods=["POST"])
@endpoint({"QATechnician"})
def resume_batch(user_id, role, batchId):
    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] != "ON_HOLD":
        raise ApiError("ERR_BATCH_STATE", "Batch is not ON_HOLD")
    origin = batch["hold_origin_state"]
    reason = batch["hold_reason"] or ""
    if reason.startswith("CCP_FAIL:"):
        check_type = reason.split(":", 1)[1]
        latest = svc.latest_check(batch["id"], check_type)
        if latest is None or latest["result"] != "PASS":
            raise ApiError(
                "ERR_BATCH_STATE",
                "The latest %s check on this batch must be PASS before resume" % check_type,
            )
    batch["status"] = origin
    batch["hold_origin_state"] = None
    batch["hold_reason"] = None
    bump(batch)
    return ok_object(batch_out(batch))


@bp.route("/plant/production-batches/<batchId>/rework", methods=["POST"])
@endpoint({"QAManager"})
def rework_batch(user_id, role, batchId):
    body = body_dict(request.get_json(silent=True))
    as_string(req_present(body, "reason"), "reason")
    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] != "ON_HOLD":
        raise ApiError("ERR_BATCH_STATE", "Only an ON_HOLD batch can be sent to rework")
    batch["status"] = "REWORK"
    batch["hold_origin_state"] = None
    batch["hold_reason"] = None
    bump(batch)
    return ok_object(batch_out(batch))


@bp.route("/plant/production-batches/<batchId>/cancel", methods=["POST"])
@endpoint({"ProductionPlanner"})
def cancel_batch(user_id, role, batchId):
    batch = svc.require_record("batches", batchId, "ProductionBatch")
    if batch["status"] not in ("CREATED", "ON_HOLD"):
        raise ApiError("ERR_BATCH_STATE", "Batch cannot be cancelled from %s" % batch["status"])
    if batch["status"] == "ON_HOLD":
        for cyc in svc.cycles_of_batch(batch["id"]):
            if cyc["status"] == "RESERVED":
                svc.void_reserved_cycle(cyc)
        for run in svc.runs_of_batch(batch["id"]):
            if run["status"] == "SCHEDULED":
                svc.cancel_scheduled_run(run)
    batch["status"] = "CANCELLED"
    bump(batch)
    order = svc.order_of_batch(batch)
    if order is not None:
        svc.order_completion_check(order)
    return ok_object(batch_out(batch))
