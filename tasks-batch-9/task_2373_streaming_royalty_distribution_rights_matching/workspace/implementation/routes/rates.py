"""RateSchedule endpoints (§3.8)."""

from flask import Blueprint

import lookup
import serializers
import validation
from constants import (
    API_PREFIX,
    ROLE_REGULATORY_OFFICER,
    STATUTORY_MIN_REVENUE_SHARE_BPS,
    SUBSCRIPTION_TIERS,
)
from db import db, fmt_dt, now, stamp_new, touch
from errors import ApiError
from middleware import require
from response import created_response, object_response
from services import cascades

bp = Blueprint("rates", __name__, url_prefix=API_PREFIX)


@bp.post("/rate-schedules")
@require(ROLE_REGULATORY_OFFICER)
def create_rate_schedule():
    data = validation.body()
    proceeding_ref = validation.get_string(data, "proceeding_ref", max_len=120)
    territory_code = validation.get_territory(data, "territory_code", allow_world=True)
    subscription_tier = validation.get_enum(
        data, "subscription_tier", SUBSCRIPTION_TIERS)
    revenue_share_bps = validation.get_int(
        data, "revenue_share_bps", minimum=0, maximum=10000)
    per_subscriber_minimum_cents = validation.get_int(
        data, "per_subscriber_minimum_cents", minimum=0)
    mechanical_share_bps = validation.get_int(
        data, "mechanical_share_bps", minimum=0, maximum=10000)
    performance_share_bps = validation.get_int(
        data, "performance_share_bps", minimum=0, maximum=10000)
    statutory_floor = validation.get_int(
        data, "statutory_floor_per_play_millicents", minimum=0)
    effective_from = validation.get_date(data, "effective_from")
    effective_to = validation.get_date(data, "effective_to")
    retroactive = validation.get_bool(data, "retroactive", default=False)

    # Item 19: the schedule window is closed at both ends.
    if effective_to < effective_from:
        raise ApiError("ERR_INVALID_EFFECTIVE_PERIOD")

    # Item 24: the publishing split must be exhaustive.
    if mechanical_share_bps + performance_share_bps != 10000:
        raise ApiError("ERR_RATE_SHARE_SPLIT_INVALID")

    record = {
        "proceeding_ref": proceeding_ref,
        "territory_code": territory_code,
        "subscription_tier": subscription_tier,
        "revenue_share_bps": revenue_share_bps,
        "per_subscriber_minimum_cents": per_subscriber_minimum_cents,
        "mechanical_share_bps": mechanical_share_bps,
        "performance_share_bps": performance_share_bps,
        "statutory_floor_per_play_millicents": statutory_floor,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "retroactive": retroactive,
        "status": "PROPOSED",
        "promulgated_at": None,
    }
    stamp_new(record)
    db.rate_schedules[record["id"]] = record
    return created_response(serializers.rate_schedule(record))


@bp.get("/rate-schedules/<schedule_id>")
@require()
def read_rate_schedule(schedule_id):
    schedule = lookup.rate_schedule(schedule_id)
    return object_response(serializers.rate_schedule(schedule))


@bp.post("/rate-schedules/<schedule_id>/promulgate")
@require(ROLE_REGULATORY_OFFICER)
def promulgate(schedule_id):
    schedule = lookup.rate_schedule(schedule_id)
    data = validation.body()
    supersede_incumbent = validation.get_bool(data, "supersede_incumbent", default=False)

    # Item 13: state.
    if schedule["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_RATE_SCHEDULE_STATE")

    # Item 16: statutory floor ratchet.
    if schedule["revenue_share_bps"] < STATUTORY_MIN_REVENUE_SHARE_BPS:
        raise ApiError("ERR_STATUTORY_RATE_FLOOR_BREACH")
    incumbents = _incumbents(schedule)
    if incumbents:
        highest = max(i["statutory_floor_per_play_millicents"] for i in incumbents)
        if schedule["statutory_floor_per_play_millicents"] < highest:
            raise ApiError("ERR_STATUTORY_RATE_FLOOR_BREACH")

    # Item 23: exclusive occupancy over the closed interval.
    if not supersede_incumbent:
        for other in incumbents:
            if cascades._closed_windows_overlap(other, schedule):
                raise ApiError("ERR_RATE_SCHEDULE_OVERLAP")

    # Item 24: the publishing split is re-verified at promulgation.
    if schedule["mechanical_share_bps"] + schedule["performance_share_bps"] != 10000:
        raise ApiError("ERR_RATE_SHARE_SPLIT_INVALID")

    schedule["status"] = "EFFECTIVE"
    schedule["promulgated_at"] = fmt_dt(now())
    touch(schedule)

    cascades.promulgation_cascade(schedule, supersede_incumbent)
    return object_response(serializers.rate_schedule(schedule))


def _incumbents(schedule):
    return [s for s in db.rate_schedules.values()
            if s["id"] != schedule["id"]
            and s["status"] == "EFFECTIVE"
            and s["territory_code"] == schedule["territory_code"]
            and s["subscription_tier"] == schedule["subscription_tier"]]
