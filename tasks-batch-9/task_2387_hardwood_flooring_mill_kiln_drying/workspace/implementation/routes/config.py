"""Configuration surface: the logical clock, species profiles, drying schedules,
kiln chambers, product lines, core stock and prefinish lines (PRD 3.1)."""

from flask import Blueprint

from db import db, insert, iso, touch
from errors import ApiError
from middleware import (ALL_ROLES, KILN_OPERATOR, MILL_ADMIN, MILL_SUPERVISOR, authorize)
from response import array_response, object_response, paginate
from serializers import serialize, serialize_many
from services import calc, lookup, mill
from validation import (body_json, pagination, query_enum, query_str, req_datetime,
                        req_decimal, req_enum, req_int, req_ref, req_str)

bp = Blueprint("config", __name__)

DENSITY_CLASSES = ("DENSE", "MEDIUM", "SOFT")
CONSTRUCTION_TYPES = ("SOLID", "ENGINEERED")
CORE_MATERIALS = ("BIRCH_PLY", "HDF", "EUCALYPTUS_PLY")
CHAMBER_STATUSES = ("AVAILABLE", "OCCUPIED", "MAINTENANCE")
POSTURES = ("OPEN", "RESTRICTED", "FROZEN")


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@authorize(*ALL_ROLES)
def set_current_utc():
    body = body_json()
    instant = req_datetime(body, "current_utc")
    db.current_utc = instant
    return object_response({"current_utc": iso(instant)})


# --------------------------------------------------------------------------
# Species profiles
# --------------------------------------------------------------------------
@bp.post("/mill/species-profiles")
@authorize(MILL_ADMIN)
def create_species_profile():
    body = body_json()
    species_code = req_str(body, "species_code")
    common_name = req_str(body, "common_name")
    density_class = req_enum(body, "density_class", DENSITY_CLASSES)
    coefficient = req_decimal(body, "tangential_shrinkage_coefficient")
    target_moisture_pct = req_decimal(body, "target_moisture_pct")
    max_moisture_gradient_pp = req_decimal(body, "max_moisture_gradient_pp")

    if lookup.code_taken(db.species_profiles, "species_code", species_code):
        raise ApiError("ERR_DUPLICATE_CODE")

    record = insert(db.species_profiles, {
        "species_code": species_code,
        "common_name": common_name,
        "density_class": density_class,
        "tangential_shrinkage_coefficient": coefficient,
        "target_moisture_pct": target_moisture_pct,
        "max_moisture_gradient_pp": max_moisture_gradient_pp,
        "green_to_dry_shrink_pct": calc.GREEN_TO_DRY_SHRINK_PCT[density_class],
    })
    return object_response(serialize("species_profile", record), 201)


@bp.get("/mill/species-profiles/<species_profile_id>")
@authorize(*ALL_ROLES)
def get_species_profile(species_profile_id):
    return object_response(serialize("species_profile", lookup.species_profile(species_profile_id)))


@bp.get("/mill/species-profiles")
@authorize(*ALL_ROLES)
def list_species_profiles():
    limit, offset = pagination()
    density_class = query_enum("density_class", DENSITY_CLASSES)
    rows = lookup.filtered(db.species_profiles, [("density_class", density_class)])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("species_profile", page), limit, offset, total)


# --------------------------------------------------------------------------
# Drying schedules
# --------------------------------------------------------------------------
@bp.post("/mill/drying-schedules")
@authorize(MILL_ADMIN, KILN_OPERATOR)
def create_drying_schedule():
    body = body_json()
    species_profile_id = req_ref(body, "species_profile_id")
    schedule_code = req_str(body, "schedule_code")
    thickness_in = req_decimal(body, "thickness_in")
    initial_moisture_pct = req_decimal(body, "initial_moisture_pct")
    final_moisture_pct = req_decimal(body, "final_moisture_pct")
    conditioning_hours = req_int(body, "conditioning_hours")
    stress_relief_hours = req_int(body, "stress_relief_hours")
    expected_version = req_int(body, "expected_species_profile_version")

    profile = lookup.species_profile(species_profile_id)

    if expected_version != int(profile["version"]):
        raise ApiError("ERR_STALE_SPECIES_PROFILE_VERSION")

    if lookup.code_taken(db.drying_schedules, "schedule_code", schedule_code):
        raise ApiError("ERR_DUPLICATE_CODE")

    planned_dry_hours = calc.kiln_schedule_duration(
        profile["density_class"], thickness_in, initial_moisture_pct,
        final_moisture_pct, conditioning_hours, stress_relief_hours,
    )

    record = insert(db.drying_schedules, {
        "species_profile_id": species_profile_id,
        "schedule_code": schedule_code,
        "thickness_in": thickness_in,
        "initial_moisture_pct": initial_moisture_pct,
        "final_moisture_pct": final_moisture_pct,
        "conditioning_hours": conditioning_hours,
        "stress_relief_hours": stress_relief_hours,
        "planned_dry_hours": planned_dry_hours,
    })
    touch(profile)
    return object_response(serialize("drying_schedule", record), 201)


