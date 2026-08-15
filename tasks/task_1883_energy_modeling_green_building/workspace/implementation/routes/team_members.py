"""TeamMember endpoints (PRD 3.1)."""
from flask import Blueprint, request

from db import DB
from errors import ApiError
from middleware import auth_headers, require_role
from response import ok, ok_list
from services import get_member, ser_member, sorted_created, stamp
from util import SPECIALTIES, as_enum, as_opt_bool, as_str, body, bool_filter, pagination_args, required

bp = Blueprint("team_members", __name__)


@bp.post("/team-members")
def create_member():
    _user_id, role = auth_headers()
    data = body()
    full_name = as_str(required(data, "full_name"), "full_name")
    email = as_str(required(data, "email"), "email")
    specialty = as_enum(required(data, "specialty"), SPECIALTIES, "specialty")
    is_independent = as_opt_bool(data, "is_independent", False)
    require_role(role, {"ProgramAdmin"})
    for m in DB["team_members"].values():
        if m["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", 400, "email must be unique across members")
    rec = stamp(
        {
            "full_name": full_name,
            "email": email,
            "specialty": specialty,
            "is_independent": is_independent,
        }
    )
    DB["team_members"][rec["id"]] = rec
    return ok(ser_member(rec), status=201)


@bp.get("/team-members")
def list_members():
    auth_headers()
    specialty = request.args.get("specialty")
    is_independent = bool_filter(request.args.get("is_independent"))
    items = list(DB["team_members"].values())
    if specialty is not None:
        items = [m for m in items if m["specialty"] == specialty]
    if is_independent is not None:
        items = [m for m in items if m["is_independent"] == is_independent]
    items = sorted_created(items)
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset : offset + limit]
    return ok_list([ser_member(m) for m in page], total, limit, offset)


@bp.get("/team-members/<member_id>")
def get_one_member(member_id):
    auth_headers()
    return ok(ser_member(get_member(member_id)))
