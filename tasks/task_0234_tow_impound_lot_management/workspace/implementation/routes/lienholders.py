"""Lienholder endpoints."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services.serialize import public
from validators import require_str

bp = Blueprint("lienholders", __name__)


def get_lienholder_or_404(lh_id):
    lh = db.lienholders.get(lh_id)
    if lh is None:
        raise ApiError("ERR_NOT_FOUND", "Lienholder not found")
    return lh


@bp.route("/lienholders", methods=["POST"])
def create_lienholder():
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    body = get_json_body()
    name = require_str(body, "name")
    mailing_address = require_str(body, "mailing_address")
    state_code = require_str(body, "state_code")
    lh = {"name": name, "mailing_address": mailing_address, "state_code": state_code}
    db.stamp_create(lh)
    db.lienholders[lh["id"]] = lh
    return object_response(public(lh), 201)


@bp.route("/lienholders/<lh_id>", methods=["GET"])
def get_lienholder(lh_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "Claimant"})
    lh = get_lienholder_or_404(lh_id)
    return object_response(public(lh), 200)
