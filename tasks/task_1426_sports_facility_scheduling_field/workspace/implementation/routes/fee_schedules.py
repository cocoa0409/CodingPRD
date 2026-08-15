"""Fee schedule routes: create, read, publish (PRD 3.3)."""

from datetime import timedelta

from flask import Blueprint

import errors
import util
import clock
from db import store
from middleware import require_roles, ANY_ROLE
from response import success_object
from services import core

bp = Blueprint("fee_schedules", __name__)


@bp.post("/fee-schedules")
def create_fee_schedule():
    require_roles("AthleticsAdmin")
    body = util.get_json_body()
    name = util.require_str(body, "name")
    effective_from = util.require_iso(body, "effective_from")
    hourly_resident = util.require_int(body, "hourly_resident_cents", min_v=0)
    hourly_nonresident = util.require_int(body, "hourly_nonresident_cents", min_v=0)
    hourly_commercial = util.require_int(body, "hourly_commercial_cents", min_v=0)
    lights_block = util.require_int(body, "lights_block_cents", min_v=0)
    nonresident_pct = util.require_int(body, "nonresident_surcharge_pct", min_v=0, max_v=100)
    commercial_pct = util.require_int(body, "commercial_surcharge_pct", min_v=0, max_v=100)
    tournament_day = util.require_int(body, "tournament_day_cents", min_v=0)
    tournament_min = util.require_int(body, "tournament_day_min_minutes", min_v=60)
    deposit_pct = util.require_int(body, "deposit_pct", min_v=1, max_v=100)
    min_deposit = util.require_int(body, "min_deposit_cents", min_v=0)

    from db import iso_from_dt
    schedule = util.new_entity({
        "name": name,
        "effective_from": iso_from_dt(effective_from),
        "status": "DRAFT",
        "hourly_resident_cents": hourly_resident,
        "hourly_nonresident_cents": hourly_nonresident,
        "hourly_commercial_cents": hourly_commercial,
        "lights_block_cents": lights_block,
        "nonresident_surcharge_pct": nonresident_pct,
        "commercial_surcharge_pct": commercial_pct,
        "tournament_day_cents": tournament_day,
        "tournament_day_min_minutes": tournament_min,
        "deposit_pct": deposit_pct,
        "min_deposit_cents": min_deposit,
    })
    store.fee_schedules[schedule["id"]] = schedule
    return success_object(schedule, 201)


@bp.get("/fee-schedules/<sid>")
def get_fee_schedule(sid):
    require_roles(*ANY_ROLE)
    return success_object(core.get_fee_schedule(sid))


@bp.post("/fee-schedules/<sid>/publish")
def publish_fee_schedule(sid):
    require_roles("AthleticsAdmin")
    schedule = core.get_fee_schedule(sid)
    if schedule["status"] != "DRAFT":
        raise errors.ApiError(errors.ERR_INVALID_SCHEDULE_STATE,
                              "FeeSchedule must be DRAFT to publish", 409)
    eff = util.parse_iso(schedule["effective_from"], "effective_from")
    if eff.date() > clock.now().date() + timedelta(days=365):
        raise errors.ApiError(
            errors.ERR_INVALID_SCHEDULE_STATE,
            "effective_from is more than 365 days beyond the current logical date", 409)

    # At most one PUBLISHED schedule at any moment: supersede the prior one.
    for s in store.fee_schedules.values():
        if s["status"] == "PUBLISHED":
            s["status"] = "SUPERSEDED"
            util.touch(s)

    schedule["status"] = "PUBLISHED"
    util.touch(schedule)
    return success_object(schedule)