@bp.get("/mill/drying-schedules/<drying_schedule_id>")
@authorize(*ALL_ROLES)
def get_drying_schedule(drying_schedule_id):
    return object_response(serialize("drying_schedule", lookup.drying_schedule(drying_schedule_id)))


@bp.get("/mill/drying-schedules")
@authorize(*ALL_ROLES)
def list_drying_schedules():
    limit, offset = pagination()
    species_profile_id = query_str("species_profile_id")
    rows = lookup.filtered(db.drying_schedules, [("species_profile_id", species_profile_id)])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("drying_schedule", page), limit, offset, total)


# --------------------------------------------------------------------------
# Kiln chambers
# --------------------------------------------------------------------------
@bp.post("/mill/kiln-chambers")
@authorize(MILL_ADMIN)
def create_kiln_chamber():
    body = body_json()
    chamber_code = req_str(body, "chamber_code")
    capacity_board_feet = req_int(body, "capacity_board_feet")

    if lookup.code_taken(db.kiln_chambers, "chamber_code", chamber_code):
        raise ApiError("ERR_DUPLICATE_CODE")

    record = insert(db.kiln_chambers, {
        "chamber_code": chamber_code,
        "capacity_board_feet": capacity_board_feet,
        "maintenance_note": None,
        "status": "AVAILABLE",
    })
    return object_response(serialize("kiln_chamber", record), 201)


@bp.get("/mill/kiln-chambers/<kiln_chamber_id>")
@authorize(*ALL_ROLES)
def get_kiln_chamber(kiln_chamber_id):
    return object_response(serialize("kiln_chamber", lookup.kiln_chamber(kiln_chamber_id)))


@bp.get("/mill/kiln-chambers")
@authorize(*ALL_ROLES)
def list_kiln_chambers():
    limit, offset = pagination()
    status = query_enum("status", CHAMBER_STATUSES)
    rows = lookup.filtered(db.kiln_chambers, [("status", status)])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("kiln_chamber", page), limit, offset, total)


@bp.post("/mill/kiln-chambers/<kiln_chamber_id>/start_maintenance")
@authorize(KILN_OPERATOR, MILL_ADMIN)
def start_maintenance(kiln_chamber_id):
    body = body_json()
    maintenance_note = req_str(body, "maintenance_note")
    chamber = lookup.kiln_chamber(kiln_chamber_id)
    if chamber["status"] != "AVAILABLE":
        raise ApiError("ERR_CHAMBER_STATE_INVALID")
    chamber["status"] = "MAINTENANCE"
    chamber["maintenance_note"] = maintenance_note
    touch(chamber)
    return object_response(serialize("kiln_chamber", chamber))


@bp.post("/mill/kiln-chambers/<kiln_chamber_id>/complete_maintenance")
@authorize(KILN_OPERATOR, MILL_ADMIN)
def complete_maintenance(kiln_chamber_id):
    body_json()
    chamber = lookup.kiln_chamber(kiln_chamber_id)
    if chamber["status"] != "MAINTENANCE":
        raise ApiError("ERR_CHAMBER_STATE_INVALID")
    chamber["status"] = "AVAILABLE"
    chamber["maintenance_note"] = None
    touch(chamber)
    return object_response(serialize("kiln_chamber", chamber))


# --------------------------------------------------------------------------
# Product lines
# --------------------------------------------------------------------------
@bp.post("/mill/product-lines")
@authorize(MILL_ADMIN)
def create_product_line():
    body = body_json()
    line_code = req_str(body, "line_code")
    species_profile_id = req_ref(body, "species_profile_id")
    construction_type = req_enum(body, "construction_type", CONSTRUCTION_TYPES)
    nominal_width_in = req_decimal(body, "nominal_width_in")
    nominal_thickness_in = req_decimal(body, "nominal_thickness_in")
    material_value_cents_per_sf = req_int(body, "material_value_cents_per_sf")
    warranty_funded_total_cents = req_int(body, "warranty_funded_total_cents")

    lookup.species_profile(species_profile_id)

    if lookup.code_taken(db.product_lines, "line_code", line_code):
        raise ApiError("ERR_DUPLICATE_CODE")

    record = insert(db.product_lines, {
        "line_code": line_code,
        "species_profile_id": species_profile_id,
        "construction_type": construction_type,
        "nominal_width_in": nominal_width_in,
        "nominal_thickness_in": nominal_thickness_in,
        "material_value_cents_per_sf": material_value_cents_per_sf,
        "warranty_funded_total_cents": warranty_funded_total_cents,
        "warranty_balance_cents": warranty_funded_total_cents,
        "warranty_committed_cents": 0,
        "freeze_override": False,
        "posture": "OPEN",
    })
    mill.recompute_posture(record)
    return object_response(serialize("product_line", record), 201)


