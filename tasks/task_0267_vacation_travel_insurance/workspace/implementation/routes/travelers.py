"""Traveler endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize
from services.store_helpers import make_record, get_traveler

bp = Blueprint("travelers", __name__)


@bp.route("/travelers", methods=["POST"])
@require_roles("CarrierAdmin", "Traveler")
def create_traveler():
    body = common.get_json_body()
    email = common.require_str(body, "email")
    full_name = common.require_str(body, "full_name")
    date_of_birth = common.require_str(body, "date_of_birth")

    for t in db.travelers.values():
        if t["email"] == email:
            raise errors.conflict(errors.ERR_DUPLICATE_EMAIL, "Traveler email already in use.")

    rec = make_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
    })
    db.travelers[rec["id"]] = rec
    return response.success_object(serialize.traveler_out(rec), status=201)


@bp.route("/travelers/<traveler_id>", methods=["GET"])
@require_roles("Any")
def get_traveler_route(traveler_id):
    rec = get_traveler(traveler_id)
    return response.success_object(serialize.traveler_out(rec), status=200)
