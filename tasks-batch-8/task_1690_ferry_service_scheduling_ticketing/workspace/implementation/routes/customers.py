"""Customer endpoints (PRD §3.5)."""

from flask import Blueprint, request

from db import db, now_iso
from errors import raise_error, ERR_NOT_FOUND, ERR_DUPLICATE
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from services.serializers import (
    serialize_customer, serialize_booking, serialize_standby_entry,
)

bp = Blueprint("customers", __name__)


@bp.post("/ferry/customers")
def create_customer():
    require_roles("SchedulerAdmin")
    payload = request.get_json(silent=True) or {}
    email = payload.get("email")

    # ERR_DUPLICATE: email unique
    for c in db.customers.values():
        if c["email"] == email:
            raise_error(ERR_DUPLICATE, "email already in use")

    ts = now_iso()
    customer = {
        "id": db.new_id(),
        "full_name": payload.get("full_name"),
        "email": email,
        "fare_class": payload.get("fare_class"),
        "refund_credit_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    db.customers[customer["id"]] = customer
    return success_object(serialize_customer(customer), status=201)


@bp.get("/ferry/customers/<customer_id>")
def get_customer(customer_id):
    require_roles("SchedulerAdmin", "TerminalAgent", "CrewPlanner", "Customer")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    return success_object(serialize_customer(customer))


@bp.get("/ferry/customers/<customer_id>/bookings")
def list_customer_bookings(customer_id):
    require_roles("SchedulerAdmin", "TerminalAgent", "Customer")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    status = request.args.get("status")
    items = [b for b in db.bookings.values()
             if b["customer_id"] == customer_id
             and (status is None or b["status"] == status)]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_booking(b) for b in page], meta)


@bp.get("/ferry/customers/<customer_id>/standby-queue")
def list_customer_standby(customer_id):
    require_roles("SchedulerAdmin", "TerminalAgent", "Customer")
    customer = db.customers.get(customer_id)
    if customer is None:
        raise_error(ERR_NOT_FOUND, "Customer not found")
    status = request.args.get("status")
    items = [e for e in db.standby_entries.values()
             if e["customer_id"] == customer_id
             and (status is None or e["status"] == status)]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    limit, offset = parse_pagination(request.args)
    page, meta = paginate(items, limit, offset)
    return success_list([serialize_standby_entry(e) for e in page], meta)
