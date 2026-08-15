"""Blender and BlendBatch routes."""

from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    not_found, invalid_transition, business,
    ERR_BLENDER_OUT_OF_SERVICE, ERR_PERMIT_NOT_ACTIVE, ERR_BLENDER_WINDOW_CONFLICT,
    ERR_BLENDER_FORM_MISMATCH,
)
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list, iso8601_ms
from services.core import scaffold_entity, touch, public, lazy_permit
from services.orders import complete_batch, CLEANUP_BUFFER_MINUTES
from util import (
    get_body, require, optional, reject_unknown, as_string, as_enum, as_number,
    parse_pagination, paginate, parse_instant, D,
)

bp = Blueprint("blenders", __name__)

FORM_SUPPORT = {"DRY", "LIQUID", "BOTH"}


def _get_blender(bid):
    x = db.blenders.get(bid)
    if x is None:
        raise not_found("Blender not found")
    return x


def _get_batch(bid):
    x = db.blend_batches.get(bid)
    if x is None:
        raise not_found("Batch not found")
    return x


def _get_order(oid):
    x = db.blend_orders.get(oid)
    if x is None:
        raise not_found("Blend order not found")
    return x


def _active_blender_site_permit(site_code):
    for p in db.permits.values():
        if p["permit_type"] != "BLENDER_SITE" or p["site_code"] != site_code:
            continue
        lazy_permit(p)
        if p["status"] == "ACTIVE":
            return p
    return None


# ---------------------------------------------------------------------------
# Blenders
# ---------------------------------------------------------------------------

@bp.post("/agronomy/blenders")
def create_blender():
    require_roles("PlantOperator", "BranchAdmin")
    body = get_body()
    reject_unknown(body, {"name", "site_code", "capacity_tons_per_hour", "form_supported"})
    name = as_string(require(body, "name"), "name")
    site_code = as_string(require(body, "site_code"), "site_code")
    capacity = as_number(require(body, "capacity_tons_per_hour"), "capacity_tons_per_hour",
                         minimum=0, exclusive_min=True)
    form_supported = as_enum(require(body, "form_supported"), "form_supported", FORM_SUPPORT)
    blender = scaffold_entity(db.blenders, {
        "name": name,
        "site_code": site_code,
        "capacity_tons_per_hour": float(capacity),
        "form_supported": form_supported,
        "status": "ACTIVE",
    })
    return success_object(public(blender), 201)


