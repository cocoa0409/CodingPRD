"""Reference-data catalogues and the logical clock (PRD 3.1)."""

from flask import Blueprint

import serialize
from db import db, new_row, rows
from errors import ERR_DUPLICATE_CODE, fail
from middleware import ALL_ROLES, roles_required
from response import created, ok, ok_list
from services import (
    get_case_model,
    get_install_crew,
    get_part_inventory,
    recompute_part_availability,
)
from validation import (
    filter_value,
    get_body,
    opt_datetime,
    paginate,
    pagination,
    req_array,
    req_datetime,
    req_enum,
    req_int,
    req_number,
    req_string,
)

bp = Blueprint("catalog", __name__)

SYSTEM_TYPES = ["REMOTE", "SELF_CONTAINED"]
TEMPERATURE_CLASSES = ["HT", "MT", "LT"]
SAFETY_CLASSES = ["A1", "A2L", "A3"]
SYSTEM_TYPE_SCOPES = ["REMOTE", "SELF_CONTAINED", "ANY"]


def _unique(collection, field, value, scope_field=None, scope_value=None):
    for row in collection.values():
        if row.get(field) != value:
            continue
        if scope_field is not None and row.get(scope_field) != scope_value:
            continue
        fail(ERR_DUPLICATE_CODE, "%s '%s' already exists" % (field, value))


# --------------------------------------------------------------------------
@bp.post("/refrigerants")
@roles_required("PlatformAdmin")
def create_refrigerant():
    body = get_body()
    refrigerant_code = req_string(body, "refrigerant_code", 1, 32)
    trade_name = req_string(body, "trade_name")
    gwp_100yr = req_int(body, "gwp_100yr", minimum=1)
    safety_class = req_enum(body, "safety_class", SAFETY_CLASSES)
    max_charge_grams = req_int(body, "max_charge_grams", minimum=1)
    allowed_system_types = req_array(
        body, "allowed_system_types", allowed=SYSTEM_TYPES, non_empty=True
    )

    _unique(db.refrigerants, "refrigerant_code", refrigerant_code)

    row = new_row(common_fields=False)
    row.update({
        "refrigerant_code": refrigerant_code,
        "trade_name": trade_name,
        "gwp_100yr": gwp_100yr,
        "safety_class": safety_class,
        "max_charge_grams": max_charge_grams,
        "allowed_system_types": allowed_system_types,
    })
    db.refrigerants[row["id"]] = row
    return created(serialize.dump("Refrigerant", row))


@bp.post("/energy-standards")
@roles_required("PlatformAdmin", "ComplianceOfficer")
def create_energy_standard():
    body = get_body()
    standard_code = req_string(body, "standard_code", 1, 48)
    effective_raw, effective_dt = req_datetime(body, "effective_date")
    max_gwp = req_int(body, "max_gwp", minimum=1)
    coefficient_a = req_number(body, "limit_coefficient_a", exclusive_minimum=0)
    constant_b = req_number(body, "limit_constant_b", minimum=0)
    temperature_class = req_enum(body, "temperature_class", TEMPERATURE_CLASSES)
    system_type_scope = req_enum(body, "system_type_scope", SYSTEM_TYPE_SCOPES)

    _unique(db.energy_standards, "standard_code", standard_code)

    row = new_row(common_fields=False)
    row.update({
        "standard_code": standard_code,
        "effective_date": effective_raw,
        "_effective_date": effective_dt,
        "max_gwp": max_gwp,
        "limit_coefficient_a": coefficient_a,
        "limit_constant_b": constant_b,
        "temperature_class": temperature_class,
        "system_type_scope": system_type_scope,
    })
    db.energy_standards[row["id"]] = row
    return created(serialize.dump("EnergyStandard", row))


