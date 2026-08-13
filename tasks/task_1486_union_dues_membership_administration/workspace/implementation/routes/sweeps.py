"""Ops-run delinquency sweep endpoint."""
from flask import Blueprint, request

import db
import errors
import utils
from middleware import require_roles
from response import ok
from services import sweep as sweep_svc

bp = Blueprint("sweeps", __name__, url_prefix="/api/system/sweeps")


@bp.route("/delinquency", methods=["POST"])
@require_roles("LocalAdmin")
def delinquency_sweep(user_id, role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    local_id = utils.require_field(body, "local_id")
    local = db.store.locals.get(local_id)
    if local is None:
        raise errors.local_not_found_body()
    result = sweep_svc.run_sweep(local)
    return ok(result, 200)
