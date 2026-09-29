"""Product-line design records (PRD 3.1)."""

from flask import Blueprint

import domain
from auth import ANY, require_action_role, require_roles
from calcs import fnum
from db import clock_iso, db, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    MATERIAL_GRADES,
    PRESSURE_CLASSES,
    SEAT_TYPES,
    SPECIAL_SERVICES,
    VALVE_TYPES,
    filter_value,
    get_body,
    get_enum,
    get_enum_array,
    get_int,
    get_number,
    get_string,
    invalid,
    paginate,
    parse_pagination,
    present,
)

bp = Blueprint("valve_models", __name__)

ACTION_ROLES = {
    "SUBMIT_REVIEW": ["ProductEngineer"],
    "RELEASE": ["QualityManager"],
    "REJECT": ["QualityManager"],
    # PRD 2.1 gives WITHDRAW to the ProductEngineer, PRD 3.1 to the QualityManager.
    "WITHDRAW": ["ProductEngineer", "QualityManager"],
}
ACTIONS = list(ACTION_ROLES.keys())
ACTIVE_CODE_STATUSES = ("DRAFT", "IN_REVIEW", "RELEASED")


def _code_taken(model_code, exclude_id=None):
    for row in db.valve_models.values():
        if row["id"] == exclude_id:
            continue
        if row["model_code"] == model_code and row["status"] in ACTIVE_CODE_STATUSES:
            return True
    return False


@bp.post("/valve-mfg/valve-models")
def create_model():
    user_id, _role = require_roles(["ProductEngineer"])
    body = get_body()
    model_code = get_string(body, "model_code")
    valve_type = get_enum(body, "valve_type", VALVE_TYPES)
    pressure_class = get_int(body, "pressure_class", allowed=PRESSURE_CLASSES)
    body_material_grade = get_enum(body, "body_material_grade", MATERIAL_GRADES)
    bore_size_mm = get_int(body, "bore_size_mm", minimum=1)
    seat_type = get_enum(body, "seat_type", SEAT_TYPES)
    base_break_torque_nm = get_number(body, "base_break_torque_nm", exclusive_minimum=0)
    required_special_services = get_enum_array(
        body, "required_special_services", SPECIAL_SERVICES, required=False, default=[]
    )
    repair_kit_stock_qty = get_int(
        body, "repair_kit_stock_qty", required=False, default=0, minimum=0
    )
    supersedes_model_id = get_string(
        body, "supersedes_model_id", required=False, default=None
    )

    if supersedes_model_id is not None:
        domain.find_model(supersedes_model_id)
    # PRD 3.1 states the model_code uniqueness check only at SUBMIT_REVIEW ("no other
    # design sharing the same `model_code` currently sits in `DRAFT`, `IN_REVIEW` or
    # `RELEASED`"), so a duplicate draft may be opened and is refused only at submission.

    row = new_row(
        {
            "model_code": model_code,
            "valve_type": valve_type,
            "pressure_class": pressure_class,
            "body_material_grade": body_material_grade,
            "bore_size_mm": bore_size_mm,
            "seat_type": seat_type,
            "base_break_torque_nm": fnum(base_break_torque_nm, 1),
            "required_special_services": required_special_services,
            "repair_kit_stock_qty": repair_kit_stock_qty,
            "supersedes_model_id": supersedes_model_id,
            "spec_revision": 1,
            "status": "DRAFT",
            "authored_by_user_id": user_id,
            "released_at": None,
        }
    )
    db.valve_models[row["id"]] = row
    return object_response(domain.serialize_model(row), 201)


@bp.get("/valve-mfg/valve-models")
def list_models():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.valve_models.values()))
    status = filter_value("status")
    valve_type = filter_value("valve_type")
    supersedes = filter_value("supersedes_model_id")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if valve_type is not None:
        rows = [r for r in rows if r["valve_type"] == valve_type]
    if supersedes is not None:
        rows = [r for r in rows if r.get("supersedes_model_id") == supersedes]
    page, total = paginate(rows, limit, offset)
    return list_response([domain.serialize_model(r) for r in page], limit, offset, total)


@bp.get("/valve-mfg/valve-models/<model_id>")
def get_model(model_id):
    require_roles(ANY)
    row = domain.find_model(model_id)
    return object_response(domain.serialize_model(row))


@bp.post("/valve-mfg/valve-models/<model_id>/actions")
def model_actions(model_id):
    user_id, role = require_roles(["ProductEngineer", "QualityManager"])
    body = get_body()
    action = get_enum(body, "action", ACTIONS)
    require_action_role(role, action, ACTION_ROLES)
    model = domain.find_model(model_id)

    if action == "SUBMIT_REVIEW":
        if model["status"] != "DRAFT":
            raise api_error(
                "ERR_STATE_INVALID",
                "SUBMIT_REVIEW requires status DRAFT (current: %s)" % model["status"],
            )
        if not (model["base_break_torque_nm"] > 0 and model["bore_size_mm"] > 0):
            raise invalid("base_break_torque_nm and bore_size_mm must be greater than 0")
        if _code_taken(model["model_code"], exclude_id=model["id"]):
            raise api_error(
                "ERR_DUPLICATE_CODE",
                "model_code '%s' is already in use" % model["model_code"],
            )
        model["status"] = "IN_REVIEW"
        touch(model)

    elif action == "REJECT":
        if model["status"] != "IN_REVIEW":
            raise api_error(
                "ERR_STATE_INVALID",
                "REJECT requires status IN_REVIEW (current: %s)" % model["status"],
            )
        model["status"] = "DRAFT"
        model["spec_revision"] = model["spec_revision"] + 1
        touch(model)
        domain.mark_pinned_orders_stale(model["id"])

    elif action == "RELEASE":
        if model["status"] != "IN_REVIEW":
            raise api_error(
                "ERR_STATE_INVALID",
                "RELEASE requires status IN_REVIEW (current: %s)" % model["status"],
            )
        qualified = domain.model_qualified_special_services(model)
        missing = [
            s for s in (model.get("required_special_services") or []) if s not in qualified
        ]
        if missing:
            raise api_error(
                "ERR_SPECIAL_SERVICE_NOT_QUALIFIED",
                "special services without a valid type test: %s" % ", ".join(missing),
            )
        model["status"] = "RELEASED"
        model["released_at"] = clock_iso()
        touch(model)
        predecessor_id = model.get("supersedes_model_id")
        if predecessor_id:
            predecessor = db.valve_models.get(predecessor_id)
            if predecessor is not None and predecessor["status"] == "RELEASED":
                predecessor["status"] = "SUPERSEDED"
                touch(predecessor)
                domain.mark_pinned_orders_stale(predecessor["id"])

    else:  # WITHDRAW
        if model["status"] != "RELEASED":
            raise api_error(
                "ERR_STATE_INVALID",
                "WITHDRAW requires status RELEASED (current: %s)" % model["status"],
            )
        for unit in domain.units_of_model(model["id"]):
            domain.refresh_unit(unit)
            if unit["cert_status"] in ("TESTS_IN_PROGRESS", "TESTS_PASSED"):
                raise api_error(
                    "ERR_STATE_INVALID",
                    "a unit of this design is mid-certification (%s)"
                    % unit["cert_status"],
                )
        model["status"] = "WITHDRAWN"
        touch(model)
        domain.mark_pinned_orders_stale(model["id"])

    return object_response(domain.serialize_model(model))
