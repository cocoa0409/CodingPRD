"""Rights-holder routes."""

from flask import Blueprint, request

from middleware import require_role
from response import success_response, list_response
from services import rights_holder as rh_svc
from services import admin_ops
from services import dispute as dispute_svc

bp = Blueprint("rights_holders", __name__)


@bp.route("/rights-holders", methods=["POST"])
def create():
    require_role("PlatformAdmin")
    body = request.get_json(silent=True) or {}
    data = rh_svc.create_rights_holder(body)
    return success_response(data, status_code=201)


@bp.route("/rights-holders/<holder_id>", methods=["GET"])
def get(holder_id):
    require_role("PlatformAdmin", "RightsHolder", "FinanceOps", "RegistrationReviewer", "DisputeOfficer")
    data = rh_svc.get_rights_holder(holder_id)
    return success_response(data)


@bp.route("/rights-holders", methods=["GET"])
def list_all():
    require_role("PlatformAdmin", "FinanceOps")
    items, total, limit, offset = rh_svc.list_rights_holders(request.args)
    return list_response(items, total, limit, offset)


@bp.route("/rights-holders/<holder_id>/dispute-exposure", methods=["GET"])
def dispute_exposure(holder_id):
    require_role("PlatformAdmin", "FinanceOps")
    mode = request.args.get("mode", "forward_looking")
    if mode not in ("forward_looking", "chronological"):
        from errors import raise_err
        raise_err("ERR_VALIDATION", "Invalid mode")
    data = dispute_svc.compute_exposure_score(holder_id, mode)
    return success_response(data)


@bp.route("/rights-holders/<holder_id>/micro-balance", methods=["GET"])
def micro_balance(holder_id):
    require_role("PlatformAdmin", "RightsHolder", "FinanceOps")
    # Ownership check for RightsHolder
    from middleware import current_role, current_user_id
    if current_role() == "RightsHolder" and current_user_id() != holder_id:
        from errors import raise_err
        raise_err("ERR_FORBIDDEN", "Not owner")
    items = admin_ops.read_micro_balance(holder_id)
    # The endpoint returns an array but isn't paginated per the PRD; we still emit "array" envelope.
    return success_response(items, response_type="array")
