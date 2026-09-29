"""Logical clock and plant reference data: models, parts, benches, loaners."""
from flask import Blueprint

import calc
import db
import helpers
import serialize
import validate
from auth import PLANT_ROLES, authorize
from db import touch
from errors import ApiError
from response import ok
from util import iso

bp = Blueprint("reference", __name__)


# --- logical clock (PRD 2.4) ----------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    # PRD 2.1: the clock endpoint is exempt from the authentication gate but
    # not from the role gate, whose set is the five plant roles.
    authorize(PLANT_ROLES, auth_exempt=True)
    data = validate.body()
    current_utc, raw = validate.req_dt(data, "current_utc")
    db.db.clock = current_utc
    db.db.clock_raw = raw
    return ok({"current_utc": raw})


# --- ModelSpec (PRD 3.2) --------------------------------------------------
def _validate_criteria(required_codes, criteria):
    if not isinstance(criteria, list):
        raise ApiError("ERR_INVALID_REQUEST", "component_criteria must be an array.")
    for entry in criteria:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST",
                           "each component_criteria entry must be an object.")
        code = entry.get("code")
        if code not in calc.COMPONENT_CODES:
            raise ApiError("ERR_INVALID_REQUEST",
                           "component_criteria.code must be a component code.")
        if entry.get("metric_direction") not in calc.METRIC_DIRECTIONS:
            raise ApiError("ERR_INVALID_REQUEST",
                           "component_criteria.metric_direction is invalid.")
        for key in ("replace_threshold", "fail_threshold"):
            value = entry.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ApiError("ERR_INVALID_REQUEST",
                               "component_criteria.%s must be a number." % key)
    covered = set(entry.get("code") for entry in criteria)
    for code in required_codes:
        if code not in covered:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "component_criteria must contain one object for %s." % code)


@bp.post("/model-specs")
def create_model_spec():
    authorize(("PlantManager",))
    data = validate.body()
    manufacturer = validate.req_str(data, "manufacturer", max_len=200)
    model_code = validate.req_str(data, "model_code", min_len=1, max_len=40)
    standard_code = validate.req_str(data, "standard_code")
    shell_material = validate.req_enum(data, "shell_material", calc.SHELL_MATERIALS)
    max_service_life_years = validate.req_int(data, "max_service_life_years", 1, 25)
    warranty_years = validate.req_int(data, "warranty_years", 0, 10)
    record_retention_years = validate.req_int(data, "record_retention_years", 1, 10)
    pass_si_max = validate.req_num(data, "pass_si_max")
    repair_si_max = validate.req_num(data, "repair_si_max")
    max_retest_count = validate.req_int(data, "max_retest_count", 0, 5)
    if not validate.present(data, "required_component_codes"):
        raise ApiError("ERR_INVALID_REQUEST", "required_component_codes is required.")
    codes = data["required_component_codes"]
    if not isinstance(codes, list) or not codes:
        raise ApiError("ERR_INVALID_REQUEST",
                       "required_component_codes must be a non-empty array.")
    for code in codes:
        if code not in calc.COMPONENT_CODES:
            raise ApiError("ERR_INVALID_REQUEST",
                           "required_component_codes must be component codes.")
    if len(set(codes)) != len(codes):
        raise ApiError("ERR_INVALID_REQUEST",
                       "required_component_codes must not repeat a code.")
    if not validate.present(data, "component_criteria"):
        raise ApiError("ERR_INVALID_REQUEST", "component_criteria is required.")
    criteria = data["component_criteria"]
    _validate_criteria(codes, criteria)
    reconditionable = validate.opt_bool(data, "reconditionable", default=True)

    for row in db.db.model_specs.values():
        if row["model_code"] == model_code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "model_code must be unique across model specifications.")

    record = db.base_record()
    record.update({
        "manufacturer": manufacturer,
        "model_code": model_code,
        "standard_code": standard_code,
        "shell_material": shell_material,
        "max_service_life_years": max_service_life_years,
        "warranty_years": warranty_years,
        "record_retention_years": record_retention_years,
        "pass_si_max": pass_si_max,
        "repair_si_max": repair_si_max,
        "max_retest_count": max_retest_count,
        "reconditionable": reconditionable,
        "required_component_codes": list(codes),
        "component_criteria": criteria,
    })
    db.db.model_specs[record["id"]] = record
    return helpers.single(record, serialize.model_spec, 201)


@bp.get("/model-specs/<row_id>")
def get_model_spec(row_id):
    authorize(PLANT_ROLES)
    return helpers.single(helpers.model(row_id), serialize.model_spec)


