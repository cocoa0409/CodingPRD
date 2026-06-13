"""Recoupment endpoints — PRD §3.9."""
from flask import Blueprint

from db import STORE
from errors import ApiError
from middleware import get_auth, require_roles
from response import success
from services.common import lookup, list_response
from services.models import touch, serialize
from services.validation import require_body, req_int

bp = Blueprint("recoupments", __name__)

ALL_ROLES = ["ProgramAdmin", "Caseworker", "Inspector"]


@bp.route("/disaster-relief/recoupments", methods=["GET"])
def list_recoupments():
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        data, pg = list_response(
            STORE.recoupments.values(),
            {"ihp_case_id": "ihp_case_id", "status": "status", "origin": "origin"},
        )
    return success(data, pagination=pg)


@bp.route("/disaster-relief/recoupments/<rid>", methods=["GET"])
def get_recoupment(rid):
    _uid, role = get_auth()
    require_roles(role, ALL_ROLES)
    with STORE.lock:
        r = lookup("recoupments", rid)
        return success(serialize(r))


@bp.route("/disaster-relief/recoupments/<rid>/record-recovery", methods=["POST"])
def record_recovery(rid):
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    body = require_body()
    with STORE.lock:
        r = lookup("recoupments", rid)
        if r["status"] != "ESTABLISHED":
            raise ApiError("ERR_RECOUPMENT_NOT_ESTABLISHED")
        amount_cents = req_int(body, "amount_cents", minimum=0)
        r["recovered_cents"] += amount_cents
        if r["recovered_cents"] >= r["debt_amount_cents"]:
            r["status"] = "SATISFIED"
        touch(r)
        return success(serialize(r))


@bp.route("/disaster-relief/recoupments/<rid>/waive", methods=["POST"])
def waive_recoupment(rid):
    _uid, role = get_auth()
    require_roles(role, ["ProgramAdmin"])
    with STORE.lock:
        r = lookup("recoupments", rid)
        if r["status"] != "ESTABLISHED":
            raise ApiError("ERR_RECOUPMENT_NOT_ESTABLISHED")
        r["status"] = "WAIVED"
        touch(r)
        return success(serialize(r))
