"""Housing units and the operator-driven unit status machine (PRD 3.1)."""

from flask import Blueprint

import middleware as mw
import response as resp
from db import base_row, bump, db, sort_rows
from errors import ApiError
from services import core, lookup

bp = Blueprint("units", __name__)

# Operator-permitted edges only.  System edges are driven by other workflows.
OPERATOR_EDGES = {
    ("AVAILABLE", "OFFLINE_MAINTENANCE"),
    ("OFFLINE_MAINTENANCE", "AVAILABLE"),
    ("AVAILABLE", "HAZARD_HOLD"),
    ("ASSIGNED", "HAZARD_HOLD"),
    ("HAZARD_HOLD", "AVAILABLE"),
}


@bp.post("/housing-units")
def create_unit():
    mw.authenticate((mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER))
    body = mw.json_body()
    installation_id = mw.v_id(body, "installation_id")
    unit_code = mw.v_str(body, "unit_code")
    bedroom_count = mw.v_int(body, "bedroom_count", minimum=1, maximum=5)
    unit_type = mw.v_enum(body, "unit_type", mw.UNIT_TYPES)
    designated = mw.v_enum(body, "designated_rank_category", mw.RANK_CATEGORIES)
    historic = mw.v_bool(body, "historic_flag", required=False, default=False)
    features = mw.v_features(body, "accessibility_features", required=False, default=[])
    installation = lookup.installation(installation_id)
    for existing in lookup.units_of(installation["id"]):
        if existing["unit_code"] == unit_code:
            mw.bad("unit_code", "must be unique within the installation")
    row = base_row()
    row["installation_id"] = installation["id"]
    row["unit_code"] = unit_code
    row["bedroom_count"] = bedroom_count
    row["unit_type"] = unit_type
    row["designated_rank_category"] = designated
    row["historic_flag"] = historic
    row["accessibility_features"] = features
    row["status"] = "AVAILABLE"
    row["hazard_hold_reason"] = None
    row["last_lease_end_date"] = None
    db.housing_units[row["id"]] = row
    core.recount(installation)
    return resp.created(row)


@bp.get("/housing-units/<unit_id>")
def get_unit(unit_id):
    mw.authenticate(mw.ALL_ROLES)
    return resp.ok(lookup.housing_unit(unit_id))


@bp.get("/housing-units")
def list_units():
    mw.authenticate(mw.ALL_ROLES)
    limit, offset = mw.pagination()
    installation_id = mw.q_str("installation_id")
    status = mw.q_enum("status", mw.UNIT_STATUSES)
    bedroom_count = mw.q_int("bedroom_count")
    unit_type = mw.q_enum("unit_type", mw.UNIT_TYPES)
    rows = sort_rows(list(db.housing_units.values()))
    if installation_id is not None:
        rows = [r for r in rows if r["installation_id"] == installation_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if bedroom_count is not None:
        rows = [r for r in rows if int(r["bedroom_count"]) == bedroom_count]
    if unit_type is not None:
        rows = [r for r in rows if r["unit_type"] == unit_type]
    return resp.page(rows, limit, offset)


@bp.post("/housing-units/<unit_id>/status")
def set_unit_status(unit_id):
    mw.authenticate((mw.PLATFORM_ADMIN, mw.PROPERTY_MANAGER))
    body = mw.json_body()
    target = mw.v_enum(body, "status", mw.UNIT_STATUSES)
    reason = mw.v_str(body, "hazard_hold_reason", required=False, default=None)
    if target == "HAZARD_HOLD" and reason is None:
        mw.bad("hazard_hold_reason", "is required when placing a unit on hazard hold")
    unit = lookup.housing_unit(unit_id)

    # HousingUnit declares no terminal state, so rung 19 is the only state gate.
    if (unit["status"], target) not in OPERATOR_EDGES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if unit["status"] == "HAZARD_HOLD" and target == "AVAILABLE":
        for case in lookup.hazard_cases_of_unit(unit["id"]):
            if case["status"] in core.BLOCKING_HAZARD_STATUSES:
                raise ApiError(
                    "ERR_INVALID_STATE_TRANSITION",
                    "An open hazard case still holds this unit.")

    unit["status"] = target
    if target == "HAZARD_HOLD":
        unit["hazard_hold_reason"] = reason
    else:
        unit["hazard_hold_reason"] = None
    bump(unit)
    core.recount_for_unit(unit)
    return resp.ok(unit)