# --- ApprovedPart (PRD 3.2) ----------------------------------------------
@bp.post("/approved-parts")
def create_approved_part():
    authorize(("PlantManager",))
    data = validate.body()
    model_spec_id = validate.req_id(data, "model_spec_id")
    part_number = validate.req_str(data, "part_number", max_len=80)
    component_code = validate.req_enum(data, "component_code", calc.COMPONENT_CODES)
    oem_approved = validate.req_bool(data, "oem_approved")
    unit_price_cents = validate.req_int(data, "unit_price_cents", 0)
    received_qty = validate.req_int(data, "received_qty", 0)
    helpers.model(model_spec_id)

    for row in db.db.approved_parts.values():
        if row["model_spec_id"] == model_spec_id and row["part_number"] == part_number:
            raise ApiError("ERR_INVALID_REQUEST",
                           "part_number must be unique within the model.")

    record = db.base_record()
    record.update({
        "model_spec_id": model_spec_id,
        "part_number": part_number,
        "component_code": component_code,
        "oem_approved": oem_approved,
        "unit_price_cents": unit_price_cents,
        "received_qty": received_qty,
        "on_hand_qty": received_qty,
        "reserved_qty": 0,
        "consumed_qty": 0,
    })
    db.db.approved_parts[record["id"]] = record
    return helpers.single(record, serialize.approved_part, 201)


@bp.get("/approved-parts/<row_id>")
def get_approved_part(row_id):
    authorize(("PlantManager", "Technician", "ComplianceOfficer"))
    return helpers.single(helpers.part(row_id), serialize.approved_part)


@bp.get("/approved-parts")
def list_approved_parts():
    authorize(("PlantManager", "Technician", "ComplianceOfficer"))
    filters = {
        "model_spec_id": validate.query_str("model_spec_id"),
        "component_code": validate.query_enum("component_code", calc.COMPONENT_CODES),
    }
    return helpers.listing("approved_parts", serialize.approved_part, filters)


# --- TestBench (PRD 3.2) -------------------------------------------------
@bp.post("/test-benches")
def create_test_bench():
    authorize(("PlantManager",))
    data = validate.body()
    bench_code = validate.req_str(data, "bench_code", max_len=80)
    test_type = validate.req_enum(data, "test_type", calc.TEST_TYPES)
    daily_session_quota = validate.req_int(data, "daily_session_quota", 1)
    cooldown_minutes = validate.opt_int(data, "cooldown_minutes", 0, 240, default=45)

    for row in db.db.test_benches.values():
        if row["bench_code"] == bench_code:
            raise ApiError("ERR_INVALID_REQUEST",
                           "bench_code must be unique across test benches.")

    record = db.base_record()
    record.update({
        "bench_code": bench_code,
        "test_type": test_type,
        "cooldown_minutes": cooldown_minutes,
        "daily_session_quota": daily_session_quota,
        "calibration_valid_until": None,
    })
    db.db.test_benches[record["id"]] = record
    return helpers.single(record, serialize.test_bench, 201)


@bp.get("/test-benches/<row_id>")
def get_test_bench(row_id):
    authorize(("PlantManager", "Technician", "CertifyingInspector",
               "ComplianceOfficer"))
    return helpers.single(helpers.bench(row_id), serialize.test_bench)


@bp.post("/test-benches/<row_id>/calibrate")
def calibrate_test_bench(row_id):
    authorize(("PlantManager",))
    data = validate.body()
    valid_until, raw = validate.req_dt(data, "calibration_valid_until")
    record = helpers.bench(row_id)
    record["calibration_valid_until"] = valid_until
    db.raw_set(record, "calibration_valid_until", raw)
    touch(record)
    return helpers.single(record, serialize.test_bench)


# --- LoanerUnit (PRD 3.2) -----------------------------------------------
@bp.post("/loaner-units")
def create_loaner_unit():
    authorize(("PlantManager",))
    data = validate.body()
    model_spec_id = validate.req_id(data, "model_spec_id")
    asset_tag = validate.req_str(data, "asset_tag", max_len=80)
    condition_grade = validate.req_enum(data, "condition_grade", calc.CONDITION_GRADES)
    valid_until, raw = validate.req_dt(data, "certification_valid_until")
    helpers.model(model_spec_id)

    for row in db.db.loaner_units.values():
        if row["asset_tag"] == asset_tag:
            raise ApiError("ERR_INVALID_REQUEST",
                           "asset_tag must be unique across loaner units.")

    record = db.base_record()
    record.update({
        "model_spec_id": model_spec_id,
        "asset_tag": asset_tag,
        "condition_grade": condition_grade,
        "certification_valid_until": valid_until,
        "assignment_count": 0,
        "status": "AVAILABLE",
    })
    db.raw_set(record, "certification_valid_until", raw)
    db.db.loaner_units[record["id"]] = record
    return helpers.single(record, serialize.loaner_unit, 201)


@bp.get("/loaner-units/<row_id>")
def get_loaner_unit(row_id):
    authorize(("PlantManager", "IntakeClerk", "ComplianceOfficer"))
    return helpers.single(helpers.loaner(row_id), serialize.loaner_unit)


@bp.get("/loaner-units")
def list_loaner_units():
    authorize(("PlantManager", "IntakeClerk", "ComplianceOfficer"))
    filters = {
        "model_spec_id": validate.query_str("model_spec_id"),
        "status": validate.query_enum("status", calc.LOANER_STATUSES),
        "condition_grade": validate.query_enum("condition_grade",
                                               calc.CONDITION_GRADES),
    }
    return helpers.listing("loaner_units", serialize.loaner_unit, filters)