@bp.get("/agronomy/blenders")
def list_blenders():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.blenders.values())
    if "site_code" in request.args:
        items = [b for b in items if b["site_code"] == request.args["site_code"]]
    if "status" in request.args:
        items = [b for b in items if b["status"] == request.args["status"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/blenders/<blenderId>")
def get_blender(blenderId):
    require_roles(*ALL_ROLES)
    blender = _get_blender(blenderId)
    return success_object(public(blender))


@bp.post("/agronomy/blenders/<blenderId>/out-of-service")
def blender_out_of_service(blenderId):
    require_roles("PlantOperator")
    blender = _get_blender(blenderId)
    if blender["status"] != "ACTIVE":
        raise invalid_transition("Blender not ACTIVE")
    blender["status"] = "OUT_OF_SERVICE"
    touch(blender)
    return success_object(public(blender))


@bp.post("/agronomy/blenders/<blenderId>/return-to-service")
def blender_return_to_service(blenderId):
    require_roles("PlantOperator")
    blender = _get_blender(blenderId)
    if blender["status"] != "OUT_OF_SERVICE":
        raise invalid_transition("Blender not OUT_OF_SERVICE")
    if _active_blender_site_permit(blender["site_code"]) is None:
        raise business(ERR_PERMIT_NOT_ACTIVE, 422, "No ACTIVE BLENDER_SITE permit for site")
    blender["status"] = "ACTIVE"
    touch(blender)
    return success_object(public(blender))


# ---------------------------------------------------------------------------
# Batches
# ---------------------------------------------------------------------------

@bp.post("/agronomy/blend-orders/<orderId>/batches")
def create_batch(orderId):
    require_roles("PlantOperator")
    order = _get_order(orderId)
    body = get_body()
    reject_unknown(body, {"blender_id", "scheduled_start", "scheduled_end"})
    blender_id = require(body, "blender_id")
    start = parse_instant(require(body, "scheduled_start"), "scheduled_start")
    end = parse_instant(require(body, "scheduled_end"), "scheduled_end")
    if end <= start:
        from errors import validation
        raise validation("scheduled_end must be later than scheduled_start")
    blender = db.blenders.get(blender_id)
    if blender is None:
        raise not_found("Blender not found")

    # state gates: order BOOKED + payment cross-dimension
    if order["fulfillment_status"] != "BOOKED" or \
            order["payment_status"] not in ("PREPAY_APPLIED", "CREDIT_APPROVED"):
        raise invalid_transition("Order not BOOKED with a committed payment posture")
    if blender["status"] != "ACTIVE":
        raise business(ERR_BLENDER_OUT_OF_SERVICE, 409, "Blender out of service")
    if _active_blender_site_permit(blender["site_code"]) is None:
        raise business(ERR_PERMIT_NOT_ACTIVE, 422, "No ACTIVE BLENDER_SITE permit for site")
    # form coverage
    for line in db.blend_lines.values():
        if line["blend_order_id"] != order["id"]:
            continue
        product = db.products[line["product_id"]]
        if blender["form_supported"] != "BOTH" and product["form"] != blender["form_supported"]:
            raise business(ERR_BLENDER_FORM_MISMATCH, 422,
                           "Blender does not support a line product's form")
    # window conflict: closed occupation windows plus a 30-minute cleanup
    # buffer. Boundary semantics per PRD §3.5: a new batch starting exactly at
    # an existing batch's end is REJECTED (buffer not honored); a new batch
    # starting exactly existing.end + buffer is ADMITTED (exact boundary).
    # Rejection predicate: new.start < existing.end + buffer AND
    # existing.start < new.end + buffer.
    buf = timedelta(minutes=CLEANUP_BUFFER_MINUTES)
    for other in db.blend_batches.values():
        if other["blender_id"] != blender["id"] or other["status"] == "VOIDED":
            continue
        if start < other["_scheduled_end"] + buf and other["_scheduled_start"] < end + buf:
            raise business(ERR_BLENDER_WINDOW_CONFLICT, 409, "Blender window conflict")

    batch = scaffold_entity(db.blend_batches, {
        "blend_order_id": order["id"],
        "blender_id": blender["id"],
        "scheduled_start": iso8601_ms(start),
        "scheduled_end": iso8601_ms(end),
        "void_reason": None,
        "status": "SCHEDULED",
    })
    batch["_scheduled_start"] = start
    batch["_scheduled_end"] = end
    order["fulfillment_status"] = "SCHEDULED"
    touch(order)
    return success_object(public(batch), 201)


@bp.get("/agronomy/blend-orders/<orderId>/batches")
def list_order_batches(orderId):
    require_roles(*ALL_ROLES)
    order = _get_order(orderId)
    from middleware import check_grower_ownership
    check_grower_ownership(order["grower_id"])
    limit, offset = parse_pagination()
    items = [b for b in db.blend_batches.values() if b["blend_order_id"] == order["id"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.get("/agronomy/blend-batches/<batchId>")
def get_batch(batchId):
    require_roles(*ALL_ROLES)
    batch = _get_batch(batchId)
    return success_object(public(batch))


@bp.get("/agronomy/blend-batches")
def list_batches():
    require_roles(*ALL_ROLES)
    limit, offset = parse_pagination()
    items = list(db.blend_batches.values())
    if "blender_id" in request.args:
        items = [b for b in items if b["blender_id"] == request.args["blender_id"]]
    if "status" in request.args:
        items = [b for b in items if b["status"] == request.args["status"]]
    items.sort(key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    return success_list([public(x) for x in paginate(items, limit, offset)], limit, offset, total)


@bp.post("/agronomy/blend-batches/<batchId>/start")
def start_batch(batchId):
    require_roles("PlantOperator")
    batch = _get_batch(batchId)
    if batch["status"] != "SCHEDULED":
        raise invalid_transition("Batch not SCHEDULED")
    blender = db.blenders[batch["blender_id"]]
    if blender["status"] != "ACTIVE":
        raise business(ERR_BLENDER_OUT_OF_SERVICE, 409, "Blender out of service")
    if _active_blender_site_permit(blender["site_code"]) is None:
        raise business(ERR_PERMIT_NOT_ACTIVE, 422, "No ACTIVE BLENDER_SITE permit for site")
    batch["status"] = "IN_PROGRESS"
    touch(batch)
    return success_object(public(batch))


@bp.post("/agronomy/blend-batches/<batchId>/complete")
def complete(batchId):
    require_roles("PlantOperator")
    batch = _get_batch(batchId)
    body = get_body()
    reject_unknown(body, {"actuals"})
    actuals = require(body, "actuals")
    if batch["status"] != "IN_PROGRESS":
        raise invalid_transition("Batch not IN_PROGRESS")
    complete_batch(batch, actuals)
    return success_object(public(batch))


@bp.post("/agronomy/blend-batches/<batchId>/void")
def void_batch(batchId):
    require_roles("PlantOperator")
    batch = _get_batch(batchId)
    body = get_body()
    reject_unknown(body, {"reason"})
    reason = optional(body, "reason", None)
    if batch["status"] != "SCHEDULED":
        raise invalid_transition("Batch not SCHEDULED")
    batch["status"] = "VOIDED"
    batch["void_reason"] = reason if reason else "VOIDED"
    touch(batch)
    order = db.blend_orders.get(batch["blend_order_id"])
    if order is not None and order["fulfillment_status"] == "SCHEDULED":
        order["fulfillment_status"] = "BOOKED"
        touch(order)
    return success_object(public(batch))
