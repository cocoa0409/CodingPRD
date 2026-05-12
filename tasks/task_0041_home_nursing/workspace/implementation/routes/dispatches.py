"""Routes for /dispatches/{id}/* endpoints."""
from flask import Blueprint, g

from db import public
from middleware import require_auth, get_json_body
from response import success
from errors import err
from services import dispatch as dispatch_svc


bp = Blueprint("dispatches", __name__)


@bp.route("/dispatches/<dispatch_id>", methods=["GET"])
@require_auth(roles={"PlatformAdmin", "ComplianceOfficer", "Nurse"})
def get_dispatch(dispatch_id):
    d = dispatch_svc.get_dispatch(dispatch_id)
    if g.user_role == "Nurse" and d.get("nurse_id") != g.user_id:
        raise err("ERR_INSUFFICIENT_PERMISSIONS", "not your dispatch")
    return success(public(d))


@bp.route("/dispatches/<dispatch_id>/accept", methods=["POST"])
@require_auth(roles={"Nurse"})
def accept(dispatch_id):
    body = get_json_body()
    d = dispatch_svc.accept_dispatch(dispatch_id, g.user_id, body)
    return success(public(d))


@bp.route("/dispatches/<dispatch_id>/reject", methods=["POST"])
@require_auth(roles={"Nurse"})
def reject(dispatch_id):
    body = get_json_body()
    d = dispatch_svc.reject_dispatch(dispatch_id, g.user_id, body)
    return success(public(d))