@bp.get("/mill/product-lines/<product_line_id>")
@authorize(*ALL_ROLES)
def get_product_line(product_line_id):
    return object_response(serialize("product_line", lookup.product_line(product_line_id)))


@bp.get("/mill/product-lines")
@authorize(*ALL_ROLES)
def list_product_lines():
    limit, offset = pagination()
    species_profile_id = query_str("species_profile_id")
    posture = query_enum("posture", POSTURES)
    construction_type = query_enum("construction_type", CONSTRUCTION_TYPES)
    rows = lookup.filtered(db.product_lines, [
        ("species_profile_id", species_profile_id),
        ("posture", posture),
        ("construction_type", construction_type),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("product_line", page), limit, offset, total)


@bp.post("/mill/product-lines/<product_line_id>/fund_warranty")
@authorize(MILL_ADMIN)
def fund_warranty(product_line_id):
    body = body_json()
    amount_cents = req_int(body, "amount_cents")
    line = lookup.product_line(product_line_id)
    line["warranty_funded_total_cents"] = int(line["warranty_funded_total_cents"]) + amount_cents
    mill.recompute_posture(line)
    touch(line)
    return object_response(serialize("product_line", line))


@bp.post("/mill/product-lines/<product_line_id>/freeze")
@authorize(MILL_ADMIN)
def freeze_product_line(product_line_id):
    body = body_json()
    freeze_reason = req_str(body, "freeze_reason")
    line = lookup.product_line(product_line_id)
    previous_posture = line["posture"]
    line["freeze_override"] = True
    mill.recompute_posture(line)
    touch(line)
    if previous_posture == "OPEN":
        mill.hold_scheduled_prefinish_runs(
            line, "Product line frozen: %s" % freeze_reason)
    return object_response(serialize("product_line", line))


@bp.post("/mill/product-lines/<product_line_id>/unfreeze")
@authorize(MILL_ADMIN)
def unfreeze_product_line(product_line_id):
    body_json()
    line = lookup.product_line(product_line_id)
    line["freeze_override"] = False
    mill.recompute_posture(line)
    touch(line)
    return object_response(serialize("product_line", line))


# --------------------------------------------------------------------------
# Core stock
# --------------------------------------------------------------------------
@bp.post("/mill/core-stocks")
@authorize(MILL_ADMIN, MILL_SUPERVISOR)
def create_core_stock():
    body = body_json()
    product_line_id = req_ref(body, "product_line_id")
    core_material = req_enum(body, "core_material", CORE_MATERIALS)
    lot_reference = req_str(body, "lot_reference")
    available_square_feet = req_decimal(body, "available_square_feet")

    lookup.product_line(product_line_id)

    record = insert(db.core_stocks, {
        "product_line_id": product_line_id,
        "core_material": core_material,
        "lot_reference": lot_reference,
        "available_square_feet": available_square_feet,
        "reserved_square_feet": calc.rhu(0, 2),
    })
    return object_response(serialize("core_stock", record), 201)


@bp.get("/mill/core-stocks/<core_stock_id>")
@authorize(*ALL_ROLES)
def get_core_stock(core_stock_id):
    return object_response(serialize("core_stock", lookup.core_stock(core_stock_id)))


@bp.get("/mill/core-stocks")
@authorize(*ALL_ROLES)
def list_core_stocks():
    limit, offset = pagination()
    product_line_id = query_str("product_line_id")
    core_material = query_enum("core_material", CORE_MATERIALS)
    rows = lookup.filtered(db.core_stocks, [
        ("product_line_id", product_line_id),
        ("core_material", core_material),
    ])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("core_stock", page), limit, offset, total)


# --------------------------------------------------------------------------
# Prefinish lines
# --------------------------------------------------------------------------
@bp.post("/mill/prefinish-lines")
@authorize(MILL_ADMIN)
def create_prefinish_line():
    body = body_json()
    line_code = req_str(body, "line_code")
    daily_capacity_linear_feet = req_int(body, "daily_capacity_linear_feet")
    coating_passes = req_int(body, "coating_passes")

    if lookup.code_taken(db.prefinish_lines, "line_code", line_code):
        raise ApiError("ERR_DUPLICATE_CODE")

    record = insert(db.prefinish_lines, {
        "line_code": line_code,
        "daily_capacity_linear_feet": daily_capacity_linear_feet,
        "coating_passes": coating_passes,
    })
    return object_response(serialize("prefinish_line", record), 201)


@bp.get("/mill/prefinish-lines/<prefinish_line_id>")
@authorize(*ALL_ROLES)
def get_prefinish_line(prefinish_line_id):
    return object_response(serialize("prefinish_line", lookup.prefinish_line(prefinish_line_id)))


@bp.get("/mill/prefinish-lines")
@authorize(*ALL_ROLES)
def list_prefinish_lines():
    limit, offset = pagination()
    rows = lookup.filtered(db.prefinish_lines, [])
    page, total = paginate(rows, limit, offset)
    return array_response(serialize_many("prefinish_line", page), limit, offset, total)
