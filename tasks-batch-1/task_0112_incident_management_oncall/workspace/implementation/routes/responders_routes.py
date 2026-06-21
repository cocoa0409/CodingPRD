"""Responder creation + read."""
from flask import Blueprint

import response
from db import db
from errors import ApiError
from middleware import require_user_context, require_role, get_json_body
from services.common import require_str, optional_str, stamp_create
from services.lookups import get_responder
from services.serializers import responder_out

bp = Blueprint("responders", __name__)

ALL_ROLES = {"PlatformAdmin", "IncidentCommander", "ResponderUser"}


@bp.route("/responders", methods=["POST"])
def create_responder():
    _, role = require_user_context()
    require_role(role, {"PlatformAdmin"})
    body = get_json_body()
    full_name = require_str(body, "full_name")
    email = require_str(body, "email")
    sms_number = optional_str(body, "sms_number")
    voice_number = optional_str(body, "voice_number")
    push_token = optional_str(body, "push_token")
    with db.lock:
        for r in db.responders.values():
            if r["email"] == email:
                raise ApiError("ERR_INVALID_REQUEST", "email must be unique across responders.")
        rec = stamp_create({
            "full_name": full_name,
            "email": email,
            "sms_number": sms_number,
            "voice_number": voice_number,
            "push_token": push_token,
        })
        db.responders[rec["id"]] = rec
    return response.success(responder_out(rec), 201)


@bp.route("/responders/<rid>", methods=["GET"])
def get_one_responder(rid):
    _, role = require_user_context()
    require_role(role, ALL_ROLES)
    with db.lock:
        r = get_responder(rid)
        return response.success(responder_out(r), 200)
