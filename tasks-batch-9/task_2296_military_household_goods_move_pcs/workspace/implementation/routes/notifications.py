"""Notification obligations and their dispatch (PRD §2.11, §3.7)."""

from decimal import Decimal

from flask import Blueprint

from db import by_seq, clock, db, touch
from errors import ApiError
from middleware import (
    ROLE_MOVE_COUNSELOR,
    ROLE_PROGRAM_ADMIN,
    ROLE_SERVICE_MEMBER,
    ROLE_TSP_COORDINATOR,
    endpoint,
    require_ownership,
)
from paging import list_response
from response import ok
from serializers import serialize
from services import calculations as calc
from services import ledger
from validation import get_body, req_enum

bp = Blueprint("notifications", __name__)


@bp.get("/shipments/<shipment_id>/notifications")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def list_shipment_notifications(shipment_id):
    shipment = ledger.get_shipment(shipment_id)
    require_ownership(ledger.member_of_shipment(shipment))
    records = by_seq(
        [n for n in db.notifications.values() if n["shipment_id"] == shipment["id"]]
    )
    return list_response(records)


@bp.get("/notifications/<notification_id>")
@endpoint([ROLE_SERVICE_MEMBER, ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def read_notification(notification_id):
    notification = ledger.get_notification(notification_id)
    shipment = db.shipments.get(notification["shipment_id"])
    if shipment is not None:
        require_ownership(ledger.member_of_shipment(shipment))
    return ok(serialize(notification))


@bp.post("/notifications/<notification_id>/dispatch")
@endpoint([ROLE_MOVE_COUNSELOR, ROLE_TSP_COORDINATOR, ROLE_PROGRAM_ADMIN])
def dispatch_notification(notification_id):
    body = get_body()
    channel = req_enum(body, "channel", calc.NOTIFICATION_CHANNELS)

    notification = ledger.get_notification(notification_id)

    if notification["status"] != "PENDING":
        raise ApiError(
            "ERR_INVALID_NOTIFICATION_STATE", "This obligation has already been dispatched."
        )

    sent_at = clock()
    notification["channel"] = channel
    notification["sent_at"] = sent_at
    if sent_at <= notification["due_by"]:
        notification["status"] = "SENT"
        notification["hours_late"] = calc.ZERO
    else:
        elapsed = Decimal(str((sent_at - notification["due_by"]).total_seconds())) / Decimal(3600)
        notification["status"] = "LATE"
        notification["hours_late"] = calc.money(elapsed)
    touch(notification)
    return ok(serialize(notification))
