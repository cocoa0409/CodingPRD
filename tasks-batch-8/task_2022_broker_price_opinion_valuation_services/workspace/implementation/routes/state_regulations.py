"""State regulation endpoints (PRD 3.2)."""

from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import allowed
from response import success_object, success_list
from serializers import ser_state_regulation
from validation import body, req_str, req_bool, opt_num, sort_and_page

bp = Blueprint("state_regulations", __name__)

STATE_CODE_PATTERN = r"^[A-Z]{2}$"


@bp.post("/bpo/state-regulations")
@allowed("ComplianceOfficer")
def create_state_regulation(user_id, role):
    b = body()
    state_code = req_str(b, "state_code", pattern=STATE_CODE_PATTERN)
    bpo_permitted = req_bool(b, "bpo_permitted")
    appraisal_required = req_bool(b, "appraisal_required_for_interior")
    min_driveby = opt_num(b, "min_driveby_radius_miles", default=None, min_v=0)
    min_interior = opt_num(b, "min_interior_radius_miles", default=None, min_v=0)

    # "Create or replace": an existing row for the state is replaced in place.
    existing = db.find_state_regulation_by_code(state_code)
    if existing is not None:
        existing["bpo_permitted"] = bpo_permitted
        existing["appraisal_required_for_interior"] = appraisal_required
        existing["min_driveby_radius_miles"] = min_driveby if min_driveby is not None else existing["min_driveby_radius_miles"]
        existing["min_interior_radius_miles"] = min_interior if min_interior is not None else existing["min_interior_radius_miles"]
        existing["status"] = "ACTIVE"
        db.touch(existing)
        return success_object(ser_state_regulation(existing), 201)

    from decimal import Decimal
    record = db.stamp_new({
        "id": db.new_id(),
        "state_code": state_code,
        "bpo_permitted": bpo_permitted,
        "appraisal_required_for_interior": appraisal_required,
        "min_driveby_radius_miles": min_driveby if min_driveby is not None else Decimal("1.0"),
        "min_interior_radius_miles": min_interior if min_interior is not None else Decimal("0.5"),
        "status": "ACTIVE",
    })
    db.state_regulations[record["id"]] = record
    return success_object(ser_state_regulation(record), 201)


@bp.get("/bpo/state-regulations")
@allowed("ComplianceOfficer", "PlatformAdmin", "OperationsManager", "DispatchCoordinator")
def list_state_regulations(user_id, role):
    records = list(db.state_regulations.values())
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    items, limit, offset, total = sort_and_page(records, ser_state_regulation)
    return success_list(items, limit, offset, total)


@bp.get("/bpo/state-regulations/<state_code>")
@allowed("ComplianceOfficer", "PlatformAdmin", "OperationsManager", "DispatchCoordinator")
def get_state_regulation(user_id, role, state_code):
    record = db.find_state_regulation_by_code(state_code)
    if record is None:
        raise ApiError(ERR_NOT_FOUND, f"StateRegulation {state_code} not found", 404)
    return success_object(ser_state_regulation(record))
