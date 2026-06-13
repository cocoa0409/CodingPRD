"""Inspector endpoints — PRD §3.1."""
from flask import Blueprint

from db import STORE
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, serialize
from services.validation import require_body, req_str, opt_int

bp = Blueprint("inspectors", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/inspectors", methods=["POST"])
def create_inspector():
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    body = require_body()
    full_name = req_str(body, "full_name")
    badge_number = req_str(body, "badge_number")
    travel_buffer_minutes = opt_int(body, "travel_buffer_minutes", default=30, minimum=0)
    with STORE.lock:
        i = base_entity()
        i.update({
            "full_name": full_name,
            "badge_number": badge_number,
            "travel_buffer_minutes": travel_buffer_minutes,
            "status": "ACTIVE",
        })
        STORE.inspectors[i["id"]] = i
        return success(serialize(i), status=201)


@bp.route("/disaster-relief/inspectors", methods=["GET"])
def list_inspectors():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(STORE.inspectors.values(), {"status": "status"})
    return success(data, pagination=pg)


@bp.route("/disaster-relief/inspectors/<iid>", methods=["GET"])
def get_inspector(iid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        i = lookup("inspectors", iid)
        return success(serialize(i))
