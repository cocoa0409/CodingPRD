"""Team endpoints."""

from flask import Blueprint, request

from db import STORE, new_id
from errors import (
    ERR_INVALID_REQUEST,
    ERR_MEET_ALREADY_COMPLETED,
    ERR_MEET_NOT_FOUND,
    ERR_TEAM_NOT_FOUND,
    raise_err,
)
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    cascade_team_withdraw,
    get_or_404,
    paginate,
    pub_result,
    pub_team,
    recompute_active_entry_count,
    req_body,
    sort_created,
    stamp,
    bump,
    v_str,
)
from decimal import Decimal

bp = Blueprint("teams", __name__)


@bp.post("/teams")
def create_team():
    _, role = ctx()
    require_role(role, "MeetDirector")
    b = req_body()
    meet_id = v_str(b, "meet_id")
    team_code = v_str(b, "team_code")
    team_name = v_str(b, "team_name")
    get_or_404("meets", meet_id, ERR_MEET_NOT_FOUND)
    for t in STORE["teams"].values():
        if t["meet_id"] == meet_id and t["team_code"] == team_code:
            raise_err(ERR_INVALID_REQUEST, "team_code must be unique within the meet")
    team = stamp(
        {
            "id": new_id(),
            "meet_id": meet_id,
            "team_code": team_code,
            "team_name": team_name,
            "status": "REGISTERED",
            "provisional_points": Decimal("0.00"),
            "official_points": Decimal("0.00"),
            "active_entry_count": 0,
        }
    )
    STORE["teams"][team["id"]] = team
    return ok_object(pub_team(team), 201)


@bp.get("/teams/<tid>")
def get_team(tid):
    ctx()
    team = get_or_404("teams", tid, ERR_TEAM_NOT_FOUND)
    return ok_object(pub_team(team))


@bp.get("/teams")
def list_teams():
    ctx()
    items = list(STORE["teams"].values())
    meet_id = request.args.get("meet_id")
    if meet_id is not None:
        items = [t for t in items if t["meet_id"] == meet_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_team(t) for t in page], limit, offset, total)


@bp.get("/teams/<tid>/results")
def team_results(tid):
    ctx()
    team = get_or_404("teams", tid, ERR_TEAM_NOT_FOUND)
    items = sort_created(
        [r for r in STORE["results"].values() if r["team_id"] == team["id"]]
    )
    page, limit, offset, total = paginate(items)
    return ok_list([pub_result(r) for r in page], limit, offset, total)


@bp.post("/teams/<tid>/withdraw")
def withdraw_team(tid):
    _, role = ctx()
    require_role(role, "MeetDirector")
    team = get_or_404("teams", tid, ERR_TEAM_NOT_FOUND)
    if team["status"] != "REGISTERED":
        raise_err(ERR_INVALID_REQUEST, "team is not REGISTERED")
    meet = STORE["meets"][team["meet_id"]]
    if meet["status"] not in ("SETUP", "ENTRIES_OPEN", "ENTRIES_CLOSED", "SEEDED"):
        raise_err(ERR_MEET_ALREADY_COMPLETED, "meet is already COMPLETED or OFFICIAL")
    cascade_team_withdraw(team)
    team["status"] = "WITHDRAWN"
    recompute_active_entry_count(team["id"], bump_on_change=False)
    bump(team)
    return ok_object(pub_team(team))
