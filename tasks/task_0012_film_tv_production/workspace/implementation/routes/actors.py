"""Actor routes."""
from flask import Blueprint

import errors as E
from db import store, init_common
from middleware import require_roles
from response import ok_object
from body import get_json_body, require_string
from services.serializers import serialize_actor


bp = Blueprint("actors", __name__)


@bp.route("/actors", methods=["POST"])
@require_roles("CastingDirector")
def create_actor():
    body = get_json_body()
    legal = require_string(body, "legal_name")
    email = require_string(body, "agency_contact_email")
    zone = require_string(body, "travel_origin_zone")
    rec = {
        "legal_name": legal,
        "agency_contact_email": email,
        "travel_origin_zone": zone,
        "active": True,
    }
    init_common(rec)
    store.actors[rec["id"]] = rec
    return ok_object(serialize_actor(rec), http_status=201)


@bp.route("/actors/<aid>", methods=["GET"])
@require_roles("CastingDirector", "LineProducer")
def get_actor(aid):
    a = store.actors.get(aid)
    if not a:
        E.not_found(f"Actor {aid} not found")
    return ok_object(serialize_actor(a))
