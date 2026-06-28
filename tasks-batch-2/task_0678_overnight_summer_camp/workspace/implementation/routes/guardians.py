"""Guardian registration (anonymous) and retrieval. PRD §3.3."""
from flask import Blueprint

import db
import response
from middleware import get_identity, require_role, get_json_body
from services import validate, serialize
from services.store import base_fields, require

bp = Blueprint("guardians", __name__)


@bp.route("/guardians/register", methods=["POST"])
def register_guardian():
    # Exempt from auth (SCAFFOLD §1.4). Anyone may register a Guardian.
    body = get_json_body()
    email = validate.require_str(body, "email")
    full_name = validate.require_str(body, "full_name")
    phone = validate.require_str(body, "phone")

    g = base_fields()
    g.update({"email": email, "full_name": full_name, "phone": phone})
    db.guardians[g["id"]] = g
    return response.success(serialize.guardian(g), 201)


@bp.route("/guardians/<gid>", methods=["GET"])
def get_guardian(gid):
    _uid, role = get_identity()
    require_role(role, {"Guardian", "CampDirector"})
    g = require(db.guardians, gid)
    return response.success(serialize.guardian(g), 200)
