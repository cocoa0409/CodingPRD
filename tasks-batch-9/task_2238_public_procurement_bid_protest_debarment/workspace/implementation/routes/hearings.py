"""The protest-hearing machine: convene, continue, conclude (PRD §3.8)."""

from flask import Blueprint

import calc
import serializers
import services
import store
import validation as v
from errors import ApiError
from util import whole_minutes

bp = Blueprint("hearings", __name__)


@bp.get("/procurement/hearings/<hearing_id>")
@v.endpoint(v.ALL_ROLES)
def read_hearing(hearing_id):
    return ("obj", services.must("hearings", hearing_id), serializers.hearing, 200)


@bp.post("/procurement/hearings/<hearing_id>/convene")
@v.endpoint(["HearingOfficer"])
def convene(hearing_id):
    hearing = services.must("hearings", hearing_id)
    protest = services.must("protests", hearing["protest_id"])

    if hearing["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_HEARING_STATE")
    if store.now() < hearing["scheduled_start_utc"]:
        raise ApiError("ERR_HEARING_NOT_YET_STARTED")
    if protest["record_item_count"] < 1:
        raise ApiError("ERR_AGENCY_RECORD_INCOMPLETE")

    v.set_field(hearing, "status", "CONVENED")
    v.set_field(hearing, "convened_at_utc", store.now())
    v.touch(hearing)
    return ("obj", hearing, serializers.hearing, 200)


@bp.post("/procurement/hearings/<hearing_id>/continue")
@v.endpoint(["HearingOfficer"])
def continue_hearing(hearing_id):
    data = v.body()
    start = v.req_dt(data, "scheduled_start_utc")
    end = v.req_dt(data, "scheduled_end_utc")
    room_code = v.req_str(data, "room_code")
    v.req_str(data, "continuance_reason")
    if whole_minutes(start, end) is None:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "the hearing window must end strictly after it starts and span a whole "
            "number of minutes",
        )

    hearing = services.must("hearings", hearing_id)
    if hearing["status"] != "CONVENED":
        raise ApiError("ERR_INVALID_HEARING_STATE")

    services.check_hearing_capacity(
        hearing["id"], hearing["hearing_officer_user_id"], start, end, room_code
    )

    if hearing["continuance_count"] >= calc.MAX_CONTINUANCES:
        raise ApiError("ERR_CONTINUANCE_LIMIT_EXCEEDED")

    v.set_field(hearing, "scheduled_start_utc", start)
    v.set_field(hearing, "scheduled_end_utc", end)
    v.set_field(hearing, "room_code", room_code)
    v.set_field(hearing, "status", "SCHEDULED")
    v.set_field(hearing, "continuance_count", hearing["continuance_count"] + 1)
    v.set_field(hearing, "convened_at_utc", None)
    v.touch(hearing)
    return ("obj", hearing, serializers.hearing, 200)


@bp.post("/procurement/hearings/<hearing_id>/conclude")
@v.endpoint(["HearingOfficer"])
def conclude(hearing_id):
    hearing = services.must("hearings", hearing_id)
    protest = services.must("protests", hearing["protest_id"])

    if hearing["status"] != "CONVENED":
        raise ApiError("ERR_INVALID_HEARING_STATE")
    if protest["record_item_count"] < 2:
        raise ApiError("ERR_AGENCY_RECORD_INCOMPLETE")

    v.set_field(hearing, "status", "CONCLUDED")
    v.set_field(hearing, "concluded_at_utc", store.now())
    v.set_field(hearing, "record_items_reviewed_count", protest["record_item_count"])
    v.touch(hearing)
    if protest["status"] == "HEARING_SCHEDULED":
        v.set_field(protest, "status", "UNDER_REVIEW")
        v.touch(protest)
    return ("obj", hearing, serializers.hearing, 200)
