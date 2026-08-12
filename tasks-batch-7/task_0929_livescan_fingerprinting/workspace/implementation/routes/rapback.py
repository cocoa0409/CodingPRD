from flask import Blueprint, g, request

import cascades
import constants as C
import derive
import serializers
import validation as V
from envelope import object_response, paginate
from errors import ApiError
from lookups import (agency_of_ori, body_row, check_billing_freeze, check_ori_authority,
                     path_row, require_record_state)
from store import db
from timeutil import add_days

bp = Blueprint("rapback", __name__)


# ------------------------------------------------------------- subscriptions

@bp.post("/livescan/rapback-subscriptions")
def subscribe():
    data = V.body()
    submission = (
        body_row("submissions", data["submission_id"]) if data.get("submission_id") else None
    )
    if submission is None:
        V.bad_request("submission_id is required")

    ori = db.oris[submission["ori_id"]]
    check_billing_freeze(agency_of_ori(ori))
    check_ori_authority(ori)

    if not ori["rapback_authority"]:
        raise ApiError("ERR_RAPBACK_NOT_AUTHORIZED", "the ORI has no rap-back authority")
    if submission["retention_status"] not in ("GRANTED", "PURGE_REQUESTED", "PURGE_DENIED"):
        raise ApiError("ERR_RAPBACK_REQUIRES_RETENTION", "the submission has no granted retention")

    term_start = db.now()
    row = db.create(
        "subscriptions",
        {
            "submission_id": submission["id"],
            "ori_id": ori["id"],
            "term_start": term_start,
            "term_end": add_days(term_start, C.RAPBACK_TERM_DAYS),
            "status": "ACTIVE",
            "renewal_count": 0,
            "notifications_received_count": 0,
            "notifications_routed_count": 0,
            "notifications_voided_count": 0,
        },
    )
    return object_response(serializers.subscription(row), 201)


@bp.get("/livescan/rapback-subscriptions/<id>")
def read_subscription(id):
    return object_response(serializers.subscription(path_row("subscriptions", id)))


@bp.get("/livescan/rapback-subscriptions")
def list_subscriptions():
    rows = list(db.subscriptions.values())
    for field in ("submission_id", "ori_id"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if derive.subscription_status(r) == status]
    return paginate(rows, serializers.subscription)


@bp.post("/livescan/rapback-subscriptions/<id>/renew")
def renew(id):
    subscription = path_row("subscriptions", id)
    ori = db.oris[subscription["ori_id"]]
    check_billing_freeze(agency_of_ori(ori))
    check_ori_authority(ori)

    current = derive.subscription_status(subscription)
    # rung 10 carve-out (b): this rung fires only for LAPSED, CANCELLED and
    # TERMINATED; a still-ACTIVE subscription outside its window is rung 32's.
    require_record_state(
        current not in ("LAPSED", "CANCELLED", "TERMINATED"), "subscription is %s" % current
    )
    if not ori["rapback_authority"]:
        raise ApiError("ERR_RAPBACK_NOT_AUTHORIZED", "the ORI has no rap-back authority")
    if current != "RENEWAL_DUE":
        raise ApiError("ERR_RENEWAL_WINDOW_CLOSED", "the subscription is outside its window")

    term_start = db.now()
    subscription["term_start"] = term_start
    subscription["term_end"] = add_days(term_start, C.RAPBACK_TERM_DAYS)
    subscription["renewal_count"] += 1
    subscription["status"] = "ACTIVE"
    db.touch(subscription)
    return object_response(serializers.subscription(subscription))


@bp.post("/livescan/rapback-subscriptions/<id>/cancel")
def cancel_subscription(id):
    subscription = path_row("subscriptions", id)
    current = derive.subscription_status(subscription)
    require_record_state(current in ("ACTIVE", "RENEWAL_DUE"), "subscription is %s" % current)
    subscription["status"] = "CANCELLED"
    db.touch(subscription)
    return object_response(serializers.subscription(subscription))


# ------------------------------------------------------------- notifications

@bp.post("/livescan/rapback-notifications")
def deliver_notification():
    data = V.body()
    ori_code = V.req_string(data, "ori_code")
    subject_tcn = V.req_string(data, "subject_submission_tcn")
    event_type = V.req_string(data, "event_type")
    event_date = V.req_date(data, "event_date")
    V.enum_value("event_type", event_type, C.EVENT_TYPES)

    bound = None
    for subscription in db.subscriptions.values():
        if derive.subscription_status(subscription) not in ("ACTIVE", "RENEWAL_DUE"):
            continue
        submission = db.submissions.get(subscription["submission_id"])
        if submission is None or submission["tcn_full"] != subject_tcn:
            continue
        ori = db.oris.get(subscription["ori_id"])
        if ori is None or ori["ori_code"] != ori_code:
            continue
        bound = subscription
        break

    row = db.create(
        "notifications",
        {
            "subscription_id": bound["id"] if bound else None,
            "ori_code": ori_code,
            "subject_submission_tcn": subject_tcn,
            "event_type": event_type,
            "event_date": event_date,
            "status": "ROUTED" if bound else "ORPHANED",
            "acknowledged_by_user_id": None,
        },
    )
    if bound is not None:
        if cascades.sync_subscription_counters(bound):
            db.touch(bound)
    return object_response(serializers.notification(row), 201)


@bp.get("/livescan/rapback-notifications/<id>")
def read_notification(id):
    return object_response(serializers.notification(path_row("notifications", id)))


@bp.get("/livescan/rapback-notifications")
def list_notifications():
    rows = list(db.notifications.values())
    for field in ("subscription_id", "status", "ori_code"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    return paginate(rows, serializers.notification)


@bp.post("/livescan/rapback-notifications/<id>/acknowledge")
def acknowledge(id):
    notification = path_row("notifications", id)
    if notification["subscription_id"] is None or notification["status"] != "ROUTED":
        raise ApiError("ERR_NOTIFICATION_UNROUTABLE", "notification is %s" % notification["status"])

    notification["status"] = "ACKNOWLEDGED"
    notification["acknowledged_by_user_id"] = g.user_id
    db.touch(notification)
    return object_response(serializers.notification(notification))
