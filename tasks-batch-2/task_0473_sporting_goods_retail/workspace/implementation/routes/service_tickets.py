"""Service-ticket routes: open/start/flag-parts/resume/complete/cancel (PRD §3.8, §3.9)."""

from flask import Blueprint, request

import errors
from db import db, new_id, now_ts
from helpers import get_body, parse_pagination, paginate, as_str, as_enum
from middleware import require_roles
from response import success, list_success
from routes.common import get_or_404
from services import serializers, pricing
from services.inventory import find_row, reserve, commit, release

bp = Blueprint("service_tickets", __name__)

SERVICE_TYPES = {"SKATE_SHARPEN", "RACKET_STRING"}


def _touch(rec):
    rec["updated_at"] = now_ts()
    rec["version"] += 1


@bp.route("/service-tickets", methods=["POST"])
@require_roles("Customer", "ServiceTech")
def create_service_ticket():
    body = get_body()
    customer_id = as_str(body, "customer_id", required=True)
    store_id = as_str(body, "store_id", required=True)
    service_type = as_enum(body, "service_type", SERVICE_TYPES, required=True)
    part_sku_id = as_str(body, "part_sku_id", required=False, default=None)

    get_or_404(db.customers, customer_id)
    get_or_404(db.stores, store_id)
    part_store_inventory_id = None
    if part_sku_id is not None:
        get_or_404(db.skus, part_sku_id)
        row = find_row(store_id, part_sku_id)
        part_store_inventory_id = row["id"] if row else None

    ts = now_ts()
    rid = new_id()
    rec = {
        "id": rid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
        "customer_id": customer_id,
        "store_id": store_id,
        "service_type": service_type,
        "part_sku_id": part_sku_id,
        "part_store_inventory_id": part_store_inventory_id,
        "status": "RECEIVED",
        "service_fee_cents": 0,
    }
    db.service_tickets[rid] = rec
    return success(serializers.service_ticket(rec), 201)


@bp.route("/service-tickets/<rid>", methods=["GET"])
@require_roles("PlatformAdmin", "ServiceTech", "Customer", "StoreAssociate")
def get_service_ticket(rid):
    rec = get_or_404(db.service_tickets, rid)
    return success(serializers.service_ticket(rec), 200)


@bp.route("/service-tickets", methods=["GET"])
@require_roles("PlatformAdmin", "ServiceTech", "Customer", "StoreAssociate")
def list_service_tickets():
    limit, offset = parse_pagination()
    customer_id = request.args.get("customer_id")
    store_id = request.args.get("store_id")
    part_sku_id = request.args.get("part_sku_id")
    items = list(db.service_tickets.values())
    if customer_id is not None:
        items = [t for t in items if t["customer_id"] == customer_id]
    if store_id is not None:
        items = [t for t in items if t["store_id"] == store_id]
    if part_sku_id is not None:
        items = [t for t in items if t["part_sku_id"] == part_sku_id]
    page, total = paginate(items, limit, offset)
    return list_success([serializers.service_ticket(t) for t in page], limit, offset, total)


def _part_row(ticket):
    """Return the live stock row for the ticket's part, resolving if needed."""
    if ticket["part_sku_id"] is None:
        return None
    if ticket["part_store_inventory_id"] is not None:
        return db.store_inventory.get(ticket["part_store_inventory_id"])
    row = find_row(ticket["store_id"], ticket["part_sku_id"])
    if row is not None:
        ticket["part_store_inventory_id"] = row["id"]
    return row


@bp.route("/service-tickets/<rid>/start", methods=["POST"])
@require_roles("ServiceTech")
def start_service_ticket(rid):
    ticket = get_or_404(db.service_tickets, rid)
    if ticket["status"] != "RECEIVED":
        raise errors.invalid_state("Ticket is not in RECEIVED state")
    if ticket["part_sku_id"] is not None:
        row = _part_row(ticket)
        if row is None or row["available_qty"] < 1:
            raise errors.ApiError(errors.ERR_INSUFFICIENT_INVENTORY, 409,
                                  "No available part unit to reserve")
        reserve(row, 1)
    ticket["status"] = "IN_PROGRESS"
    _touch(ticket)
    return success(serializers.service_ticket(ticket), 200)


@bp.route("/service-tickets/<rid>/flag-parts", methods=["POST"])
@require_roles("ServiceTech")
def flag_parts_service_ticket(rid):
    ticket = get_or_404(db.service_tickets, rid)
    if ticket["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Ticket is not in IN_PROGRESS state")
    ticket["status"] = "NEEDS_PARTS"
    _touch(ticket)
    return success(serializers.service_ticket(ticket), 200)


@bp.route("/service-tickets/<rid>/resume", methods=["POST"])
@require_roles("ServiceTech")
def resume_service_ticket(rid):
    ticket = get_or_404(db.service_tickets, rid)
    if ticket["status"] != "NEEDS_PARTS":
        raise errors.invalid_state("Ticket is not in NEEDS_PARTS state")
    ticket["status"] = "IN_PROGRESS"
    _touch(ticket)
    return success(serializers.service_ticket(ticket), 200)


@bp.route("/service-tickets/<rid>/complete", methods=["POST"])
@require_roles("ServiceTech")
def complete_service_ticket(rid):
    ticket = get_or_404(db.service_tickets, rid)
    if ticket["status"] != "IN_PROGRESS":
        raise errors.invalid_state("Ticket is not in IN_PROGRESS state")
    if ticket["part_sku_id"] is not None:
        row = _part_row(ticket)
        if row is not None:
            commit(row, 1)
    customer = db.customers[ticket["customer_id"]]
    ticket["service_fee_cents"] = pricing.service_fee(ticket["service_type"], customer["loyalty_tier"])
    ticket["status"] = "COMPLETED"
    _touch(ticket)
    return success(serializers.service_ticket(ticket), 200)


@bp.route("/service-tickets/<rid>/cancel", methods=["POST"])
@require_roles("ServiceTech")
def cancel_service_ticket(rid):
    ticket = get_or_404(db.service_tickets, rid)
    status = ticket["status"]
    if status not in ("RECEIVED", "IN_PROGRESS", "NEEDS_PARTS"):
        raise errors.invalid_state("Ticket cannot be cancelled from its current state")
    if status in ("IN_PROGRESS", "NEEDS_PARTS") and ticket["part_sku_id"] is not None:
        row = _part_row(ticket)
        if row is not None:
            release(row, 1)
    ticket["status"] = "CANCELLED"
    _touch(ticket)
    return success(serializers.service_ticket(ticket), 200)
