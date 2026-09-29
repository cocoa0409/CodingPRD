"""Notification batch and delivery-record endpoints."""

from flask import Blueprint

import db
import validation as v
from errors import ApiError
from middleware import (
    COMMUNITY_LIAISON,
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
    roles,
)
from response import object_response
from services import calc, notifications

bp = Blueprint("notifications", __name__)

STAGES = ("ADVANCE_48H", "ADVANCE_24H", "IMMINENT_1H", "ACTIVATION", "RESTORATION")
DELIVERY_STATUSES = ("DELIVERED", "UNREACHABLE")

READ_ROLES = (
    GRID_PLANNER,
    PSPS_DUTY_OFFICER,
    COMMUNITY_LIAISON,
    REGULATORY_REVIEWER,
    TRANSMISSION_ENGINEER,
)


@bp.post("/notification-batches")
@roles(COMMUNITY_LIAISON)
def create_batch():
    body = v.Body()
    event_id = body.string("psps_event_id", 1, None)
    stage = body.enum("stage", STAGES)
    scheduled, scheduled_raw = body.timestamp("scheduled_send_at")

    event = v.psps_event(event_id)

    # Priority 13 - the pre-onset stages must be scheduled before the onset.
    if stage in calc.PRE_ONSET_STAGES and scheduled >= event["forecast_onset_at"]:
        raise ApiError(
            "ERR_NOTIFICATION_WINDOW_INVALID",
            "Stage %s must be scheduled strictly before the event onset." % stage,
        )

    # Priority 14 - somebody must be in scope to notify.
    if int(event["confirmed_scope_count"]) < 1:
        raise ApiError(
            "ERR_NO_CIRCUITS_IN_SCOPE", "The event holds no CONFIRMED scope row."
        )

    row = db.new_row()
    row["psps_event_id"] = event["id"]
    row["stage"] = stage
    db.set_dt(row, "scheduled_send_at", scheduled, scheduled_raw)
    row["status"] = "PENDING"
    db.set_dt(row, "dispatched_at", None)
    row["lead_time_minutes"] = None
    row["target_count"] = 0
    row["delivered_count"] = 0
    row["unreachable_count"] = 0
    db.notification_batches[row["id"]] = row
    return object_response(db.notification_batch_out(row), 201)


@bp.get("/notification-batches/<batch_id>")
@roles(*READ_ROLES)
def get_batch(batch_id):
    return object_response(db.notification_batch_out(v.notification_batch(batch_id)))


@bp.post("/notification-batches/<batch_id>/dispatch")
@roles(COMMUNITY_LIAISON)
def dispatch_batch(batch_id):
    batch = v.notification_batch(batch_id)

    # Priority 8 - the batch's own state.
    if batch["status"] != "PENDING":
        raise ApiError(
            "ERR_BATCH_ALREADY_DISPATCHED",
            "The batch has already settled at %s." % batch["status"],
        )

    event = db.psps_events.get(batch["psps_event_id"])
    notifications.dispatch(batch, event)
    return object_response(db.notification_batch_out(batch))


@bp.get("/notification-records")
@roles(*READ_ROLES)
def list_records():
    batch_id = v.query_string("notification_batch_id")
    customer_id = v.query_string("customer_id")
    delivery_status = v.query_enum("delivery_status", DELIVERY_STATUSES)

    if batch_id is not None:
        v.notification_batch(batch_id)
    if customer_id is not None:
        v.customer(customer_id)

    rows = db.in_order(db.notification_records.values())
    if batch_id is not None:
        rows = [r for r in rows if r["notification_batch_id"] == batch_id]
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if delivery_status is not None:
        rows = [r for r in rows if r["delivery_status"] == delivery_status]
    return v.paged(rows, db.notification_record_out)


@bp.get("/notification-records/<record_id>")
@roles(*READ_ROLES)
def get_record(record_id):
    return object_response(db.notification_record_out(v.notification_record(record_id)))
