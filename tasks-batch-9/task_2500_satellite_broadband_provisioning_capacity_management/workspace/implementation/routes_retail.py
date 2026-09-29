"""Subscriber accounts, service orders and the waitlist (PRD 3.3)."""

from flask import Blueprint

import capacity
import serialize
from auth import own_order, own_subscriber_record, roles
from constants import API_PREFIX, ORDER_STATES, WAITLIST_CAP_PER_CELL
from db import db, new_record, ordered, touch
from errors import fail
from response import list_response, object_response
from validators import (
    body_dict,
    filter_enum,
    filter_value,
    pagination,
    paginate,
    req_email,
    req_jurisdiction,
    req_str,
)

bp = Blueprint("retail", __name__, url_prefix=API_PREFIX)


def find_order(order_id):
    record = db.orders.get(order_id)
    if record is None:
        fail("ERR_SERVICE_ORDER_NOT_FOUND", "Service order not found.")
    return record


def find_subscriber(subscriber_id):
    record = db.subscribers.get(subscriber_id)
    if record is None:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "Subscriber not found.")
    return record


# ------------------------------------------------------------- subscribers ----

@bp.post("/subscribers")
@roles("ProvisioningAgent")
def open_account():
    body = body_dict()
    email = req_email(body, "email")
    full_name = req_str(body, "full_name", 1, 200)
    jurisdiction_code = req_jurisdiction(body, "jurisdiction_code")

    for existing in db.subscribers.values():
        if existing["email"] == email:
            fail("ERR_INVALID_REQUEST", "email is already in use.")

    record = new_record()
    record.update(
        {
            "email": email,
            "full_name": full_name,
            "jurisdiction_code": jurisdiction_code,
            "account_state": "PROSPECT",
            "pending_charge_cents": 0,
        }
    )
    db.subscribers[record["id"]] = record
    return object_response(serialize.subscriber(record), 201)


@bp.get("/subscribers/<subscriber_id>")
@roles("ProvisioningAgent", "ComplianceOfficer", "Subscriber")
def read_subscriber(subscriber_id):
    own_subscriber_record(subscriber_id)
    return object_response(serialize.subscriber(find_subscriber(subscriber_id)))


# ----------------------------------------------------------- service orders ---

@bp.post("/service-orders")
@roles("ProvisioningAgent")
def file_order():
    body = body_dict()
    subscriber_id = req_str(body, "subscriber_id", 1, 100)
    cell_id = req_str(body, "service_cell_id", 1, 100)
    plan_id = req_str(body, "requested_plan_id", 1, 100)

    subscriber = db.subscribers.get(subscriber_id)
    if subscriber is None:
        fail("ERR_SUBSCRIBER_NOT_FOUND", "Subscriber not found.")
    cell = db.cells.get(cell_id)
    if cell is None:
        fail("ERR_SERVICE_CELL_NOT_FOUND", "Service cell not found.")
    if plan_id not in db.plans:
        fail("ERR_SERVICE_PLAN_NOT_FOUND", "Service plan not found.")

    beam = capacity.beam_of_cell(cell)

    # The lazy-expiry sweep cannot change the admission figure (the figure already
    # discounts expired holds) nor the waitlist depth, so both rejections are
    # evaluated first and a refused filing leaves no trace behind.
    admits = capacity.admission_free(cell) >= 1
    if not admits and capacity.waitlist_depth(cell) >= WAITLIST_CAP_PER_CELL:
        fail("ERR_WAITLIST_CLOSED", "The cell's waitlist is at capacity.")
    if beam is None or beam["beam_state"] != "ACTIVE":
        fail("ERR_BEAM_SUSPENDED", "The governing beam is out of service.")

    capacity.expire_reservations(cell)

    record = new_record()
    record.update(
        {
            "subscriber_id": subscriber_id,
            "service_cell_id": cell_id,
            "requested_plan_id": plan_id,
            "order_state": "PENDING_DETERMINATION",
            "reservation_expires_at": None,
            "waitlist_priority_score": None,
            "promoted_at": None,
            "cancel_reason": None,
        }
    )
    db.orders[record["id"]] = record

    if capacity.admission_free(cell) >= 1:
        record["order_state"] = "RESERVED"
        record["reservation_expires_at"] = capacity.reservation_deadline()
    else:
        record["order_state"] = "WAITLISTED"
        record["waitlist_priority_score"] = capacity.waitlist_priority_score(record)
        if subscriber["account_state"] == "PROSPECT":
            subscriber["account_state"] = "WAITLISTED"
            touch(subscriber)

    touch(cell)
    return object_response(serialize.service_order(record), 201)


@bp.get("/service-orders/<order_id>")
@roles("ProvisioningAgent", "Subscriber")
def read_order(order_id):
    own_order(order_id)
    return object_response(serialize.service_order(find_order(order_id)))


@bp.get("/service-orders")
@roles("ProvisioningAgent", "NetworkOpsEngineer", "Subscriber")
def list_orders():
    limit, offset = pagination()
    subscriber_id = filter_value("subscriber_id")
    cell_id = filter_value("service_cell_id")
    plan_id = filter_value("requested_plan_id")
    state = filter_enum("order_state", ORDER_STATES)

    records = ordered(list(db.orders.values()))
    if subscriber_id is not None:
        records = [r for r in records if r["subscriber_id"] == subscriber_id]
    if cell_id is not None:
        records = [r for r in records if r["service_cell_id"] == cell_id]
    if plan_id is not None:
        records = [r for r in records if r["requested_plan_id"] == plan_id]
    if state is not None:
        records = [r for r in records if r["order_state"] == state]

    page = paginate(records, limit, offset)
    return list_response(
        serialize.collection(page, serialize.service_order), limit, offset, len(records)
    )


@bp.post("/service-orders/<order_id>/cancel")
@roles("ProvisioningAgent", "Subscriber")
def cancel_order(order_id):
    own_order(order_id)
    body = body_dict()
    cancel_reason = req_str(body, "cancel_reason", 1, 500)

    record = find_order(order_id)
    state = record["order_state"]
    if state not in ("RESERVED", "WAITLISTED"):
        fail(
            "ERR_ORDER_STATE_INVALID",
            "Cancellation requires order_state RESERVED or WAITLISTED.",
        )

    cell = db.cells.get(record["service_cell_id"])
    record["order_state"] = "CANCELLED"
    record["cancel_reason"] = cancel_reason

    if state == "RESERVED":
        record["reservation_expires_at"] = None
        touch(record)
        if cell is not None:
            touch(cell)
            capacity.run_promotion(cell)
    else:
        touch(record)
        subscriber = db.subscribers.get(record["subscriber_id"])
        if subscriber is not None and subscriber["account_state"] == "WAITLISTED":
            still_waiting = any(
                o["subscriber_id"] == subscriber["id"] and o["order_state"] == "WAITLISTED"
                for o in db.orders.values()
            )
            if not still_waiting:
                subscriber["account_state"] = "PROSPECT"
                touch(subscriber)
        if cell is not None:
            touch(cell)

    return object_response(serialize.service_order(record))
