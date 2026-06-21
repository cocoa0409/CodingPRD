"""Caseworker endpoints — PRD §3.1."""
from flask import Blueprint

from db import STORE
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import base_entity, serialize
from services.validation import require_body, req_str, opt_bool

bp = Blueprint("caseworkers", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/caseworkers", methods=["POST"])
def create_caseworker():
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    body = require_body()
    full_name = req_str(body, "full_name")
    employee_id = req_str(body, "employee_id")
    can_approve_awards = opt_bool(body, "can_approve_awards", default=True)
    with STORE.lock:
        c = base_entity()
        c.update({
            "full_name": full_name,
            "employee_id": employee_id,
            "can_approve_awards": can_approve_awards,
            "status": "ACTIVE",
        })
        STORE.caseworkers[c["id"]] = c
        return success(serialize(c), status=201)


@bp.route("/disaster-relief/caseworkers", methods=["GET"])
def list_caseworkers():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(STORE.caseworkers.values(), {"status": "status"})
    return success(data, pagination=pg)


@bp.route("/disaster-relief/caseworkers/<cid>", methods=["GET"])
def get_caseworker(cid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        c = lookup("caseworkers", cid)
        return success(serialize(c))
