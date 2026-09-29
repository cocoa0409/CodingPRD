"""Distributors, raw materials, press lines and the logical clock."""

import re

from flask import Blueprint, request

import calc
import cascades
from db import db, iso, new_row, serialize as _ser, set_clock, touch
from errors import ApiError
from middleware import authorize, find
from response import enum_filter, list_response, object_response, string_filter
from support import STATUS_CREATED, body, unique
from validate import field as F
from validate import invalid, validate

bp = Blueprint("masterdata", __name__)

TERRITORY = re.compile(r"^[A-Z]{2}$")

DISTRIBUTOR_STATUS = ("ACTIVE", "SUSPENDED")
MATERIAL_CATEGORY = ("VINYL_RESIN", "PLASTICIZER", "FILLER", "STABILIZER")
MATERIAL_STATUS = ("ACTIVE", "RESTRICTED", "DISCONTINUED")
LINE_TYPE = ("MULTI_DAY_PRESS", "CALENDER")
LINE_STATUS = ("AVAILABLE", "MAINTENANCE", "DOWN")

DISTRIBUTOR_READERS = ("PlantAdmin", "ProductionPlanner", "WarrantyAdjuster", "Distributor")
MATERIAL_READERS = ("PlantAdmin", "Formulator", "TechnicalDirector", "QaTechnician")
LINE_READERS = ("PlantAdmin", "ProductionPlanner", "QaTechnician")


# ---------------------------------------------------------------------------
# Distributor
# ---------------------------------------------------------------------------

DISTRIBUTOR_CREATE = [
    F("account_code", "string", required=True, min_len=3, max_len=32),
    F("name", "string", required=True),
    F("territory_code", "string", required=True, regex=TERRITORY),
    F("certified_installer_program", "boolean", default=False),
    F("status", "string", enum=DISTRIBUTOR_STATUS, default="ACTIVE"),
]


