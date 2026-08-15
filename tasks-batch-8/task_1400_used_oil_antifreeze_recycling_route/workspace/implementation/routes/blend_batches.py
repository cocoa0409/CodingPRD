"""BlendBatch endpoints (PRD §3.8)."""

from flask import Blueprint, request

import db
from errors import (
    ApiError,
    ERR_BATCH_NOT_BLENDING,
    ERR_BATCH_NOT_CANCELLABLE,
    ERR_BLEND_BATCH_NOT_FOUND,
    ERR_BATCH_NOT_ON_HOLD,
    ERR_BATCH_NOT_PLANNED,
    ERR_BATCH_NOT_RELEASED,
    ERR_INVALID_REQUEST,
    ERR_PICKUP_TICKET_NOT_FOUND,
    ERR_TICKET_ALREADY_CONSUMED,
    ERR_TICKET_NOT_SETTLED,
)
from middleware import get_body, req_enum, req_int, req_list, req_str, require_roles
from response import success_list, success_object
from services.calc import blend_yield

bp = Blueprint("blend_batches", __name__)

TARGET_PRODUCTS = {"RE_REFINED_BASE_OIL", "RECYCLED_ANTIFREEZE", "FUEL_BLENDING_STOCK"}
READ_ROLES = ("RoutePlanner", "SettlementClerk", "LabTech")


def get_batch_or_404(batch_id):
    batch = db.get("blend_batches", batch_id)
    if batch is None:
        raise ApiError(ERR_BLEND_BATCH_NOT_FOUND, "BlendBatch id not found", 404)
    return batch


@bp.post("/blend-batches")
@require_roles("RoutePlanner")
def create_batch():
    body = get_body()
    batch_code = req_str(body, "batch_code")
    target_product = req_enum(body, "target_product", TARGET_PRODUCTS)
    ticket_ids = req_list(body, "input_pickup_ticket_ids")
    resale_price = req_int(body, "resale_price_cents_per_gal")
    tickets = []
    for tid in ticket_ids:
        if not isinstance(tid, str):
            raise ApiError(ERR_INVALID_REQUEST, "input_pickup_ticket_ids must be an array of ids", 400)
        ticket = db.get("pickup_tickets", tid)
        if ticket is None:
            raise ApiError(ERR_PICKUP_TICKET_NOT_FOUND, "PickupTicket id not found", 404)
        tickets.append(ticket)
    for b in db.all_entities("blend_batches"):
        if b["batch_code"] == batch_code:
            raise ApiError(ERR_INVALID_REQUEST, "batch_code must be unique", 400)
    # planned_estimate variant: optimistic projection (avg_H = 0, no mix penalty)
    v_in, _, planned_output = blend_yield(target_product, tickets, optimistic=True)
    batch = db.create_entity("blend_batches", {
        "batch_code": batch_code,
        "target_product": target_product,
        "input_pickup_ticket_ids": list(ticket_ids),
        "input_gallons_total": v_in,
        "yield_pct": None,
        "output_gallons": None,
        "planned_output_gallons": planned_output,
        "resale_price_cents_per_gal": resale_price,
        "gross_resale_revenue_cents": None,
        "status": "PLANNED",
    })
    return success_object(db.serialize(batch), 201)


@bp.get("/blend-batches")
@require_roles(*READ_ROLES)
def list_batches():
    items = db.all_entities("blend_batches")
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    return success_list([db.serialize(b) for b in db.sorted_created(items)])


@bp.get("/blend-batches/<batchId>")
@require_roles(*READ_ROLES)
def get_batch(batchId):
    return success_object(db.serialize(get_batch_or_404(batchId)))


