"""CheckIn routes (§3.5)."""
from flask import Blueprint, request

from common import init_common, touch, require_fields, req_str, paginate
from db import db
from errors import err
from middleware import get_auth, require_role, get_json_body
from response import success
from routes.helpers import get_or_404, fk_or_404
from serializers import view, view_list
from services import derived

bp = Blueprint("check_ins", __name__)


@bp.route("/check-ins", methods=["POST"])
def create_check_in():
    user_id, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    body = get_json_body()
    require_fields(body, ["market_id", "booth_assignment_id", "market_day_id"])
    market_id = req_str(body, "market_id")
    booth_assignment_id = req_str(body, "booth_assignment_id")
    market_day_id = req_str(body, "market_day_id")

    fk_or_404("market", market_id)
    asg = fk_or_404("booth_assignment", booth_assignment_id)
    md = fk_or_404("market_day", market_day_id)
    if asg["market_id"] != market_id or md["market_id"] != market_id:
        raise err("ERR_NOT_FOUND", "assignment/market_day not in market scope")

    # Vendor ownership: the check-in's assignment must belong to the acting vendor
    if role == "Vendor" and asg["vendor_id"] != user_id:
        raise err("ERR_FORBIDDEN_ROLE", "Vendor does not own this assignment")

    c = {
        "market_id": market_id,
        "booth_assignment_id": booth_assignment_id,
        "market_day_id": market_day_id,
        "status": "EXPECTED",
        "arrived_at": None,
    }
    init_common(c)
    db.check_ins[c["id"]] = c
    return success(view(c), 201)


@bp.route("/check-ins/<check_in_id>", methods=["GET"])
def get_check_in(check_in_id):
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    c = get_or_404("check_in", check_in_id)
    return success(view(c), 200)


@bp.route("/check-ins", methods=["GET"])
def list_check_ins():
    _, role = get_auth()
    require_role(role, {"MarketAdmin", "MarketManager", "Vendor"})
    items = list(db.check_ins.values())
    for key in ("market_id", "booth_assignment_id", "market_day_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [c for c in items if c.get(key) == val]
    page, meta = paginate(items)
    return success(view_list(page), 200, is_list=True, pagination=meta)


@bp.route("/check-ins/<check_in_id>/arrive", methods=["POST"])
def arrive(check_in_id):
    user_id, role = get_auth()
    require_role(role, {"MarketAdmin", "Vendor"})
    c = get_or_404("check_in", check_in_id)
    asg = db.booth_assignments.get(c["booth_assignment_id"])
    if role == "Vendor" and (asg is None or asg["vendor_id"] != user_id):
        raise err("ERR_FORBIDDEN_ROLE", "Vendor does not own this check-in")
    # state: EXPECTED (priority 6 before temporal)
    if c["status"] != "EXPECTED":
        raise err("ERR_INVALID_STATE", "CheckIn is not EXPECTED")
    # temporal: market day OPEN (priority 7)
    md = db.market_days.get(c["market_day_id"])
    if md is None or md["status"] != "OPEN":
        raise err("ERR_OUTSIDE_WINDOW", "Market day is not OPEN")

    c["status"] = "PRESENT"
    c["arrived_at"] = db.clock.now_iso()
    touch(c)
    derived.recompute_attendance(md)
    # cascade: RESERVED assignment -> ACTIVE
    if asg is not None and asg["status"] == "RESERVED":
        asg["status"] = "ACTIVE"
        touch(asg)
    return success(view(c), 200)
