"""Shipment carrier-event routes with direction-dependent box cascades."""
from datetime import timedelta

from flask import Blueprint

from domain import create_fee, late_fee_cents, touch
from envelope import ok_object
from errors import invalid_state, not_found
from serializers import serialize_shipment
from store import DB, clock
from timestamps import parse_datetime
from validate import (
    F,
    authenticate,
    authorize,
    body,
    finalize_shape,
    parse_fields,
)

bp = Blueprint("shipments", __name__)

EVENT_TYPES = {"IN_TRANSIT", "DELIVERED", "EXCEPTION", "LOST_IN_TRANSIT"}


def _get_shipment(sid):
    s = DB.shipments.get(sid)
    if s is None:
        raise not_found("ERR_SHIPMENT_NOT_FOUND", "Shipment id does not exist.")
    return s


def _on_outbound_delivered(sh, box, occurred_dt, occurred_raw):
    box["status"] = "DELIVERED"
    box["delivered_at"] = occurred_raw
    box["delivered_at_dt"] = occurred_dt
    box["due_date"] = occurred_dt + timedelta(
        days=box["plan_snapshot"]["rental_period_days"])
    touch(box)


def _on_outbound_lost(sh, box):
    box["status"] = "CANCELLED"
    touch(box)
    for it in DB.box_items.values():
        if it["rotation_box_id"] != box["id"]:
            continue
        copy = DB.copies.get(it["toy_copy_id"])
        if copy is not None and copy["status"] in ("OUT_ON_LOAN", "RESERVED"):
            copy["status"] = "LOST"
            touch(copy)
    sub = DB.subscriptions.get(box["subscription_id"])
    if sub is not None:
        sub["next_cycle_due_at"] = clock() + timedelta(
            days=box["plan_snapshot"]["rotation_cadence_days"])
        touch(sub)


def _on_return_delivered(sh, box, occurred_dt, occurred_raw):
    box["status"] = "RECEIVED"
    box["received_at"] = occurred_raw
    box["received_at_dt"] = occurred_dt
    touch(box)
    for it in DB.box_items.values():
        if it["rotation_box_id"] != box["id"]:
            continue
        copy = DB.copies.get(it["toy_copy_id"])
        if copy is not None and copy["status"] == "OUT_ON_LOAN":
            copy["status"] = "RETURNED"
            touch(copy)
    fee = late_fee_cents(box, occurred_dt)
    if fee > 0:
        create_fee(box["subscription_id"], None, box["id"], "LATE_RETURN", fee)


def _on_return_lost(sh, box):
    box["status"] = "INSPECTED"
    touch(box)
    for it in DB.box_items.values():
        if it["rotation_box_id"] != box["id"]:
            continue
        copy = DB.copies.get(it["toy_copy_id"])
        if it["loan_status"] == "PENDING_RETURN":
            it["loan_status"] = "LOST_REPORTED"
            it["resolution_status"] = "FEE_ASSESSED"
            touch(it)
            cat = DB.catalog_items.get(copy["catalog_item_id"]) if copy else None
            if cat is not None:
                create_fee(
                    box["subscription_id"], it["id"], box["id"],
                    "LOSS", cat["replacement_value_cents"],
                )
        if copy is not None and copy["status"] == "OUT_ON_LOAN":
            copy["status"] = "LOST"
            touch(copy)


@bp.post("/toy-rental/shipments/<sid>/events")
def record_event(sid):
    uid, role = authenticate()
    authorize(role, {"OperationsManager"})
    sh = _get_shipment(sid)
    data = body()
    shape = parse_fields(data, [
        F("event_type", True, "enum", values=EVENT_TYPES),
        F("occurred_at", True, "datetime"),
    ])
    event_type = shape.values.get("event_type")
    occurred_raw = shape.values.get("occurred_at")
    occurred_dt = parse_datetime(occurred_raw) if occurred_raw else None

    # Shipment state machine (priority 5).
    legal = (
        (event_type == "IN_TRANSIT" and sh["status"] in ("LABEL_CREATED", "EXCEPTION"))
        or (event_type == "DELIVERED" and sh["status"] == "IN_TRANSIT")
        or (event_type == "EXCEPTION" and sh["status"] == "IN_TRANSIT")
        or (event_type == "LOST_IN_TRANSIT" and sh["status"] == "IN_TRANSIT")
    )
    if event_type in EVENT_TYPES and not legal:
        raise invalid_state(
            "Event %s is not legal while the shipment is %s."
            % (event_type, sh["status"]))
    finalize_shape(shape)

    sh["events"].append({"event_type": event_type, "occurred_at": occurred_raw})
    sh["status"] = event_type
    touch(sh)

    box = DB.boxes.get(sh["rotation_box_id"])
    if box is not None:
        if sh["direction"] == "OUTBOUND":
            if event_type == "DELIVERED" and box["status"] == "SHIPPED":
                _on_outbound_delivered(sh, box, occurred_dt, occurred_raw)
            elif event_type == "LOST_IN_TRANSIT" and box["status"] == "SHIPPED":
                _on_outbound_lost(sh, box)
        else:  # RETURN
            if event_type == "DELIVERED" and box["status"] == "RETURNING":
                _on_return_delivered(sh, box, occurred_dt, occurred_raw)
            elif event_type == "LOST_IN_TRANSIT" and box["status"] == "RETURNING":
                _on_return_lost(sh, box)
    return ok_object(serialize_shipment(sh))
