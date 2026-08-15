"""Swimmer endpoints."""

from flask import Blueprint, request

from db import STORE, new_id
from errors import ERR_INSUFFICIENT_PERMISSIONS, ERR_SWIMMER_NOT_FOUND, ERR_TEAM_NOT_FOUND, raise_err
from middleware import ctx, require_role
from response import ok_list, ok_object
from services import (
    SWIMMER_GENDERS,
    age_group_of,
    compute_age,
    get_or_404,
    paginate,
    pub_swimmer,
    req_body,
    sort_created,
    stamp,
    v_enum,
    v_str,
    v_date,
)

bp = Blueprint("swimmers", __name__)


@bp.post("/swimmers")
def create_swimmer():
    user_id, role = ctx()
    require_role(role, "TeamCoach")
    b = req_body()
    team_id = v_str(b, "team_id")
    full_name = v_str(b, "full_name")
    birth_date = v_date(b, "birth_date")
    gender = v_enum(b, "gender", SWIMMER_GENDERS)
    # Ownership: TeamCoach X-User-ID must equal the Team id.
    if team_id != user_id:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "coach may only register swimmers on their own team")
    team = get_or_404("teams", team_id, ERR_TEAM_NOT_FOUND)
    meet = STORE["meets"][team["meet_id"]]
    age = compute_age(birth_date, meet["start_date"])
    swimmer = stamp(
        {
            "id": new_id(),
            "team_id": team_id,
            "full_name": full_name,
            "birth_date": birth_date,
            "gender": gender,
            "age_on_meet_start": age,
            "age_group": age_group_of(age),
            "status": "ACTIVE",
        }
    )
    STORE["swimmers"][swimmer["id"]] = swimmer
    return ok_object(pub_swimmer(swimmer), 201)


@bp.get("/swimmers/<sid>")
def get_swimmer(sid):
    ctx()
    swimmer = get_or_404("swimmers", sid, ERR_SWIMMER_NOT_FOUND)
    return ok_object(pub_swimmer(swimmer))


@bp.get("/swimmers")
def list_swimmers():
    ctx()
    items = list(STORE["swimmers"].values())
    team_id = request.args.get("team_id")
    if team_id is not None:
        items = [s for s in items if s["team_id"] == team_id]
    items = sort_created(items)
    page, limit, offset, total = paginate(items)
    return ok_list([pub_swimmer(s) for s in page], limit, offset, total)
