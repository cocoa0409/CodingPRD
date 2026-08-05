"""Spray notices: issuance, delivery retry cycle, and acknowledgement window."""
from datetime import timedelta

from flask import Blueprint

import calc
import domain
import store
import views
from common import (
    ALL_DISTRICT_READERS, ApiError, authenticate, authorize, created,
    get_body, logical_now, ok, ok_list, opt_enum, opt_string, pagination,
    paginate, query_enum, query_str, req_string,
)

bp = Blueprint("notification", __name__)

CHANNELS = ("EMAIL", "SMS", "PHONE")
NOTIFICATION_STATUSES = ("QUEUED", "SENT", "ACKNOWLEDGED", "FAILED", "EXPIRED",
                         "UNDELIVERABLE")
NOTIFICATION_ACTORS = {
    "SEND": "DistrictAdmin",
    "FAIL": "DistrictAdmin",
    "REQUEUE": "DistrictAdmin",
    "ABANDON": "DistrictAdmin",
    "EXPIRE": "DistrictAdmin",
    "ACKNOWLEDGE": "SensitiveSiteOperator",
}

LIVE_STATUSES = ("QUEUED", "SENT", "ACKNOWLEDGED")


@bp.post("/treatment-plans/<plan_id>/notifications")
def create_notification(plan_id):
    authorize(authenticate(), ("DistrictAdmin",))
    plan = store.fetch("TreatmentPlan", plan_id)
    body = get_body()

    site = None
    if body.get("sensitive_site_id") is not None:
        site = store.fetch("SensitiveSite", body.get("sensitive_site_id"))

    req_string(body, "sensitive_site_id", 1)
    channel = opt_enum(body, "channel", CHANNELS, default="EMAIL")

    for existing in store.NOTIFICATIONS.values():
        if existing["treatment_plan_id"] != plan["id"]:
            continue
        if existing["sensitive_site_id"] != site["id"]:
            continue
        if existing["status"] in LIVE_STATUSES:
            raise ApiError("ERR_DUPLICATE_RESOURCE", 409,
                           "A live notice already exists for this plan and site.")

    if plan["status"] not in ("APPROVED", "SCHEDULED"):
        raise domain.invalid_transition(
            "Notices may only be issued for an APPROVED or SCHEDULED plan.")

    if site["service_area_id"] != plan["service_area_id"]:
        raise ApiError("ERR_AREA_MISMATCH", 422,
                       "The protected site belongs to another service area.")

    record = store.new_record()
    record.update({
        "treatment_plan_id": plan["id"],
        "sensitive_site_id": site["id"],
        "channel": channel,
        "status": "QUEUED",
        "attempt_count": 0,
        "sent_at": None,
        "acknowledged_at": None,
        "failure_reason": None,
    })
    store.NOTIFICATIONS[record["id"]] = record
    return created(views.notification_view(record))


@bp.get("/notifications")
def list_notifications():
    authorize(authenticate(), ALL_DISTRICT_READERS + ("SensitiveSiteOperator",))
    limit, offset = pagination()
    plan_id = query_str("treatment_plan_id")
    site_id = query_str("sensitive_site_id")
    status = query_enum("status", NOTIFICATION_STATUSES)
    rows = [n for n in store.NOTIFICATIONS.values()
            if (plan_id is None or n["treatment_plan_id"] == plan_id)
            and (site_id is None or n["sensitive_site_id"] == site_id)
            and (status is None or n["status"] == status)]
    page, total = paginate(store.ordered(rows), limit, offset)
    return ok_list([views.notification_view(r) for r in page], limit, offset, total)


@bp.get("/notifications/<notification_id>")
def get_notification(notification_id):
    authorize(authenticate(), ALL_DISTRICT_READERS + ("SensitiveSiteOperator",))
    notification = store.fetch("Notification", notification_id)
    return ok(views.notification_view(notification))


@bp.post("/notifications/<notification_id>/transitions")
def transition_notification(notification_id):
    actor = authorize(authenticate(), ("DistrictAdmin", "SensitiveSiteOperator"))
    body = get_body()
    action, known = domain.read_action(body, NOTIFICATION_ACTORS)
    domain.enforce_actor(action, known, NOTIFICATION_ACTORS, actor)

    notification = store.fetch("Notification", notification_id)

    if known and action == "ACKNOWLEDGE":
        if actor.user_id != notification["sensitive_site_id"]:
            raise ApiError("ERR_NOT_RESOURCE_OWNER", 403,
                           "Only the notified site operator may acknowledge.")

    domain.require_action_supplied(action)
    failure_reason = None
    if known and action == "FAIL":
        failure_reason = opt_string(body, "failure_reason", 1, 1000)
    domain.require_known_action(action, known)

    plan = store.TREATMENT_PLANS.get(notification["treatment_plan_id"])
    ack_window = timedelta(hours=calc.NOTIFICATION_ACK_WINDOW_HOURS)

    if action == "SEND":
        if notification["status"] != "QUEUED":
            raise domain.invalid_transition("SEND requires a QUEUED notice.")
        if plan is None or plan["status"] not in ("APPROVED", "SCHEDULED"):
            raise domain.invalid_transition(
                "The parent plan must be APPROVED or SCHEDULED.")
        if notification["attempt_count"] >= calc.NOTIFICATION_MAX_ATTEMPTS:
            raise ApiError("ERR_NOTIFICATION_ATTEMPTS_EXHAUSTED", 409,
                           "The notice has exhausted its delivery attempts.")
        notification["attempt_count"] = notification["attempt_count"] + 1
        notification["sent_at"] = logical_now()
        notification["status"] = "SENT"

    elif action == "ACKNOWLEDGE":
        if notification["status"] != "SENT":
            raise domain.invalid_transition("ACKNOWLEDGE requires a SENT notice.")
        if logical_now() > notification["sent_at"] + ack_window:
            raise ApiError("ERR_ACK_WINDOW_EXPIRED", 422,
                           "The acknowledgement window has closed.")
        notification["acknowledged_at"] = logical_now()
        notification["status"] = "ACKNOWLEDGED"

    elif action == "FAIL":
        if notification["status"] != "SENT":
            raise domain.invalid_transition("FAIL requires a SENT notice.")
        notification["failure_reason"] = failure_reason
        notification["status"] = "FAILED"

    elif action == "REQUEUE":
        if notification["status"] != "FAILED":
            raise domain.invalid_transition("REQUEUE requires a FAILED notice.")
        if notification["attempt_count"] >= calc.NOTIFICATION_MAX_ATTEMPTS:
            raise ApiError("ERR_NOTIFICATION_ATTEMPTS_EXHAUSTED", 409,
                           "The notice has exhausted its delivery attempts.")
        notification["status"] = "QUEUED"

    elif action == "ABANDON":
        if notification["status"] != "FAILED":
            raise domain.invalid_transition("ABANDON requires a FAILED notice.")
        notification["status"] = "UNDELIVERABLE"

    else:  # EXPIRE
        if notification["status"] != "SENT":
            raise domain.invalid_transition("EXPIRE requires a SENT notice.")
        if logical_now() <= notification["sent_at"] + ack_window:
            raise ApiError("ERR_ACK_WINDOW_OPEN", 409,
                           "The acknowledgement window is still open.")
        notification["status"] = "EXPIRED"

    store.touch(notification)
    return ok(views.notification_view(notification))
