"""Member routes + reinstate + member no-show-events (PRD §3.2, §3.6)."""
from flask import Blueprint, request

from db import store
from errors import err, ERR_NOT_FOUND, ERR_INVALID_STATE
from middleware import authenticate, require_role, forbid
from response import success, success_list
from util import get_json_body, require_str, parse_pagination, paginate
from services.common import make_full, bump
from services import serialize

bp = Blueprint("members", __name__)


@bp.route("/members", methods=["POST"])
def create_member():
    p = authenticate()
    require_role(p, ["StudioManager", "FrontDesk"])
    body = get_json_body()
    home_location_id = require_str(body, "home_location_id")
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    if home_location_id not in store.locations:
        raise err(ERR_NOT_FOUND, "Location not found.")
    rec = make_full({
        "home_location_id": home_location_id,
        "full_name": full_name,
        "email": email,
        "intro_completed": False,
        "mobility_tier": None,
        "strike_score": 0,
        "status": "ACTIVE",
    })
    store.members[rec["id"]] = rec
    return success(serialize.member_view(rec), 201)


@bp.route("/members", methods=["GET"])
def list_members():
    p = authenticate()
    require_role(p, ["StudioManager", "FrontDesk"])
    limit, offset = parse_pagination()
    home_location_id = _qs("home_location_id")
    status = _qs("status")
    items = [r for r in store.members.values()
             if (home_location_id is None or r["home_location_id"] == home_location_id)
             and (status is None or r["status"] == status)]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.member_view(r) for r in window], limit, offset, total)


@bp.route("/members/<mid>", methods=["GET"])
def get_member(mid):
    p = authenticate()
    require_role(p, ["StudioManager", "FrontDesk", "Member"])
    rec = store.members.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    if p.is_member and p.user_id != mid:
        forbid()
    return success(serialize.member_view(rec), 200)


@bp.route("/members/<mid>/reinstate", methods=["POST"])
def reinstate_member(mid):
    p = authenticate()
    require_role(p, ["StudioManager"])
    rec = store.members.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    if rec["status"] != "SUSPENDED":
        raise err(ERR_INVALID_STATE, "Member is not SUSPENDED.")
    rec["status"] = "ACTIVE"
    bump(rec)
    return success(serialize.member_view(rec), 200)


@bp.route("/members/<mid>/no-show-events", methods=["GET"])
def member_no_show_events(mid):
    p = authenticate()
    require_role(p, ["StudioManager", "FrontDesk", "Member"])
    member = store.members.get(mid)
    if member is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    if p.is_member and p.user_id != mid:
        forbid()
    limit, offset = parse_pagination()
    items = [e for e in store.no_show_events.values() if e["member_id"] == mid]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.noshow_view(e) for e in window], limit, offset, total)


def _qs(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
