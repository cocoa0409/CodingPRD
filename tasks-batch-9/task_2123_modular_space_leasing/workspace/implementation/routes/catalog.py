"""Branches, jurisdictions, building specs, floorplan configurations, units."""
from flask import Blueprint

import calc
import serializers as S
import services
from db import store, new_record, touch, ordered
from errors import ApiError
from guard import (auth, lookup, get_body, resolve_fk, v_string, v_int, v_number,
                   v_bool, v_enum)
from response import success, created, paginate

bp = Blueprint("catalog", __name__)

ANCHORING = ("NONE", "GROUND_ANCHOR", "PIER_FOUNDATION", "ENGINEERED_SLAB")
GRADES = ("A", "B", "C", "D")


# ---------------------------------------------------------------- Branch

@bp.post("/branches")
def create_branch():
    auth("FleetAdmin")
    body = get_body()
    name = v_string(body, "name")
    region_code = v_string(body, "region_code")
    yard_capacity_units = v_int(body, "yard_capacity_units", minimum=1)
    daily_dispatch_capacity = v_int(body, "daily_dispatch_capacity", minimum=1)
    labor_rate = v_int(body, "labor_rate_cents_per_hour", minimum=0)
    status = v_enum(body, "status", ("OPERATIONAL", "SUSPENDED"), required=False, default="OPERATIONAL")

    record = new_record(
        name=name,
        region_code=region_code,
        yard_capacity_units=yard_capacity_units,
        daily_dispatch_capacity=daily_dispatch_capacity,
        labor_rate_cents_per_hour=labor_rate,
        status=status,
        units_in_yard=0,
        units_available=0,
        utilization_pct=calc.D("0.00"),
    )
    store.branches[record["id"]] = record
    return created(S.branch(record))


@bp.get("/branches/<branch_id>")
def read_branch(branch_id):
    auth("FleetAdmin", "BranchOps", "LeasingAgent")
    record = lookup(store.branches, branch_id, "ERR_BRANCH_NOT_FOUND")
    return success(S.branch(record))


# ---------------------------------------------------------------- Jurisdiction

@bp.post("/jurisdictions")
def create_jurisdiction():
    auth("FleetAdmin")
    body = get_body()
    code = v_string(body, "code")
    name = v_string(body, "name")
    permit_required = v_bool(body, "permit_required")
    permit_lead_days = v_int(body, "permit_lead_days", minimum=0)
    anchoring_standard = v_enum(body, "anchoring_standard", ANCHORING)
    wind_zone = v_int(body, "wind_zone", choices=(1, 2, 3, 4))
    permit_fee_cents = v_int(body, "permit_fee_cents", minimum=0)
    ada_ramp_required = v_bool(body, "ada_ramp_required")
    min_ramp_run_ratio = v_number(body, "min_ramp_run_ratio", exclusive_minimum=0)

    # rank 16 -- identifier uniqueness
    if any(j["code"] == code for j in store.jurisdictions.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "Jurisdiction code %r already exists." % code)

    record = new_record(
        code=code,
        name=name,
        permit_required=permit_required,
        permit_lead_days=permit_lead_days,
        anchoring_standard=anchoring_standard,
        wind_zone=wind_zone,
        permit_fee_cents=permit_fee_cents,
        ada_ramp_required=ada_ramp_required,
        min_ramp_run_ratio=min_ramp_run_ratio,
    )
    store.jurisdictions[record["id"]] = record
    return created(S.jurisdiction(record))


# ---------------------------------------------------------------- BuildingSpec

@bp.post("/building-specs")
def create_building_spec():
    auth("FleetAdmin")
    body = get_body()
    model_code = v_string(body, "model_code")
    width_ft = v_number(body, "width_ft", exclusive_minimum=0)
    length_ft = v_number(body, "length_ft", exclusive_minimum=0)
    sections = v_int(body, "sections", minimum=1, maximum=4)
    floor_height_in = v_number(body, "floor_height_in", minimum=0)
    base_monthly_rate_cents = v_int(body, "base_monthly_rate_cents", minimum=0)
    delivery_base_cents = v_int(body, "delivery_base_cents", minimum=0)
    install_base_cents = v_int(body, "install_base_cents", minimum=0)
    replacement_value_cents = v_int(body, "replacement_value_cents", minimum=0)
    max_occupancy = v_int(body, "max_occupancy", minimum=1)

    if any(s["model_code"] == model_code for s in store.building_specs.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "Model code %r already exists." % model_code)

    record = new_record(
        model_code=model_code,
        width_ft=width_ft,
        length_ft=length_ft,
        sections=sections,
        floor_height_in=floor_height_in,
        base_monthly_rate_cents=base_monthly_rate_cents,
        delivery_base_cents=delivery_base_cents,
        install_base_cents=install_base_cents,
        replacement_value_cents=replacement_value_cents,
        max_occupancy=max_occupancy,
        floor_area_sqft=calc.building_spec_area(width_ft, length_ft),
    )
    store.building_specs[record["id"]] = record
    return created(S.building_spec(record))


