"""BrokerSearchRecord endpoints (PRD §3.2)."""

from __future__ import annotations

from flask import Blueprint

import db
from errors import (
    raise_err,
    ERR_BROKER_SEARCH_ALREADY_RESPONDED,
    ERR_BROKER_SEARCH_NOT_FOUND,
    ERR_DUPLICATE_BROKER_CODE,
    ERR_INVALID_MEETING_STATE,
    ERR_INVALID_REQUEST,
    ERR_MEETING_NOT_FOUND,
)
from middleware import require_roles
from response import success_object, success_list
from services.serializers import serialize, serialize_list
from util import (
    apply_filters,
    get_json_body,
    paginate,
    parse_pagination,
    require_field,
    require_string,
    sort_by_created_at,
)

bp = Blueprint("broker_searches", __name__)


def get_broker_search_or_404(record_id: str) -> dict:
    record = db.broker_searches.get(record_id)
    if record is None:
        raise_err(ERR_BROKER_SEARCH_NOT_FOUND, "BrokerSearchRecord id does not exist")
    return record


@bp.route("/proxy/broker-searches", methods=["POST"])
@require_roles("TransferAgent")
def create_broker_search(_user_id: str, _role: str):
    body = get_json_body()
    meeting_id = require_field(body, "meeting_id")
    meeting = db.meetings.get(meeting_id)
    if meeting is None:
        raise_err(ERR_MEETING_NOT_FOUND, "Meeting id does not exist")
    if meeting["status"] not in ("RECORD_DATE_LOCKED", "MATERIALS_DISTRIBUTED"):
        raise_err(
            ERR_INVALID_MEETING_STATE,
            "Broker search requires meeting RECORD_DATE_LOCKED or MATERIALS_DISTRIBUTED",
        )

    broker_code = require_string(body, "broker_code")
    if any(
        b["meeting_id"] == meeting_id and b["broker_code"] == broker_code
        for b in db.broker_searches.values()
    ):
        raise_err(ERR_DUPLICATE_BROKER_CODE, "broker_code already exists within the meeting")

    broker_name = require_string(body, "broker_name")

    record = {
        "meeting_id": meeting_id,
        "broker_code": broker_code,
        "broker_name": broker_name,
        "status": "REQUESTED",
        "shares_reported": None,
    }
    db.stamp_new(record)
    db.broker_searches[record["id"]] = record
    return success_object(serialize(record), 201)


@bp.route("/proxy/broker-searches", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection", "Broker")
def list_broker_searches(_user_id: str, _role: str):
    limit, offset = parse_pagination()
    items = sort_by_created_at(list(db.broker_searches.values()))
    items = apply_filters(items, ["meeting_id", "status"])
    page, total = paginate(items, limit, offset)
    return success_list(serialize_list(page), limit, offset, total)


@bp.route("/proxy/broker-searches/<record_id>", methods=["GET"])
@require_roles("ProxyAdministrator", "TransferAgent", "InspectorOfElection", "Broker")
def get_broker_search(record_id: str, _user_id: str, _role: str):
    return success_object(serialize(get_broker_search_or_404(record_id)))


@bp.route("/proxy/broker-searches/<record_id>/respond", methods=["POST"])
@require_roles("Broker")
def respond_broker_search(record_id: str, _user_id: str, _role: str):
    record = get_broker_search_or_404(record_id)
    if record["status"] != "REQUESTED":
        raise_err(
            ERR_BROKER_SEARCH_ALREADY_RESPONDED,
            "Broker search record has already been answered",
        )
    body = get_json_body()
    shares_reported = require_field(body, "shares_reported")
    if (
        isinstance(shares_reported, bool)
        or not isinstance(shares_reported, int)
        or shares_reported < 0
    ):
        raise_err(ERR_INVALID_REQUEST, "shares_reported must be an integer >= 0")
    record["shares_reported"] = shares_reported
    record["status"] = "RESPONDED"
    db.touch(record)
    return success_object(serialize(record))