@bp.post("/test-chambers")
@roles_required("PlatformAdmin")
def create_test_chamber():
    body = get_body()
    chamber_code = req_string(body, "chamber_code", 1, 32)
    name = req_string(body, "name")
    supported = req_array(
        body, "supported_temperature_classes", allowed=TEMPERATURE_CLASSES, non_empty=True
    )
    turnaround_hours = req_int(body, "turnaround_hours", minimum=0)
    max_tda_sqft = req_number(body, "max_tda_sqft", exclusive_minimum=0)
    closed_start_raw, closed_start = opt_datetime(body, "closed_window_start")
    closed_end_raw, closed_end = opt_datetime(body, "closed_window_end")

    _unique(db.test_chambers, "chamber_code", chamber_code)

    row = new_row()
    row.update({
        "chamber_code": chamber_code,
        "name": name,
        "supported_temperature_classes": supported,
        "turnaround_hours": turnaround_hours,
        "max_tda_sqft": max_tda_sqft,
        "closed_window_start": closed_start_raw,
        "closed_window_end": closed_end_raw,
        "_closed_window_start": closed_start,
        "_closed_window_end": closed_end,
    })
    db.test_chambers[row["id"]] = row
    return created(serialize.dump("TestChamber", row))


@bp.post("/install-crews")
@roles_required("PlatformAdmin", "LogisticsCoordinator")
def create_install_crew():
    body = get_body()
    crew_code = req_string(body, "crew_code", 1, 32)
    contractor_name = req_string(body, "contractor_name")
    service_region_codes = req_array(body, "service_region_codes", non_empty=True)
    daily_case_capacity = req_int(body, "daily_case_capacity", minimum=1)

    _unique(db.install_crews, "crew_code", crew_code)

    row = new_row()
    row.update({
        "crew_code": crew_code,
        "contractor_name": contractor_name,
        "service_region_codes": service_region_codes,
        "daily_case_capacity": daily_case_capacity,
        "committed_case_days": 0,
    })
    db.install_crews[row["id"]] = row
    return created(serialize.dump("InstallCrew", row))


@bp.get("/install-crews/<crew_id>")
@roles_required(*ALL_ROLES)
def read_install_crew(crew_id):
    return ok(serialize.dump("InstallCrew", get_install_crew(crew_id)))


@bp.post("/part-inventories")
@roles_required("PlatformAdmin", "ServiceManager")
def create_part_inventory():
    body = get_body()
    part_number = req_string(body, "part_number")
    description = req_string(body, "description")
    case_model_id = req_string(body, "case_model_id")
    region_code = req_string(body, "region_code")
    on_hand_qty = req_int(body, "on_hand_qty", minimum=0)
    unit_cost_cents = req_int(body, "unit_cost_cents", minimum=0)
    min_stock_qty = req_int(body, "min_stock_qty", minimum=0)

    get_case_model(case_model_id)  # rank 6

    _unique(db.part_inventories, "part_number", part_number, "region_code", region_code)

    row = new_row()
    row.update({
        "part_number": part_number,
        "description": description,
        "case_model_id": case_model_id,
        "region_code": region_code,
        "on_hand_qty": on_hand_qty,
        "reserved_qty": 0,
        "unit_cost_cents": unit_cost_cents,
        "min_stock_qty": min_stock_qty,
    })
    recompute_part_availability(row)
    db.part_inventories[row["id"]] = row
    return created(serialize.dump("PartInventory", row))


@bp.get("/part-inventories/<part_id>")
@roles_required(*ALL_ROLES)
def read_part_inventory(part_id):
    return ok(serialize.dump("PartInventory", get_part_inventory(part_id)))


@bp.get("/part-inventories")
@roles_required(*ALL_ROLES)
def list_part_inventories():
    limit, offset = pagination()
    case_model_id = filter_value("case_model_id")
    region_code = filter_value("region_code")

    items = rows(db.part_inventories)
    if case_model_id is not None:
        items = [r for r in items if r["case_model_id"] == case_model_id]
    if region_code is not None:
        items = [r for r in items if r["region_code"] == region_code]

    page, total = paginate(items, limit, offset)
    return ok_list(serialize.dump_many("PartInventory", page), limit, offset, total)


@bp.post("/_clock/set_current_utc")
@roles_required("PlatformAdmin")
def set_clock():
    body = get_body()
    _raw, instant = req_datetime(body, "to_iso8601")
    db.clock = instant
    return ok({})
