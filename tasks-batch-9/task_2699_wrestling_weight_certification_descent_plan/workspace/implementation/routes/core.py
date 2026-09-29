"""Logical clock, seasons, growth allowances, teams and the compliance run."""

from flask import Blueprint

import cascade
import lookups
import serialize
import validate as V
from auth import endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import DB, fmt_date, new_row, parse_date, parse_dt, touch

bp = Blueprint("core", __name__)

SEASON_STATUSES = ("SETUP", "OPEN", "CLOSED")
COMPLIANCE_STATUSES = ("CLEAR", "WATCH", "PROBATION")


def require_open(season):
    if season.get("status") != "OPEN":
        raise ApiError("ERR_SEASON_NOT_OPEN", "The owning season is not OPEN.")


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
@endpoint("StateOffice")
def set_clock():
    body = V.get_body()
    raw = V.req_str(body, "to_iso8601")
    parsed = parse_dt(raw)
    if parsed is None:
        V.bad("Field 'to_iso8601' must be an ISO 8601 UTC instant.")
    DB.clock = parsed
    return ok({})


# --------------------------------------------------------------------------
# seasons
# --------------------------------------------------------------------------

def _weight_classes(body):
    if "weight_classes" not in body or body["weight_classes"] is None:
        return None
    value = body["weight_classes"]
    if not isinstance(value, list) or len(value) == 0:
        V.bad("Field 'weight_classes' must be a non-empty array.")
    ladder = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int):
            if isinstance(item, float) and float(item).is_integer():
                item = int(item)
            else:
                V.bad("Field 'weight_classes' must contain integers.")
        if item <= 0:
            V.bad("Field 'weight_classes' must contain positive integers.")
        ladder.append(int(item))
    for index in range(1, len(ladder)):
        if ladder[index] <= ladder[index - 1]:
            V.bad("Field 'weight_classes' must be distinct and strictly ascending.")
    return ladder


@bp.post("/seasons")
@endpoint("StateOffice")
def create_season():
    body = V.get_body()
    name = V.req_str(body, "name", max_len=120, allow_empty=False)
    start_date = V.req_date(body, "start_date")
    ladder = _weight_classes(body)
    row = new_row()
    row.update({
        "name": name,
        "start_date": fmt_date(start_date),
        "weight_classes": ladder if ladder is not None else
            [106, 113, 120, 126, 132, 138, 144, 150, 157, 165, 175, 190, 215, 285],
        "min_body_fat_pct_male": V.opt_num(
            body, "min_body_fat_pct_male", minimum=0, maximum=30,
            exclusive_min=True, exclusive_max=True, default=7.0),
        "min_body_fat_pct_female": V.opt_num(
            body, "min_body_fat_pct_female", minimum=0, maximum=40,
            exclusive_min=True, exclusive_max=True, default=12.0),
        "hydration_max_specific_gravity": V.opt_num(
            body, "hydration_max_specific_gravity", minimum=1.000, maximum=1.060,
            exclusive_min=True, exclusive_max=True, default=1.025),
        "max_weekly_descent_pct": V.opt_num(
            body, "max_weekly_descent_pct", minimum=0, maximum=3.0,
            exclusive_min=True, default=1.5),
        "assessor_min_training_hours": V.opt_int(
            body, "assessor_min_training_hours", minimum=1, default=8),
        "audit_fail_threshold_pct": V.opt_num(
            body, "audit_fail_threshold_pct", minimum=0,
            exclusive_min=True, default=2.0),
        "audit_min_sample_count": V.opt_int(
            body, "audit_min_sample_count", minimum=1, default=3),
        "max_consecutive_day_allowance_lbs": V.opt_num(
            body, "max_consecutive_day_allowance_lbs", minimum=0, default=2.0),
        "appeal_filing_window_days": V.opt_int(
            body, "appeal_filing_window_days", minimum=1, default=5),
        "max_appeal_retest_rounds": V.opt_int(
            body, "max_appeal_retest_rounds", minimum=1, default=2),
        "assessor_daily_assessment_capacity": V.opt_int(
            body, "assessor_daily_assessment_capacity", minimum=1, default=3),
        "plan_breach_limit": V.opt_int(body, "plan_breach_limit", minimum=1, default=2),
        "status": "SETUP",
    })
    DB.seasons[row["id"]] = row
    return ok(serialize.season(row), 201)


