"""Episodes: ordering, turnaround and the production lock (PRD 3.2, 3.8)."""
from datetime import timedelta

from flask import Blueprint

from db import base_row, db, touch
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, LEGAL_COUNSEL, SHOWRUNNER,
                        STUDIO_EXECUTIVE, WRITER, fetch, require)
from response import created, ok
from routes.common import list_out, match, out
from services import calc, domain
from validation import body_json, filter_value, v_dt, v_enum, v_int

bp = Blueprint("episodes", __name__)

READ_ROLES = (STUDIO_EXECUTIVE, SHOWRUNNER, GUILD_ADMINISTRATOR, LEGAL_COUNSEL, WRITER)


def shoot_window(episode):
    """Closed interval: production start through shoot_days - 1 later (PRD 2.8)."""
    start = episode["production_start_date"]
    return start, start + timedelta(days=episode["shoot_days"] - 1)


@bp.post("/seasons/<season_id>/episodes")
def create_episode(season_id):
    require(STUDIO_EXECUTIVE)
    season = fetch(db.seasons, season_id, "ERR_SEASON_NOT_FOUND")
    agreement = domain.agreement_of(season)
    body = body_json()
    row = base_row()
    number = v_int(body, "episode_number", lo=1)
    if number > season["episode_order"]:
        raise ApiError("ERR_INVALID_REQUEST")
    row["episode_number"] = number
    row["length_format"] = v_enum(body, "length_format", calc.LENGTH_FORMATS)
    row["production_unit"] = v_enum(body, "production_unit", calc.PRODUCTION_UNITS)
    start = v_dt(body, "production_start_date")
    row["shoot_days"] = v_int(body, "shoot_days", 1, 30, required=False, default=8)
    if start < season["production_start_date"]:
        raise ApiError("ERR_INVALID_REQUEST")
    row["season_id"] = season["id"]
    row["production_start_date"] = start
    # 18. structural: production-unit turnaround, then episode-number uniqueness
    buffer_days = timedelta(days=agreement["turnaround_buffer_days"])
    new_start, new_end = shoot_window(row)
    for other in domain.episodes_of(season["id"]):
        if other["production_unit"] != row["production_unit"]:
            continue
        other_start, other_end = shoot_window(other)
        if new_start <= other_end + buffer_days and other_start <= new_end + buffer_days:
            raise ApiError("ERR_PRODUCTION_UNIT_CONFLICT")
    for other in domain.episodes_of(season["id"]):
        if other["episode_number"] == number:
            raise ApiError("ERR_DUPLICATE_EPISODE_NUMBER")
    row["script_readiness"] = "NOT_STARTED"
    row["credit_status"] = "PENDING"
    row["clearance_posture"] = "PENDING"
    row["approved_teleplay_assignment_id"] = None
    row["provisional_credit_shares"] = {}
    row["final_credit_shares"] = {}
    row["determined_credit_string"] = None
    row["locked_at"] = None
    db.episodes[row["id"]] = row
    domain.recompute_coverage(season)
    return created(out(row))


@bp.post("/episodes/<episode_id>/lock-for-production")
def lock_episode(episode_id):
    actor = require(STUDIO_EXECUTIVE, SHOWRUNNER)
    episode = fetch(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")
    season = domain.season_of_episode(episode)
    if actor.role == SHOWRUNNER and season["showrunner_writer_id"] != actor.user_id:
        raise ApiError("ERR_NOT_SEASON_SHOWRUNNER")
    if episode["script_readiness"] == "LOCKED":
        raise ApiError("ERR_EPISODE_ALREADY_LOCKED")
    if episode["script_readiness"] != "READY":
        raise ApiError("ERR_EPISODE_NOT_READY")
    posture = episode["clearance_posture"]
    if posture not in ("CLEARED", "CONDITIONAL_WAIVED"):
        if posture == "BLOCKED":
            raise ApiError("ERR_CLEARANCE_BLOCKED")
        raise ApiError("ERR_CLEARANCE_NOT_CLEARED")
    domain.recompute_coverage(season)
    if season["ready_script_count"] < season["ready_script_target"]:
        raise ApiError("ERR_SCRIPT_COVERAGE_INSUFFICIENT")
    episode["script_readiness"] = "LOCKED"
    episode["locked_at"] = db.now()
    touch(episode)
    domain.recompute_coverage(season)
    return ok(out(episode))


@bp.get("/episodes/<episode_id>")
def get_episode(episode_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.episodes, episode_id, "ERR_EPISODE_NOT_FOUND")))


@bp.get("/episodes")
def list_episodes():
    require(*READ_ROLES)
    rows = list(db.episodes.values())
    rows = match(rows, "season_id", filter_value("season_id"))
    rows = match(rows, "script_readiness", filter_value("script_readiness"))
    rows = match(rows, "credit_status", filter_value("credit_status"))
    rows = match(rows, "clearance_posture", filter_value("clearance_posture"))
    return list_out(rows)
