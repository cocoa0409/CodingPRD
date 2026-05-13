"""Agency-binding routes."""

from flask import Blueprint, request

from middleware import require_role, current_role, current_user_id
from response import success_response
from services import agency_binding as ab_svc

bp = Blueprint("agency_bindings", __name__)


@bp.route("/agency-bindings", methods=["POST"])
def create():
    require_role("PlatformAdmin", "RightsHolder")
    body = request.get_json(silent=True) or {}
    # RightsHolder ownership: rights_holder_id in body must match X-User-ID.
    if current_role() == "RightsHolder":
        if body.get("rights_holder_id") != current_user_id():
            from errors import raise_err
            raise_err("ERR_FORBIDDEN", "Cannot create binding for another holder")
    data = ab_svc.create_agency_binding(body)
    return success_response(data, status_code=201)


@bp.route("/agency-bindings/<binding_id>/terminate", methods=["POST"])
def terminate(binding_id):
    require_role("PlatformAdmin", "RightsHolder")
    body = request.get_json(silent=True) or {}
    # RightsHolder ownership: only terminate own bindings.
    from db import store
    if current_role() == "RightsHolder":
        b = store.agency_bindings.get(binding_id)
        if b and b["rights_holder_id"] != current_user_id():
            from errors import raise_err
            raise_err("ERR_FORBIDDEN", "Not owner of binding")
    data = ab_svc.terminate_agency_binding(binding_id, body)
    return success_response(data)