@bp.get("/seasons/<season_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def read_season(season_id):
    return ok(serialize.season(lookups.season(season_id)))


@bp.post("/seasons/<season_id>/status")
@endpoint("StateOffice")
def season_status(season_id):
    season = lookups.season(season_id)
    body = V.get_body()
    target = V.req_enum(body, "status", SEASON_STATUSES)
    current = season.get("status")

    if target == "OPEN":
        if current != "SETUP":
            raise ApiError("ERR_SEASON_INVALID_STATE",
                           "Only a SETUP season may be opened.")
        if not (season.get("weight_classes") or []):
            V.bad("A season cannot be opened with an empty weight_classes ladder.")
        season["status"] = "OPEN"
        touch(season)
    elif target == "CLOSED":
        if current != "OPEN":
            raise ApiError("ERR_SEASON_INVALID_STATE",
                           "Only an OPEN season may be closed.")
        events = lookups.events_of_season(season["id"])
        if any(e.get("status") in ("WEIGH_IN_OPEN", "SEEDED") for e in events):
            raise ApiError("ERR_RESEED_REQUIRED",
                           "An event of this season is mid-weigh-in or awaiting a bracket.")
        season["status"] = "CLOSED"
        touch(season)
        for event in sorted(events, key=lambda e: (e.get("created_at") or "", e.get("_seq") or 0)):
            if event.get("status") in ("SCHEDULED", "WEIGH_IN_CLOSED"):
                event["status"] = "COMPLETED"
                touch(event)
    else:
        raise ApiError("ERR_SEASON_INVALID_STATE",
                       "That season transition is not declared out of '%s'." % current)
    return ok(serialize.season(season))


@bp.post("/seasons/<season_id>/compliance-run")
@endpoint("StateOffice")
def compliance_run(season_id):
    season = lookups.season(season_id)
    require_open(season)
    cascade.compliance_run(season)
    return ok(serialize.season(season))


# --------------------------------------------------------------------------
# growth allowances
# --------------------------------------------------------------------------

@bp.post("/seasons/<season_id>/growth-allowances")
@endpoint("StateOffice")
def create_growth_allowance(season_id):
    season = lookups.season(season_id)
    body = V.get_body()
    effective_date = V.req_date(body, "effective_date")
    allowance_lbs = V.req_num(body, "allowance_lbs", minimum=0, maximum=4.0,
                              exclusive_min=True)
    note = V.opt_str(body, "note")
    require_open(season)
    stamp = fmt_date(effective_date)
    for row in lookups.growth_of_season(season["id"]):
        if row.get("effective_date") == stamp:
            raise ApiError("ERR_GROWTH_ALLOWANCE_DATE_CONFLICT",
                           "An allowance already exists for that effective date.")
    row = new_row(common=False)
    row.update({
        "season_id": season["id"],
        "effective_date": stamp,
        "allowance_lbs": allowance_lbs,
        "note": note,
    })
    DB.growth[row["id"]] = row
    return ok(serialize.growth_allowance(row), 201)


@bp.get("/seasons/<season_id>/growth-allowances")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def list_growth_allowances(season_id):
    season = lookups.season(season_id)
    limit, offset = V.pagination()
    rows = lookups.growth_of_season(season["id"])
    rows.sort(key=lambda r: (r.get("effective_date") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list(
        [serialize.growth_allowance(r) for r in V.window(rows, limit, offset)],
        limit, offset, total,
    )


# --------------------------------------------------------------------------
# teams
# --------------------------------------------------------------------------

@bp.post("/teams")
@endpoint("StateOffice")
def create_team():
    body = V.get_body()
    season = lookups.season(V.req_id_ref(body, "season_id"))
    school_name = V.req_str(body, "school_name", max_len=160, allow_empty=False)
    require_open(season)
    for row in lookups.teams_of_season(season["id"]):
        if row.get("school_name") == school_name:
            raise ApiError("ERR_DUPLICATE_SCHOOL_NAME",
                           "School names must be unique within the season.")
    row = new_row()
    row.update({"season_id": season["id"], "school_name": school_name})
    DB.teams[row["id"]] = row
    return ok(serialize.team(row), 201)


@bp.get("/teams/<team_id>")
@endpoint("StateOffice", "Assessor", "TeamCoach", "WeighInOfficial", "MedicalReviewer")
def read_team(team_id):
    return ok(serialize.team(lookups.team(team_id)))


@bp.get("/seasons/<season_id>/teams")
@endpoint("StateOffice", "Assessor", "TeamCoach", "MedicalReviewer")
def list_teams(season_id):
    season = lookups.season(season_id)
    compliance_status = V.q_enum("compliance_status", COMPLIANCE_STATUSES)
    limit, offset = V.pagination()
    rows = lookups.teams_of_season(season["id"])
    if compliance_status is not None:
        rows = [r for r in rows if serialize.team_posture(r["id"]) == compliance_status]
    rows = sorted(rows, key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    return ok_list(
        [serialize.team(r) for r in V.window(rows, limit, offset)],
        limit, offset, total,
    )
