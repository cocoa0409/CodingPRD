"""Seasons, coverage initialisation and the reschedule cascade (PRD 3.2)."""
from flask import Blueprint

from db import base_row, db
from errors import ApiError
from middleware import (GUILD_ADMINISTRATOR, LEGAL_COUNSEL, SHOWRUNNER,
                        STUDIO_EXECUTIVE, WRITER, fetch, require)
from response import created, ok
from routes.common import list_out, match, out
from services import calc, domain
from validation import body_json, filter_value, raw, v_dt, v_enum, v_int, v_str

bp = Blueprint("seasons", __name__)

READ_ROLES = (STUDIO_EXECUTIVE, SHOWRUNNER, GUILD_ADMINISTRATOR, LEGAL_COUNSEL, WRITER)


@bp.post("/seasons")
def create_season():
    require(STUDIO_EXECUTIVE)
    body = body_json()
    agreement_ref = raw(body, "guild_agreement_id")
    agreement = None
    if agreement_ref is not None:
        agreement = fetch(db.agreements, agreement_ref, "ERR_AGREEMENT_NOT_FOUND")
    showrunner_ref = raw(body, "showrunner_writer_id")
    showrunner = None
    if showrunner_ref is not None:
        showrunner = fetch(db.writers, showrunner_ref, "ERR_WRITER_NOT_FOUND")
    row = base_row()
    if agreement is None or showrunner is None:
        raise ApiError("ERR_INVALID_REQUEST")
    row["guild_agreement_id"] = agreement["id"]
    row["showrunner_writer_id"] = showrunner["id"]
    row["title"] = v_str(body, "title", 1, 200)
    row["episode_order"] = v_int(body, "episode_order", 1, 30)
    row["length_format"] = v_enum(body, "length_format", calc.LENGTH_FORMATS)
    production_start = v_dt(body, "production_start_date")
    window_start = v_dt(body, "staffing_window_start")
    window_end = v_dt(body, "staffing_window_end")
    row["ready_script_target"] = v_int(body, "ready_script_target", 1, 30)
    row["guarantee_application_mode"] = v_enum(
        body, "guarantee_application_mode", calc.GUARANTEE_MODES,
        required=False, default="CHRONOLOGICAL_ON_ACCEPTANCE")
    row["staffing_budget_weekly_cents"] = v_int(body, "staffing_budget_weekly_cents", lo=0)
    row["script_fee_budget_cents"] = v_int(body, "script_fee_budget_cents", lo=0)
    # a season's creative lead must be showrunner-eligible (PRD 3.2)
    if not showrunner["is_showrunner_eligible"]:
        raise ApiError("ERR_INVALID_REQUEST")
    # PRD 2.8: staffing window ordering and the production-start relation
    if window_end < window_start:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    if not production_start > window_end:
        raise ApiError("ERR_INVALID_DATE_RANGE")
    row["production_start_date"] = production_start
    row["staffing_window_start"] = window_start
    row["staffing_window_end"] = window_end
    row["staffing_commitment_weekly_cents"] = 0
    row["script_fee_committed_cents"] = 0
    row["ready_script_count"] = 0
    row["coverage_posture"] = "CRITICAL"
    row["coverage_gap"] = 0
    db.seasons[row["id"]] = row
    domain.recompute_coverage(row)
    return created(out(row))


@bp.post("/seasons/<season_id>/reschedule")
def reschedule(season_id):
    require(STUDIO_EXECUTIVE)
    season = fetch(db.seasons, season_id, "ERR_SEASON_NOT_FOUND")
    body = body_json()
    new_start = v_dt(body, "new_production_start_date")
    expected = v_int(body, "expected_season_version")
    if expected != season["version"]:
        raise ApiError("ERR_STALE_SEASON_VERSION")
    if not new_start > season["staffing_window_end"] or not new_start > db.now():
        raise ApiError("ERR_RESCHEDULE_DATE_INVALID")
    domain.reschedule_season(season, new_start)
    return ok(out(season))


@bp.get("/seasons/<season_id>")
def get_season(season_id):
    require(*READ_ROLES)
    return ok(out(fetch(db.seasons, season_id, "ERR_SEASON_NOT_FOUND")))


@bp.get("/seasons")
def list_seasons():
    require(*READ_ROLES)
    rows = list(db.seasons.values())
    rows = match(rows, "guild_agreement_id", filter_value("guild_agreement_id"))
    rows = match(rows, "showrunner_writer_id", filter_value("showrunner_writer_id"))
    rows = match(rows, "coverage_posture", filter_value("coverage_posture"))
    return list_out(rows)