@bp.get("/building-specs/<spec_id>")
def read_building_spec(spec_id):
    auth("FleetAdmin", "LeasingAgent")
    record = lookup(store.building_specs, spec_id, "ERR_BUILDING_SPEC_NOT_FOUND")
    return success(S.building_spec(record))


# ---------------------------------------------------- FloorplanConfiguration

@bp.post("/floorplan-configurations")
def create_config():
    auth("FleetAdmin")
    body = get_body()
    spec = resolve_fk(body, "building_spec_id", store.building_specs, "ERR_BUILDING_SPEC_NOT_FOUND")

    building_spec_id = v_string(body, "building_spec_id")
    name = v_string(body, "name")
    private_offices = v_int(body, "private_offices", minimum=0)
    restrooms = v_int(body, "restrooms", minimum=0)
    partition_linear_ft = v_number(body, "partition_linear_ft", minimum=0)
    hvac_tons = v_number(body, "hvac_tons", minimum=0)

    surcharge = calc.floorplan_config_surcharge(
        private_offices, restrooms, partition_linear_ft, hvac_tons, spec["floor_area_sqft"])

    record = new_record(
        building_spec_id=building_spec_id,
        name=name,
        private_offices=private_offices,
        restrooms=restrooms,
        partition_linear_ft=partition_linear_ft,
        hvac_tons=hvac_tons,
        config_surcharge_cents=surcharge,
        status="DRAFT",
    )
    store.configs[record["id"]] = record
    return created(S.config(record))


@bp.get("/floorplan-configurations/<config_id>")
def read_config(config_id):
    auth("FleetAdmin", "LeasingAgent")
    record = lookup(store.configs, config_id, "ERR_CONFIG_NOT_FOUND")
    return success(S.config(record))


@bp.get("/floorplan-configurations")
def list_configs():
    auth("FleetAdmin", "LeasingAgent")
    records = ordered(store.configs.values())
    records = services.apply_filters(records, {
        "building_spec_id": "building_spec_id",
        "status": "status",
    })
    return paginate(records, S.config)


@bp.post("/floorplan-configurations/<config_id>/publish")
def publish_config(config_id):
    auth("FleetAdmin")
    record = lookup(store.configs, config_id, "ERR_CONFIG_NOT_FOUND")
    if record["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT configuration may be published.")
    record["status"] = "PUBLISHED"
    touch(record)
    return success(S.config(record))


# ---------------------------------------------------------------- Unit

@bp.post("/units")
def create_unit():
    auth("FleetAdmin")
    body = get_body()
    # rank 4 -- body foreign keys in the declared field order
    resolve_fk(body, "building_spec_id", store.building_specs, "ERR_BUILDING_SPEC_NOT_FOUND")
    branch = resolve_fk(body, "current_branch_id", store.branches, "ERR_BRANCH_NOT_FOUND")

    serial_number = v_string(body, "serial_number")
    building_spec_id = v_string(body, "building_spec_id")
    current_branch_id = v_string(body, "current_branch_id")
    condition_grade = v_enum(body, "condition_grade", GRADES, required=False, default="A")

    if any(u["serial_number"] == serial_number for u in store.units.values()):
        raise ApiError("ERR_DUPLICATE_IDENTIFIER", "Serial number %r already exists." % serial_number)

    record = new_record(
        serial_number=serial_number,
        building_spec_id=building_spec_id,
        current_branch_id=current_branch_id,
        installed_config_id=None,
        status="IN_FLEET",
        condition_grade=condition_grade,
        lifetime_relocations=0,
        refurb_cycles=0,
        accumulated_damage_cents=0,
        latest_quote_estimate_cents=0,
    )
    store.units[record["id"]] = record
    services.recompute_branch(branch)
    return created(S.unit(record))


@bp.get("/units/<unit_id>")
def read_unit(unit_id):
    auth("FleetAdmin", "BranchOps", "LeasingAgent")
    record = lookup(store.units, unit_id, "ERR_UNIT_NOT_FOUND")
    return success(S.unit(record))


@bp.get("/units")
def list_units():
    auth("FleetAdmin", "BranchOps", "LeasingAgent")
    records = ordered(store.units.values())
    records = services.apply_filters(records, {
        "current_branch_id": "current_branch_id",
        "building_spec_id": "building_spec_id",
        "installed_config_id": "installed_config_id",
        "status": "status",
    })
    return paginate(records, S.unit)