@bp.post("/blend-batches/<batchId>/start-blending")
@require_roles("RoutePlanner")
def start_blending(batchId):
    batch = get_batch_or_404(batchId)
    if batch["status"] != "PLANNED":
        raise ApiError(ERR_BATCH_NOT_PLANNED, "Start-blending requires PLANNED", 409)
    tickets = [db.get("pickup_tickets", tid) for tid in batch["input_pickup_ticket_ids"]]
    for ticket in tickets:
        if ticket is None:
            raise ApiError(ERR_PICKUP_TICKET_NOT_FOUND, "PickupTicket id not found", 404)
    for ticket in tickets:
        if ticket["payment_status"] != "SETTLED":
            raise ApiError(ERR_TICKET_NOT_SETTLED, "BlendBatch input requires SETTLED", 409)
    for ticket in tickets:
        consumed_by = ticket.get("_consumed_by")
        if consumed_by and consumed_by != batch["id"]:
            other = db.get("blend_batches", consumed_by)
            if other is not None and other["status"] != "CANCELLED":
                raise ApiError(ERR_TICKET_ALREADY_CONSUMED, "Ticket already consumed by an active BlendBatch", 409)
    v_in, yield_pct, output = blend_yield(batch["target_product"], tickets, optimistic=False)
    if v_in < 1:
        raise ApiError(ERR_INVALID_REQUEST, "input_gallons_total must be at least 1 gallon", 400)
    batch["input_gallons_total"] = v_in
    batch["yield_pct"] = yield_pct
    batch["output_gallons"] = output
    batch["gross_resale_revenue_cents"] = output * batch["resale_price_cents_per_gal"]
    batch["status"] = "BLENDING"
    db.touch(batch)
    for ticket in tickets:
        ticket["_consumed_by"] = batch["id"]
        db.touch(ticket)
    return success_object(db.serialize(batch))


@bp.post("/blend-batches/<batchId>/hold")
@require_roles("LabTech")
def hold_batch(batchId):
    batch = get_batch_or_404(batchId)
    if batch["status"] != "BLENDING":
        raise ApiError(ERR_BATCH_NOT_BLENDING, "Hold requires BLENDING", 409)
    batch["status"] = "QUALITY_HOLD"
    db.touch(batch)
    return success_object(db.serialize(batch))


@bp.post("/blend-batches/<batchId>/resume")
@require_roles("LabTech")
def resume_batch(batchId):
    batch = get_batch_or_404(batchId)
    if batch["status"] != "QUALITY_HOLD":
        raise ApiError(ERR_BATCH_NOT_ON_HOLD, "Resume requires QUALITY_HOLD", 409)
    batch["status"] = "BLENDING"
    db.touch(batch)
    return success_object(db.serialize(batch))


@bp.post("/blend-batches/<batchId>/release")
@require_roles("LabTech")
def release_batch(batchId):
    batch = get_batch_or_404(batchId)
    if batch["status"] != "BLENDING":
        raise ApiError(ERR_BATCH_NOT_BLENDING, "Release requires BLENDING", 409)
    batch["status"] = "RELEASED_FOR_SALE"
    db.touch(batch)
    return success_object(db.serialize(batch))


@bp.post("/blend-batches/<batchId>/mark-sold")
@require_roles("SettlementClerk")
def mark_sold(batchId):
    batch = get_batch_or_404(batchId)
    if batch["status"] != "RELEASED_FOR_SALE":
        raise ApiError(ERR_BATCH_NOT_RELEASED, "Mark-sold requires RELEASED_FOR_SALE", 409)
    batch["status"] = "SOLD"
    db.touch(batch)
    return success_object(db.serialize(batch))


@bp.post("/blend-batches/<batchId>/cancel")
@require_roles("RoutePlanner")
def cancel_batch(batchId):
    batch = get_batch_or_404(batchId)
    if batch["status"] not in ("PLANNED", "BLENDING"):
        raise ApiError(ERR_BATCH_NOT_CANCELLABLE, "Cancel requires PLANNED or BLENDING", 409)
    batch["status"] = "CANCELLED"
    db.touch(batch)
    # Release consumed tickets so a later batch may consume them.
    for tid in batch["input_pickup_ticket_ids"]:
        ticket = db.get("pickup_tickets", tid)
        if ticket is not None and ticket.get("_consumed_by") == batch["id"]:
            ticket["_consumed_by"] = None
            db.touch(ticket)
    return success_object(db.serialize(batch))
