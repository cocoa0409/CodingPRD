"""Parent notification delivery, retry and acknowledgement (PRD 3.11)."""

from flask import Blueprint

import clock
import config
import envelope
import helpers
import store
from errors import ApiError
from fields import Field
from ladder import Op
from services import serialize

bp = Blueprint("notifications", __name__)


@bp.get("/sbhc/notifications/<id>")
def read_notification(id):
    op = Op("GET /sbhc/notifications/{id}", ["SbhcAdmin", "Registrar", "Guardian"])
    op.path_id("notification", "notifications", id, "ERR_RESOURCE_NOT_FOUND")
    op.run()
    return envelope.ok(serialize.dump(op.get("notification")))


@bp.get("/sbhc/notifications")
def list_notifications():
    op = Op("GET /sbhc/notifications", ["SbhcAdmin", "Registrar", "Guardian"])
    op.paginated()
    op.run()
    rows = store.all_rows("notifications")
    rows = helpers.filter_eq(
        rows,
        op.args,
        {
            "student_id": "student_id",
            "guardian_id": "guardian_id",
            "visit_id": "visit_id",
            "status": "status",
            "event_type": "event_type",
        },
    )
    return helpers.list_response(rows, op)


@bp.post("/sbhc/notifications/<id>/deliver")
def deliver(id):
    op = Op("POST /sbhc/notifications/{id}/deliver", ["SbhcAdmin"])
    op.path_id("notification", "notifications", id, "ERR_RESOURCE_NOT_FOUND")
    op.schema([Field("outcome", "enum", required=True, values=config.DELIVERY_OUTCOMES)])

    def _cap(op):
        # Rung 16 sits ABOVE the state check so the cap error stays observable
        # on a notification already UNDELIVERABLE (PRD 2.6).
        count = op.get("notification")["delivery_attempt_count"]
        if count >= config.MAX_NOTIFICATION_DELIVERY_ATTEMPTS:
            raise ApiError(
                "ERR_DELIVERY_ATTEMPTS_EXHAUSTED",
                "All three delivery attempts have been used.",
            )

    def _state(op):
        if op.get("notification")["status"] not in ("QUEUED", "FAILED"):
            raise ApiError(
                "ERR_INVALID_STATE", "This notification is not open to a delivery attempt."
            )

    op.hook(16, _cap)
    op.hook(17, _state)
    op.run()

    notification = op.get("notification")
    notification["delivery_attempt_count"] = notification["delivery_attempt_count"] + 1
    if op.body["outcome"] == "DELIVERED":
        notification["status"] = "SENT"
        notification["sent_at"] = clock.now_iso()
    else:
        if notification["delivery_attempt_count"] >= config.MAX_NOTIFICATION_DELIVERY_ATTEMPTS:
            notification["status"] = "UNDELIVERABLE"
        else:
            notification["status"] = "FAILED"
    store.touch(notification)
    return envelope.ok(serialize.dump(notification))


@bp.post("/sbhc/notifications/<id>/acknowledge")
def acknowledge(id):
    op = Op("POST /sbhc/notifications/{id}/acknowledge", ["Guardian"])
    op.path_id("notification", "notifications", id, "ERR_RESOURCE_NOT_FOUND")

    def _ownership(op):
        if op.user_id != op.get("notification")["guardian_id"]:
            raise ApiError(
                "ERR_OWNERSHIP_VIOLATION",
                "Only the targeted guardian may acknowledge this notification.",
            )

    def _state(op):
        if op.get("notification")["status"] != "SENT":
            raise ApiError("ERR_INVALID_STATE", "Only a SENT notification may be acknowledged.")

    def _window(op):
        sent_at = clock.parse_datetime(op.get("notification")["sent_at"])
        deadline = clock.add_days(sent_at, config.NOTIFICATION_ACK_WINDOW_DAYS)
        if clock.now_dt() > deadline:
            raise ApiError(
                "ERR_ACK_WINDOW_EXPIRED",
                "The 14-day acknowledgement window has closed.",
            )

    op.hook(11, _ownership)
    op.hook(17, _state)
    op.hook(31, _window)
    op.run()

    notification = op.get("notification")
    notification["status"] = "ACKNOWLEDGED"
    notification["acknowledged_at"] = clock.now_iso()
    store.touch(notification)
    return envelope.ok(serialize.dump(notification))
