"""Consumer notification channels (PRD 3.7)."""

from flask import Blueprint

import auth
import lookups
import responses
import shapes
import store
from errors import raise_error

bp = Blueprint("notices", __name__)

CHANNELS = ("DIRECT_NOTICE", "PRESS_RELEASE", "REGISTRATION_CARD", "WEB_POSTING")
NOTICE_STATUSES = ("SCHEDULED", "RELEASED", "SUPERSEDED")

ROLES = ("ProgramAdmin", "ComplianceOfficer", "SafetyDirector")


@bp.route("/consumer-notices/<notice_id>", methods=["GET"])
def get_notice(notice_id):
    auth.authorize(*ROLES)
    return responses.object_response(lookups.find("consumer_notice", notice_id))


@bp.route("/consumer-notices", methods=["GET"])
def list_notices():
    auth.authorize(*ROLES)
    limit, offset = shapes.pagination()
    recall_id = shapes.q_str("recall_id")
    channel = shapes.q_enum("channel", CHANNELS)
    status = shapes.q_enum("status", NOTICE_STATUSES)

    def keep(row):
        if recall_id is not None and row["recall_id"] != recall_id:
            return False
        if channel is not None and row["channel"] != channel:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return responses.list_response(
        store.ordered(store.consumer_notices, keep), limit, offset)


@bp.route("/consumer-notices", methods=["POST"])
def create_notice():
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    data = shapes.body()
    recall_id = shapes._req(data, "recall_id")
    channel = shapes.req_enum(data, "channel", CHANNELS)
    scheduled_for = shapes.req_ts(data, "scheduled_for")
    reach_count = shapes.req_int(data, "reach_count", minimum=0)
    embargo_until = shapes.opt_ts(data, "embargo_until")
    if embargo_until is shapes.MISSING:
        embargo_until = None

    recall = lookups.find("recall", recall_id)
    if recall["plan_status"] not in ("DRAFT", "SUBMITTED", "APPROVED", "MONITORING"):
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    if channel == "REGISTRATION_CARD":
        model = lookups.model_for_recall(recall)
        ceiling = model["units_registered"] if model is not None else 0
        if reach_count > ceiling:
            raise_error("ERR_REACH_EXCEEDS_REGISTRY")

    row = store.new_row(
        recall_id=recall_id,
        channel=channel,
        scheduled_for=scheduled_for,
        embargo_until=embargo_until,
        reach_count=reach_count,
        status="SCHEDULED",
        released_at=None,
    )
    store.consumer_notices[row["id"]] = row
    return responses.created(row)


@bp.route("/consumer-notices/<notice_id>/release", methods=["POST"])
def release_notice(notice_id):
    auth.authorize("ComplianceOfficer", "SafetyDirector")
    notice = lookups.find("consumer_notice", notice_id)
    shapes.body()

    if notice["status"] != "SCHEDULED":
        raise_error("ERR_NOTICE_STATE_INVALID")

    recall = lookups.maybe("recall", notice["recall_id"])
    plan_status = recall["plan_status"] if recall is not None else None
    if plan_status not in ("APPROVED", "MONITORING"):
        raise_error("ERR_RECALL_PLAN_STATE_INVALID")

    now = store.now_logical()
    if now < notice["scheduled_for"]:
        raise_error("ERR_NOTICE_NOT_DUE")
    if notice["embargo_until"] is not None and now < notice["embargo_until"]:
        raise_error("ERR_EMBARGO_ACTIVE")

    notice["status"] = "RELEASED"
    notice["released_at"] = now
    store.touch(notice)

    def superseded(other):
        return (other["id"] != notice["id"]
                and other["recall_id"] == notice["recall_id"]
                and other["channel"] == notice["channel"]
                and other["status"] == "RELEASED")

    for other in store.ordered(store.consumer_notices, superseded):
        other["status"] = "SUPERSEDED"
        store.touch(other)

    return responses.object_response(notice)
