"""Shared catalogs: process technologies, material specs, test bays."""
from decimal import Decimal

from flask import Blueprint

import auth
import constants as C
import db
import domain
import response
import serialize
import validate
from errors import fail
from util import D

bp = Blueprint("catalogs", __name__)


def _unique_code(tablename, field, value):
    for row in db.all_rows(tablename):
        if row[field] == value:
            fail("ERR_DUPLICATE_CATALOG_CODE",
                 "%s %s already exists" % (field, value))


# ------------------------------------------------------ process technologies --

@bp.post("/process-technologies")
def create_technology():
    auth.require("PlatformAdmin")
    body = validate.body()
    code = validate.string(body, "code", max_length=80)
    name = validate.string(body, "name", max_length=160)
    role = validate.enum(body, "role", C.TECHNOLOGY_ROLES)
    max_feed_turbidity = validate.number(body, "max_feed_turbidity_ntu", minimum=0)
    max_feed_tds = validate.number(body, "max_feed_tds_mg_l", minimum=0)
    min_flow = validate.number(body, "min_design_flow_mgd", minimum=0)
    max_flow = validate.number(body, "max_design_flow_mgd", minimum=0)
    unit_capex = validate.number(body, "unit_capex_cents_per_mgd", exclusive_minimum=0)
    energy = validate.number(body, "energy_kwh_per_mg", minimum=0)
    footprint = validate.number(body, "footprint_sf_per_mgd", exclusive_minimum=0)
    requires_code_stamp = validate.enum(
        body, "requires_code_stamp", C.CODE_STAMPS, required=False, default="NONE")
    service_class = validate.enum(body, "chemical_service_class", C.SERVICE_CLASSES)
    consumable_item_code = validate.string(
        body, "consumable_item_code", required=False, default=None, max_length=80)
    status = validate.enum(
        body, "status", C.CATALOG_STATUSES, required=False, default="ACTIVE")
    if max_flow < min_flow:
        fail("ERR_INVALID_REQUEST",
             "max_design_flow_mgd must be >= min_design_flow_mgd")

    _unique_code("process_technologies", "code", code)

    row = db.new_row("process_technologies")
    row.update({
        "code": code,
        "name": name,
        "role": role,
        "max_feed_turbidity_ntu": max_feed_turbidity,
        "max_feed_tds_mg_l": max_feed_tds,
        "min_design_flow_mgd": min_flow,
        "max_design_flow_mgd": max_flow,
        "unit_capex_cents_per_mgd": unit_capex,
        "energy_kwh_per_mg": energy,
        "footprint_sf_per_mgd": footprint,
        "requires_code_stamp": requires_code_stamp,
        "chemical_service_class": service_class,
        "consumable_item_code": consumable_item_code,
        "status": status,
    })
    db.insert("process_technologies", row)
    return response.created(serialize.row(row))


@bp.get("/process-technologies")
def list_technologies():
    auth.require(*auth.ROLES)
    role = validate.enum_filter("role", C.TECHNOLOGY_ROLES)
    status = validate.enum_filter("status", C.CATALOG_STATUSES)
    rows = db.all_rows("process_technologies")
    if role:
        rows = [r for r in rows if r["role"] == role]
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("code", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/process-technologies/<technology_id>")
def get_technology(technology_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.load("process_technologies", technology_id)))


# ------------------------------------------------------------- material specs --

@bp.post("/material-specs")
def create_material():
    auth.require("PlatformAdmin")
    body = validate.body()
    code = validate.string(body, "code", max_length=80)
    max_chloride = validate.number(body, "max_chloride_ppm", minimum=0)
    max_temp = validate.number(body, "max_temp_c")
    max_pressure = validate.number(body, "max_pressure_psig", exclusive_minimum=0)
    ph_min = validate.number(body, "ph_min", minimum=0, maximum=14)
    ph_max = validate.number(body, "ph_max", minimum=0, maximum=14)
    asme = validate.boolean(body, "asme_u_capable", default=False)
    nsf = validate.boolean(body, "nsf61_certified", default=False)
    awwa = validate.boolean(body, "awwa_compliant", default=False)
    cost_index = validate.number(body, "cost_index", minimum=1, places=2)
    classes = validate.array(body, "service_classes_allowed", min_length=1)
    for item in classes:
        if not isinstance(item, str) or item not in C.SERVICE_CLASSES:
            fail("ERR_INVALID_REQUEST",
                 "service_classes_allowed entries must be one of %s"
                 % ", ".join(C.SERVICE_CLASSES))
    if ph_max < ph_min:
        fail("ERR_INVALID_REQUEST", "ph_max must be >= ph_min")

    _unique_code("material_specs", "code", code)

    row = db.new_row("material_specs")
    row.update({
        "code": code,
        "max_chloride_ppm": max_chloride,
        "max_temp_c": max_temp,
        "max_pressure_psig": max_pressure,
        "ph_min": ph_min,
        "ph_max": ph_max,
        "asme_u_capable": asme,
        "nsf61_certified": nsf,
        "awwa_compliant": awwa,
        "cost_index": cost_index,
        "service_classes_allowed": list(classes),
    })
    db.insert("material_specs", row)
    return response.created(serialize.row(row))


@bp.get("/material-specs")
def list_materials():
    auth.require(*auth.ROLES)
    rows = db.sorted_rows(db.all_rows("material_specs"), [("code", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/material-specs/<material_spec_id>")
def get_material(material_spec_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.load("material_specs", material_spec_id)))


# ------------------------------------------------------------------ test bays --

@bp.post("/test-bays")
def create_bay():
    auth.require("PlatformAdmin")
    body = validate.body()
    bay_code = validate.string(body, "bay_code", max_length=80)
    max_footprint = validate.number(body, "max_skid_footprint_sf", exclusive_minimum=0)
    buffer_minutes = validate.integer(
        body, "changeover_buffer_minutes", required=False, default=120, minimum=0)
    crane = validate.number(body, "crane_capacity_tons", exclusive_minimum=0)
    status = validate.enum(
        body, "status", C.BAY_STATUSES, required=False, default="AVAILABLE")

    _unique_code("test_bays", "bay_code", bay_code)

    row = db.new_row("test_bays")
    row.update({
        "bay_code": bay_code,
        "max_skid_footprint_sf": max_footprint,
        "changeover_buffer_minutes": buffer_minutes,
        "crane_capacity_tons": crane,
        "reserved_footprint_minutes": Decimal("0.00"),
        "status": status,
    })
    db.insert("test_bays", row)
    return response.created(serialize.row(row))


@bp.get("/test-bays")
def list_bays():
    auth.require(*auth.ROLES)
    status = validate.enum_filter("status", C.BAY_STATUSES)
    rows = db.all_rows("test_bays")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows = db.sorted_rows(rows, [("bay_code", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/test-bays/<bay_id>")
def get_bay(bay_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.load("test_bays", bay_id)))
