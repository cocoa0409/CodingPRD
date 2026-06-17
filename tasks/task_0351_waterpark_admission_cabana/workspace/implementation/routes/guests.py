"""Guest endpoints (PRD §3.4)."""
from flask import Blueprint

from db import db, new_id, add_common_fields
from middleware import authenticate, require_role
from response import success
from services import serialize
from services.common import get_json_body, require_string, require_int
from services.lookup import get_guest

bp = Blueprint("guests", __name__)


@bp.route("/guests", methods=["POST"])
def create_guest():
    _, role = authenticate()
    require_role(role, {"Guest", "ParkManager"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    zip_code = require_string(body, "zip_code")
    height_cm = require_int(body, "height_cm", minimum=0)

    rec = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "zip_code": zip_code,
        "height_cm": height_cm,
        "wallet_credit_cents": 0,
    }
    add_common_fields(rec)
    db.guests[rec["id"]] = rec
    return success(serialize.guest(rec), status=201)


@bp.route("/guests/<gid>", methods=["GET"])
def get_guest_route(gid):
    _, role = authenticate()
    require_role(role, {"Guest", "ParkManager", "GateAgent", "FinanceClerk"})
    rec = get_guest(gid)
    return success(serialize.guest(rec))