@bp.post("/distributors")
def create_distributor():
    authorize("PlantAdmin")
    data = validate(DISTRIBUTOR_CREATE, body())
    unique("distributors", "account_code", data["account_code"])
    row = new_row()
    row.update(data)
    db.distributors[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/distributors")
def list_distributors():
    authorize(*DISTRIBUTOR_READERS)
    status = enum_filter(request.args, "status", DISTRIBUTOR_STATUS)
    territory = string_filter(request.args, "territory_code")
    rows = [r for r in db.distributors.values()
            if (status is None or r["status"] == status)
            and (territory is None or r["territory_code"] == territory)]
    return list_response(rows, request.args, _ser)


@bp.get("/distributors/<row_id>")
def read_distributor(row_id):
    authorize(*DISTRIBUTOR_READERS)
    return object_response(_ser(find("distributors", row_id)))


# ---------------------------------------------------------------------------
# RawMaterial
# ---------------------------------------------------------------------------

MATERIAL_CREATE = [
    F("material_code", "string", required=True),
    F("name", "string", required=True),
    F("category", "string", required=True, enum=MATERIAL_CATEGORY),
    F("cost_per_kg_cents", "integer", required=True, min=1),
    F("indentation_index", "number", required=True, min=0, max=100, decimals=2),
    F("thermal_stability_index", "number", required=True, min=0, max=100, decimals=2),
    F("plasticizer_migration_index", "number", required=True, min=0, max=100, decimals=2),
    F("max_phr", "number", required=True, exclusive_min=0),
    F("status", "string", enum=MATERIAL_STATUS, default="ACTIVE"),
]


@bp.post("/raw-materials")
def create_material():
    authorize("PlantAdmin")
    data = validate(MATERIAL_CREATE, body())
    unique("raw_materials", "material_code", data["material_code"])
    row = new_row()
    row.update(data)
    db.raw_materials[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/raw-materials")
def list_materials():
    authorize(*MATERIAL_READERS)
    category = enum_filter(request.args, "category", MATERIAL_CATEGORY)
    status = enum_filter(request.args, "status", MATERIAL_STATUS)
    rows = [r for r in db.raw_materials.values()
            if (category is None or r["category"] == category)
            and (status is None or r["status"] == status)]
    return list_response(rows, request.args, _ser)


@bp.get("/raw-materials/<row_id>")
def read_material(row_id):
    authorize(*MATERIAL_READERS)
    return object_response(_ser(find("raw_materials", row_id)))


@bp.get("/raw-materials/<row_id>/formulation-components")
def list_material_components(row_id):
    authorize("PlantAdmin", "Formulator", "TechnicalDirector")
    material = find("raw_materials", row_id)
    rows = [c for c in db.formulation_components.values()
            if c["raw_material_id"] == material["id"]]
    return list_response(rows, request.args, _ser)


@bp.post("/raw-materials/<row_id>/status")
def material_status(row_id):
    authorize("PlantAdmin")
    data = validate([F("to_status", "string", required=True, enum=MATERIAL_STATUS)], body())
    material = find("raw_materials", row_id)
    material["status"] = data["to_status"]
    touch(material)
    if data["to_status"] == "RESTRICTED":
        cascades.raw_material_restricted(material)
    return object_response(_ser(material))


@bp.post("/raw-materials/<row_id>/cost")
def material_cost(row_id):
    authorize("PlantAdmin")
    data = validate([F("cost_per_kg_cents", "integer", required=True, min=1)], body())
    material = find("raw_materials", row_id)
    if material["status"] == "RESTRICTED":
        raise ApiError("ERR_RAW_MATERIAL_NOT_ACTIVE")
    material["cost_per_kg_cents"] = data["cost_per_kg_cents"]
    touch(material)
    for formulation in db.formulations.values():
        if formulation["cost_basis"] != "LIVE":
            continue
        if not any(c["formulation_id"] == formulation["id"]
                   and c["raw_material_id"] == material["id"]
                   for c in db.formulation_components.values()):
            continue
        calc.apply_blend_metrics(formulation)
        touch(formulation)
        cascades.refresh_pin_stale(formulation)
    return object_response(_ser(material))


# ---------------------------------------------------------------------------
# PressLine
# ---------------------------------------------------------------------------

LINE_CREATE = [
    F("line_code", "string", required=True),
    F("line_type", "string", required=True, enum=LINE_TYPE),
    F("min_thickness_mm", "number", required=True, exclusive_min=0),
    F("max_thickness_mm", "number", required=True, exclusive_min=0),
    F("changeover_minutes", "integer", required=True, min=0),
    F("curl_control_index", "number", required=True, min=0, max=100),
    F("status", "string", enum=LINE_STATUS, default="AVAILABLE"),
]


@bp.post("/press-lines")
def create_line():
    authorize("PlantAdmin")
    data = validate(LINE_CREATE, body())
    if data["max_thickness_mm"] <= data["min_thickness_mm"]:
        invalid()
    unique("press_lines", "line_code", data["line_code"])
    row = new_row()
    row.update(data)
    db.press_lines[row["id"]] = row
    return object_response(_ser(row), STATUS_CREATED)


@bp.get("/press-lines")
def list_lines():
    authorize(*LINE_READERS)
    status = enum_filter(request.args, "status", LINE_STATUS)
    line_type = enum_filter(request.args, "line_type", LINE_TYPE)
    rows = [r for r in db.press_lines.values()
            if (status is None or r["status"] == status)
            and (line_type is None or r["line_type"] == line_type)]
    return list_response(rows, request.args, _ser)


@bp.get("/press-lines/<row_id>")
def read_line(row_id):
    authorize(*LINE_READERS)
    return object_response(_ser(find("press_lines", row_id)))


@bp.post("/press-lines/<row_id>/status")
def line_status(row_id):
    authorize("PlantAdmin")
    data = validate([F("to_status", "string", required=True, enum=LINE_STATUS)], body())
    line = find("press_lines", row_id)
    line["status"] = data["to_status"]
    touch(line)
    return object_response(_ser(line))


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize("PlantAdmin")
    data = validate([F("current_utc", "datetime", required=True)], body())
    set_clock(data["current_utc"])
    return object_response({"current_utc": iso(data["current_utc"])})


__all__ = ["bp"]
