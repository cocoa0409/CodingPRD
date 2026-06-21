"""Guest read endpoints (PRD §4)."""
from flask import Blueprint

import errors
from db import db
from middleware import get_principal, require_role
from serializers import serialize
from response import success
from routes.common import list_filtered

bp = Blueprint("guests", __name__)


@bp.route("/guests", methods=["GET"])
def list_guests():
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    return list_filtered(db.guests, [("visit_id", "visit_id", "str")])


@bp.route("/guests/<guest_id>", methods=["GET"])
def get_guest(guest_id):
    _, role = get_principal()
    require_role(role, {"NetworkAdmin", "Member", "LoungeAgent"})
    g = db.guests.items.get(guest_id)
    if not g:
        raise errors.not_found("Guest not found")
    return success(serialize(g))
