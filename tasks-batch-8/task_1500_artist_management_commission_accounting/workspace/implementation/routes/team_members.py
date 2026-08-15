"""TeamMember endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import db
from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from response import success_object
from routes.helpers import get_one, list_response, public, scoped_mutation_auth
from services.core import new_record, touch
from util import parse_date
from validate import (
    get_body, opt_date, opt_int, req_date, req_enum, req_str,
    require_path_resource, require_ref,
)

bp = Blueprint("team_members", __name__)

MEMBER_ROLES = {"AGENT", "BUSINESS_MANAGER", "PUBLICIST"}


@bp.post("/team-members")
def create_team_member():
    body = get_body()
    artist_id = req_str(body, "artist_id")
    caller = scoped_mutation_auth(["FirmAdmin"], body_artist_id=artist_id)
    member_role = req_enum(body, "member_role", MEMBER_ROLES)
    display_name = req_str(body, "display_name")
    window_start = req_date(body, "window_start_date")
    window_end = opt_date(body, "window_end_date")
    cap = opt_int(body, "authority_expense_cap_cents", default=100000, non_negative=True)
    if window_end is not None and parse_date(window_end) < parse_date(window_start):
        raise_error(ERR_INVALID_REQUEST, "window_end_date must be on or after window_start_date")

    require_ref("artists", artist_id, "artist_id")

    rec = new_record("team_members", {
        "artist_id": artist_id,
        "member_role": member_role,
        "display_name": display_name,
        "authority_expense_cap_cents": cap,
        "window_start_date": window_start,
        "window_end_date": window_end,
        "status": "ACTIVE",
    })
    return success_object(public(rec), status=201)


@bp.get("/team-members/<rid>")
def get_team_member(rid):
    return get_one("team_members", rid)


@bp.get("/team-members")
def list_team_members():
    filters = {
        "artist_id": request.args.get("artist_id"),
        "member_role": request.args.get("member_role"),
        "status": request.args.get("status"),
    }
    return list_response("team_members", filters)


def _tm_transition(rid, allowed_from, target):
    caller = scoped_mutation_auth(["FirmAdmin"], "team_members", rid)
    tm = require_path_resource("team_members", rid)
    if tm["status"] not in allowed_from:
        raise_error(ERR_INVALID_STATE, f"cannot move to {target} from {tm['status']}")
    tm["status"] = target
    touch(tm)
    return success_object(public(tm))


@bp.post("/team-members/<rid>/suspend")
def suspend_team_member(rid):
    return _tm_transition(rid, ("ACTIVE",), "SUSPENDED")


@bp.post("/team-members/<rid>/resume")
def resume_team_member(rid):
    return _tm_transition(rid, ("SUSPENDED",), "ACTIVE")


@bp.post("/team-members/<rid>/end")
def end_team_member(rid):
    return _tm_transition(rid, ("ACTIVE", "SUSPENDED"), "ENDED")
