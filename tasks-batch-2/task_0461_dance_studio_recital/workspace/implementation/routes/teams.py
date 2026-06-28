"""CompetitionTeam / TeamMembership routes (PRD 3.7). OCC on roster add (PRD 2.8)."""
from flask import Blueprint, request

from db import common_fields, db, new_id, touch
from errors import err
from helpers import (LEVEL_ORDINAL, LEVELS, lookup, paginate, require_enum,
                     require_fields, require_int, require_str, sort_by_created)
from middleware import authenticate, get_json
from response import success
from views import public, public_list

bp = Blueprint("teams", __name__)


def recompute_roster_count(team):
    count = sum(
        1 for m in db.memberships.values()
        if m["team_id"] == team["id"] and m["status"] == "ROSTERED"
    )
    if team["roster_count"] != count:
        team["roster_count"] = count
        touch(team)


@bp.route("/teams", methods=["POST"])
def create_team():
    authenticate({"StudioAdmin"})
    body = get_json()
    require_fields(body, ["name", "min_level", "roster_cap"])
    name = require_str(body, "name")
    min_level = require_enum(body, "min_level", set(LEVELS))
    roster_cap = require_int(body, "roster_cap", lo=1)
    team = {
        "id": new_id(),
        "name": name,
        "min_level": min_level,
        "roster_cap": roster_cap,
        "roster_count": 0,
        "status": "FORMING",
        **common_fields(),
    }
    db.teams[team["id"]] = team
    return success(public(team), status=201)


@bp.route("/teams/<tid>", methods=["GET"])
def get_team(tid):
    authenticate({"StudioAdmin", "Parent", "Instructor"})
    team = lookup(db.teams, tid)
    return success(public(team), status=200)


@bp.route("/teams/<tid>/lock", methods=["POST"])
def lock_team(tid):
    authenticate({"StudioAdmin"})
    team = lookup(db.teams, tid)
    if team["status"] != "FORMING":
        raise err("ERR_INVALID_STATE", "Team is not FORMING.")
    team["status"] = "LOCKED"
    touch(team)
    return success(public(team), status=200)


@bp.route("/teams/<tid>/memberships", methods=["POST"])
def add_membership(tid):
    authenticate({"StudioAdmin"})
    team = lookup(db.teams, tid)
    body = get_json()
    require_fields(body, ["student_id", "expected_team_version"])
    student = lookup(db.students, body["student_id"])
    expected = require_int(body, "expected_team_version")

    # State: roster adds rejected once LOCKED (priority 5 before OCC priority 6).
    if team["status"] != "FORMING":
        raise err("ERR_INVALID_STATE", "Team roster is frozen.")

    # OCC on team version.
    if expected != team["version"]:
        raise err("ERR_STALE_VERSION", "Team version mismatch.")

    # Roster cap + min level (both ERR_ROSTER_FULL per scaffold priority 12).
    if team["roster_count"] >= team["roster_cap"]:
        raise err("ERR_ROSTER_FULL", "Roster is full.")
    if LEVEL_ORDINAL[student["level"]] < LEVEL_ORDINAL[team["min_level"]]:
        raise err("ERR_ROSTER_FULL", "Student level below team min_level.")

    membership = {
        "id": new_id(),
        "team_id": team["id"],
        "student_id": student["id"],
        "status": "ROSTERED",
        **common_fields(),
    }
    db.memberships[membership["id"]] = membership
    team["roster_count"] += 1
    touch(team)  # successful add bumps the team version by one
    return success(public(membership), status=201)


@bp.route("/teams/<tid>/memberships", methods=["GET"])
def list_team_memberships(tid):
    authenticate({"StudioAdmin", "Parent"})
    team = lookup(db.teams, tid)
    items = [m for m in db.memberships.values() if m["team_id"] == team["id"]]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    authenticate({"StudioAdmin", "Parent"})
    items = list(db.memberships.values())
    for key in ("student_id", "team_id"):
        val = request.args.get(key)
        if val is not None:
            items = [m for m in items if m[key] == val]
    items = sort_by_created(items)
    page, pg = paginate(items)
    return success(public_list(page), status=200, is_array=True, pagination=pg)


@bp.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    authenticate({"StudioAdmin", "Parent"})
    membership = lookup(db.memberships, mid)
    return success(public(membership), status=200)


@bp.route("/memberships/<mid>/release", methods=["POST"])
def release_membership(mid):
    authenticate({"StudioAdmin"})
    membership = lookup(db.memberships, mid)
    team = db.teams.get(membership["team_id"])
    if membership["status"] != "ROSTERED":
        raise err("ERR_INVALID_STATE", "Membership is not ROSTERED.")
    if team is None or team["status"] != "FORMING":
        raise err("ERR_INVALID_STATE", "Team roster is frozen.")
    membership["status"] = "RELEASED"
    touch(membership)
    team["roster_count"] -= 1
    touch(team)
    return success(public(membership), status=200)
