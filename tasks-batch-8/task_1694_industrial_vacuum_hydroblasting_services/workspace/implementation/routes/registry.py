"""Fleet and crew registries: equipment units and operators (PRD 3.2)."""

from flask import Blueprint, request

from db import store
from errors import not_found
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from util import get_body, list_paginated, new_entity, req_field

bp = Blueprint("registry", __name__)

UNIT_TYPES = ["VAC_TRUCK", "HYDROBLASTER", "COMBO"]


@bp.post("/v1/equipment-units")
def create_equipment_unit():
    require_roles(["PlatformAdmin"])
    body = get_body()
    unit_code = req_field(body, "unit_code")
    unit_type = req_field(body, "unit_type", choices=UNIT_TYPES)
    max_pressure_psi = req_field(body, "max_pressure_psi", kind="int", gte_zero=True)
    tank_capacity_gal = req_field(body, "tank_capacity_gal", kind="int", gte_zero=True)
    unit = new_entity(store.equipment_units, {
        "unit_code": unit_code,
        "unit_type": unit_type,
        "max_pressure_psi": max_pressure_psi,
        "tank_capacity_gal": tank_capacity_gal,
    })
    return success_object(unit, status=201)


@bp.get("/v1/equipment-units")
def list_equipment_units():
    require_roles(ALL_ROLES)
    filters = {}
    if request.args.get("unit_type") is not None:
        filters["unit_type"] = request.args["unit_type"]
    page, limit, offset, total = list_paginated(store.equipment_units, filters,
                                                request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/equipment-units/<unitId>")
def get_equipment_unit(unitId):
    require_roles(ALL_ROLES)
    unit = store.equipment_units.get(unitId)
    if unit is None:
        raise not_found("Equipment unit not found")
    return success_object(unit)


@bp.post("/v1/operators")
def create_operator():
    require_roles(["PlatformAdmin"])
    body = get_body()
    full_name = req_field(body, "full_name")
    employee_ref = req_field(body, "employee_ref")
    hazwoper = req_field(body, "hazwoper_expires_on", kind="date")
    hydroblast_certified = req_field(body, "hydroblast_certified", kind="bool")
    operator = new_entity(store.operators, {
        "full_name": full_name,
        "employee_ref": employee_ref,
        "hazwoper_expires_on": hazwoper.isoformat(),
        "hydroblast_certified": hydroblast_certified,
    })
    return success_object(operator, status=201)


@bp.get("/v1/operators")
def list_operators():
    require_roles(ALL_ROLES)
    page, limit, offset, total = list_paginated(store.operators, {}, request.args)
    return success_list(page, limit, offset, total)


@bp.get("/v1/operators/<operatorId>")
def get_operator(operatorId):
    require_roles(ALL_ROLES)
    operator = store.operators.get(operatorId)
    if operator is None:
        raise not_found("Operator not found")
    return success_object(operator)
