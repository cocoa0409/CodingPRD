"""Actuator packages and torque sizing (PRD 3.5)."""

from flask import Blueprint

import calcs
import domain
from auth import ANY, require_action_role, require_roles
from calcs import dec, fnum
from db import db, new_row, sort_rows, touch
from errors import api_error
from response import list_response, object_response
from validation import (
    ACTUATOR_TYPES,
    SIZING_BASES,
    filter_value,
    get_body,
    get_enum,
    get_int,
    get_number,
    get_string,
    invalid,
    paginate,
    parse_pagination,
)

bp = Blueprint("actuator_packages", __name__)

DECISION_ROLES = {"APPROVE": ["QualityManager"], "REJECT": ["QualityManager"]}


@bp.post("/valve-mfg/actuator-packages")
def create_package():
    require_roles(["ProductEngineer"])
    body = get_body()
    valve_unit_id = get_string(body, "valve_unit_id")
    actuator_type = get_enum(body, "actuator_type", ACTUATOR_TYPES)
    output_torque_nm = get_number(body, "output_torque_nm", exclusive_minimum=0)
    sizing_basis = get_enum(body, "sizing_basis", SIZING_BASES)
    expected_version = get_int(body, "expected_valve_unit_version", minimum=0)
    supply_pressure_bar = get_number(
        body, "supply_pressure_bar", required=False, default=0, minimum=0
    )

    unit = domain.find_unit(valve_unit_id)

    if expected_version != unit["version"]:
        raise api_error(
            "ERR_STALE_VALVE_UNIT_VERSION",
            "expected_valve_unit_version %s does not match the unit's current version %s"
            % (expected_version, unit["version"]),
        )

    model = db.valve_models.get(unit["model_id"])
    order = db.orders.get(unit.get("engineered_order_id") or "")
    required, margin, sized = calcs.required_actuator_torque(
        model, unit, sizing_basis, order
    )

    for other in sort_rows(domain.packages_of_unit(unit["id"])):
        if other["sizing_status"] in ("PROPOSED", "APPROVED"):
            other["sizing_status"] = "SUPERSEDED"
            touch(other)

    row = new_row(
        {
            "valve_unit_id": valve_unit_id,
            "actuator_type": actuator_type,
            "supply_pressure_bar": supply_pressure_bar,
            "output_torque_nm": output_torque_nm,
            "sizing_basis": sizing_basis,
            "required_torque_nm": fnum(required, 1),
            "safety_margin_pct": fnum(margin, 2),
            "sized_torque_nm": fnum(sized, 1),
            "sizing_status": "PROPOSED",
            "approved_by_user_id": None,
        }
    )
    db.actuator_packages[row["id"]] = row
    touch(unit)
    return object_response(domain.serialize_actuator(row), 201)


@bp.get("/valve-mfg/actuator-packages")
def list_packages():
    require_roles(ANY)
    limit, offset = parse_pagination()
    rows = sort_rows(list(db.actuator_packages.values()))
    valve_unit_id = filter_value("valve_unit_id")
    sizing_status = filter_value("sizing_status")
    actuator_type = filter_value("actuator_type")
    if valve_unit_id is not None:
        rows = [r for r in rows if r["valve_unit_id"] == valve_unit_id]
    if sizing_status is not None:
        rows = [r for r in rows if r["sizing_status"] == sizing_status]
    if actuator_type is not None:
        rows = [r for r in rows if r["actuator_type"] == actuator_type]
    page, total = paginate(rows, limit, offset)
    return list_response(
        [domain.serialize_actuator(r) for r in page], limit, offset, total
    )


@bp.get("/valve-mfg/actuator-packages/<package_id>")
def get_package(package_id):
    require_roles(ANY)
    row = domain.find_actuator(package_id)
    return object_response(domain.serialize_actuator(row))


@bp.post("/valve-mfg/actuator-packages/<package_id>/decision")
def package_decision(package_id):
    user_id, role = require_roles(["QualityManager"])
    body = get_body()
    decision = get_enum(body, "decision", list(DECISION_ROLES.keys()))
    require_action_role(role, decision, DECISION_ROLES)

    package = domain.find_actuator(package_id)

    if package["sizing_status"] != "PROPOSED":
        raise api_error(
            "ERR_STATE_INVALID",
            "a sizing decision requires sizing_status PROPOSED (current: %s)"
            % package["sizing_status"],
        )

    if decision == "APPROVE":
        if package["actuator_type"] != "ELECTRIC" and dec(
            package["supply_pressure_bar"]
        ) <= dec(0):
            raise invalid(
                "a non-electric actuator requires supply_pressure_bar greater than zero"
            )
        if dec(package["output_torque_nm"]) < dec(package["sized_torque_nm"]):
            raise api_error(
                "ERR_ACTUATOR_TORQUE_INSUFFICIENT",
                "output_torque_nm is below the sized torque of %s Nm"
                % package["sized_torque_nm"],
            )
        package["sizing_status"] = "APPROVED"
        package["approved_by_user_id"] = user_id
        touch(package)
    else:
        package["sizing_status"] = "REJECTED"
        touch(package)

    return object_response(domain.serialize_actuator(package))
