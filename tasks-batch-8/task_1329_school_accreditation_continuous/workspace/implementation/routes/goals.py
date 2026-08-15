"""ImprovementGoal and ProgressIndicator endpoints."""
from flask import Blueprint, request

from db import DB, fmt_iso, new_id
from errors import ApiError
from middleware import auth
from response import ok, ok_list
from services import get_or_404, recompute_goal_attainment
from util import (
    as_enum,
    as_num,
    as_str,
    body,
    paginate,
    pagination,
    parse_dt,
    required,
    stamp_new,
    touch,
)

bp = Blueprint("goals", __name__)

DIRECTIONS = {"INCREASE", "DECREASE"}


def goal_view(g):
    return {k: v for k, v in g.items() if not k.startswith("_")}


def indicator_view(i):
    return {k: v for k, v in i.items() if not k.startswith("_")}


@bp.post("/accreditation/terms/<id>/goals")
def create_goal(id):
    auth(["SchoolLeader"])
    term = get_or_404("terms", id, "AccreditationTerm")
    data = body()
    campus_id = data.get("campus_id")  # optional
    standard_id = required(data, "standard_id")
    title = as_str(required(data, "title"), "title")
    baseline_value = as_num(required(data, "baseline_value"), "baseline_value")
    target_value = as_num(required(data, "target_value"), "target_value")
    direction = as_enum(required(data, "direction"), "direction", DIRECTIONS)

    if campus_id is not None:
        campus = DB["campuses"].get(campus_id)
        if campus is None or campus["system_id"] != term["system_id"]:
            raise ApiError(
                "ERR_REFERENTIAL_INTEGRITY",
                422,
                "campus_id does not belong to the term's system",
            )
    standard = DB["standards"].get(standard_id)
    if standard is None:
        raise ApiError("ERR_REFERENTIAL_INTEGRITY", 422, "standard_id does not exist")

    record = {
        "id": new_id(),
        "term_id": id,
        "campus_id": campus_id,
        "standard_id": standard_id,
        "title": title,
        "baseline_value": baseline_value,
        "target_value": target_value,
        "direction": direction,
        "current_value": baseline_value,
        "attainment_pct": 0.0,
        "status": "PROPOSED",
    }
    stamp_new(record, with_version=True)
    DB["goals"][record["id"]] = record
    return ok(goal_view(record), status=201)


@bp.get("/accreditation/terms/<id>/goals")
def list_term_goals(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("terms", id, "AccreditationTerm")
    limit, offset = pagination()
    rows = [g for g in DB["goals"].values() if g["term_id"] == id]
    rows.sort(key=lambda g: g["created_at"])
    campus_id = request.args.get("campus_id")
    status = request.args.get("status")
    if campus_id:
        rows = [r for r in rows if r["campus_id"] == campus_id]
    if status:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([goal_view(r) for r in page], total, limit, offset)


@bp.get("/accreditation/goals/<id>")
def get_goal(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    row = get_or_404("goals", id, "ImprovementGoal")
    return ok(goal_view(row))


@bp.post("/accreditation/goals/<id>/adopt")
def adopt_goal(id):
    auth(["AccreditationOfficer"])
    goal = get_or_404("goals", id, "ImprovementGoal")
    if goal["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE", 409, "Goal must be PROPOSED to adopt")
    term = DB["terms"].get(goal["term_id"])
    if term is None or term["status"] not in ("TERM_ACTIVE", "INTERIM_MONITORING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Owning term must be TERM_ACTIVE or INTERIM_MONITORING",
        )
    if goal["target_value"] == goal["baseline_value"]:
        raise ApiError(
            "ERR_THRESHOLD_NOT_MET",
            422,
            "target_value must differ from baseline_value",
        )
    if goal["direction"] == "INCREASE" and not (
        goal["target_value"] > goal["baseline_value"]
    ):
        raise ApiError(
            "ERR_THRESHOLD_NOT_MET",
            422,
            "INCREASE requires target_value > baseline_value",
        )
    if goal["direction"] == "DECREASE" and not (
        goal["target_value"] < goal["baseline_value"]
    ):
        raise ApiError(
            "ERR_THRESHOLD_NOT_MET",
            422,
            "DECREASE requires target_value < baseline_value",
        )
    goal["status"] = "ADOPTED"
    goal["current_value"] = goal["baseline_value"]
    goal["attainment_pct"] = 0.0
    touch(goal)
    return ok(goal_view(goal))


@bp.post("/accreditation/goals/<id>/indicators")
def create_indicator(id):
    auth(["SchoolLeader"])
    goal = get_or_404("goals", id, "ImprovementGoal")
    data = body()
    measured_at_raw = required(data, "measured_at")
    measured_dt = parse_dt(measured_at_raw, "measured_at")
    value = as_num(required(data, "value"), "value")
    note = data.get("note", "")
    if not isinstance(note, str):
        raise ApiError("ERR_VALIDATION", 400, "note must be a string")
    expected_goal_version = required(data, "expected_goal_version")
    if not isinstance(expected_goal_version, int) or isinstance(expected_goal_version, bool):
        raise ApiError("ERR_VALIDATION", 400, "expected_goal_version must be an integer")

    if goal["status"] not in ("ADOPTED", "MONITORING"):
        raise ApiError(
            "ERR_INVALID_STATE",
            409,
            "Goal must be ADOPTED or MONITORING to accept indicators",
        )
    if goal["version"] != expected_goal_version:
        raise ApiError(
            "ERR_STALE_GOAL_VERSION",
            412,
            "expected_goal_version does not match the goal's current version",
        )
    record = {
        "id": new_id(),
        "goal_id": id,
        "measured_at": fmt_iso(measured_dt),
        "value": value,
        "note": note,
        "_measured_at_dt": measured_dt,
    }
    stamp_new(record, with_version=True)
    DB["indicators"][record["id"]] = record
    # First indicator under an ADOPTED goal moves it to MONITORING.
    if goal["status"] == "ADOPTED":
        goal["status"] = "MONITORING"
    recompute_goal_attainment(goal)
    touch(goal)
    return ok(indicator_view(record), status=201)


@bp.get("/accreditation/goals/<id>/indicators")
def list_indicators(id):
    auth(["AccreditationOfficer", "AccreditationCommission", "SchoolLeader"])
    get_or_404("goals", id, "ImprovementGoal")
    limit, offset = pagination()
    rows = [i for i in DB["indicators"].values() if i["goal_id"] == id]
    rows.sort(key=lambda i: i["created_at"])
    page, total = paginate(rows, limit, offset)
    return ok_list([indicator_view(r) for r in page], total, limit, offset)


@bp.post("/accreditation/goals/<id>/mark-achieved")
def mark_achieved(id):
    auth(["AccreditationOfficer"])
    goal = get_or_404("goals", id, "ImprovementGoal")
    if goal["status"] != "MONITORING":
        raise ApiError("ERR_INVALID_STATE", 409, "Goal must be MONITORING")
    if goal["attainment_pct"] < 100.0:
        raise ApiError(
            "ERR_THRESHOLD_NOT_MET",
            422,
            "attainment_pct must be >= 100.00",
        )
    goal["status"] = "ACHIEVED"
    touch(goal)
    return ok(goal_view(goal))


@bp.post("/accreditation/goals/<id>/abandon")
def abandon_goal(id):
    auth(["AccreditationOfficer"])
    goal = get_or_404("goals", id, "ImprovementGoal")
    if goal["status"] not in ("ADOPTED", "MONITORING"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Goal must be ADOPTED or MONITORING"
        )
    goal["status"] = "ABANDONED"
    touch(goal)
    return ok(goal_view(goal))
