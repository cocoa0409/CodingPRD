"""Allocation routes."""
from decimal import Decimal, ROUND_HALF_UP
from flask import Blueprint, request

import db
from errors import (
    err_not_found, err_invalid_request, err_stale_version,
)
from middleware import require_roles, check_caregiver_ownership
from response import success
from services.util import body, req_number, req_str, opt_str, paginate, serialize, hours_val

bp = Blueprint("allocations", __name__)


def _allocation_or_404(aid):
    a = db.allocations.get(aid)
    if a is None:
        raise err_not_found("allocation")
    return a


@bp.route("/respite/allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    user_id, role = require_roles("Caregiver", "Coordinator", "FunderAdmin")
    alloc = _allocation_or_404(aid)
    check_caregiver_ownership(user_id, role, alloc["caregiver_id"])
    return success(serialize(alloc, "allocation"))


@bp.route("/respite/allocations", methods=["GET"])
def list_allocations():
    user_id, role = require_roles("Caregiver", "Coordinator", "FunderAdmin")
    caregiver_id = request.args.get("caregiver_id")
    program_id = request.args.get("program_id")
    status = request.args.get("status")
    items = list(db.allocations.values())
    if role == "Caregiver":
        # caregiver sees only own allocations
        items = [a for a in items if a["caregiver_id"] == user_id]
    if caregiver_id:
        items = [a for a in items if a["caregiver_id"] == caregiver_id]
    if program_id:
        items = [a for a in items if a["program_id"] == program_id]
    if status:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return success(
        [serialize(a, "allocation") for a in page],
        response_type="array",
        pagination=meta,
    )


@bp.route("/respite/allocations/<aid>/grant-adjustments", methods=["POST"])
def grant_adjustment(aid):
    require_roles("Coordinator")
    data = body()
    delta = req_number(data, "delta_hours")
    reason = req_str(data, "reason")
    expected = data.get("expected_allocation_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise err_invalid_request("expected_allocation_version is required and must be an integer")
    alloc = _allocation_or_404(aid)
    if alloc["version"] != expected:
        raise err_stale_version()
    new_granted = Decimal(str(alloc["granted_hours"])) + Decimal(str(delta))
    floor_sum = (
        Decimal(str(alloc["reserved_hours"]))
        + Decimal(str(alloc["consumed_hours"]))
        + Decimal(str(alloc["expired_hours"]))
        + Decimal(str(alloc["revoked_hours"]))
    )
    if new_granted < floor_sum:
        raise err_invalid_request(
            "granted_hours would fall below reserved+consumed+expired+revoked"
        )
    alloc["granted_hours"] = hours_val(new_granted)
    alloc["available_hours"] = hours_val(
        Decimal(str(alloc["available_hours"])) + Decimal(str(delta))
    )
    db.touch(alloc)
    return success(serialize(alloc, "allocation"), status=201)
