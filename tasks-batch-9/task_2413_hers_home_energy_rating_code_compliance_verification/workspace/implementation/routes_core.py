"""Builders, subdivisions, plan models, homes, raters and the logical clock."""

from flask import Blueprint, g

import calc
import validation as v
from auth import endpoint, require_owner
from db import clock_now_iso, db, iso_ms, new_row, touch
from errors import ApiError
from graph import (
    homes_of_subdivision,
    plan_models_of_subdivision,
    require_builder,
    require_home,
    require_plan_model,
    require_rater,
    require_subdivision,
)
from ops import invalid_state
from response import Result
from serializers import (
    builder_out,
    home_out,
    plan_model_out,
    rater_out,
    subdivision_out,
)
from db import ordered

bp = Blueprint("core", __name__)

BUILDER_TYPES = ("PRODUCTION", "CUSTOM")
CODE_EDITIONS = ("IECC_2015", "IECC_2021")
CLIMATE_ZONES = ("CZ2", "CZ3", "CZ4", "CZ5", "CZ6")
PATH_PREFERENCES = ("ERI_PATH", "PRESCRIPTIVE_PATH")
CERT_LEVELS = ("RATER", "RATING_FIELD_INSPECTOR", "QA_DESIGNEE")
SAMPLING_ROLES = ("UNASSIGNED", "MEMBER", "TESTED", "REPRESENTED")

ALL_ROLES = (
    "RatingProviderAdmin",
    "CertifiedRater",
    "FieldInspector",
    "QADesignee",
    "BuilderRep",
)


# --- Builders -------------------------------------------------------------
@bp.post("/builders")
@endpoint(["RatingProviderAdmin"])
def create_builder():
    data = v.body()
    name = v.req_str(data, "name")
    builder_type = v.req_enum(data, "builder_type", BUILDER_TYPES)
    budget = v.req_int(data, "utility_program_budget_cents", min_value=0)

    row = new_row(
        "Builder",
        {
            "name": name,
            "builder_type": builder_type,
            "status": "ACTIVE",
            "utility_program_budget_cents": budget,
            "sampling_eligible": builder_type == "PRODUCTION",
            "open_corrective_action_count": 0,
            "revoked_package_count": 0,
            "certified_incentive_cents": 0,
        },
    )
    db.builders[row["id"]] = row
    return Result(row, builder_out, status=201)


@bp.get("/builders/<builder_id>")
@endpoint(["RatingProviderAdmin", "CertifiedRater", "QADesignee", "BuilderRep"])
def get_builder(builder_id):
    return Result(require_builder(builder_id), builder_out)


# --- Subdivisions ---------------------------------------------------------
@bp.post("/subdivisions")
@endpoint(["RatingProviderAdmin"])
def create_subdivision():
    data = v.body()
    builder_id = v.req_str(data, "builder_id")
    name = v.req_str(data, "name")
    code_edition = v.req_enum(data, "code_edition", CODE_EDITIONS)
    climate_zone = v.req_enum(data, "climate_zone", CLIMATE_ZONES)
    sampling_enabled = v.opt_bool(data, "sampling_enabled", False)
    preference = v.opt_enum(
        data, "compliance_path_preference", PATH_PREFERENCES, "ERI_PATH"
    )

    require_builder(builder_id)

    row = new_row(
        "Subdivision",
        {
            "builder_id": builder_id,
            "name": name,
            "code_edition": code_edition,
            "climate_zone": climate_zone,
            "sampling_enabled": sampling_enabled,
            "compliance_path_preference": preference,
            "homes_count": 0,
            "sampled_home_count": 0,
            "unsampled_home_count": 0,
        },
    )
    db.subdivisions[row["id"]] = row
    return Result(row, subdivision_out, status=201)


@bp.get("/subdivisions/<subdivision_id>")
@endpoint(list(ALL_ROLES))
def get_subdivision(subdivision_id):
    return Result(require_subdivision(subdivision_id), subdivision_out)


@bp.get("/subdivisions")
@endpoint(["RatingProviderAdmin", "CertifiedRater", "QADesignee", "BuilderRep"])
def list_subdivisions():
    limit, offset = v.pagination()
    builder_id = v.query_str("builder_id")
    rows = [
        s
        for s in db.subdivisions.values()
        if builder_id is None or s["builder_id"] == builder_id
    ]
    rows = ordered(rows)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, subdivision_out, page=(limit, offset, total))


# --- Plan models ----------------------------------------------------------
@bp.post("/plan-models")
@endpoint(["CertifiedRater"])
def create_plan_model():
    data = v.body()
    subdivision_id = v.req_str(data, "subdivision_id")
    plan_code = v.req_str(data, "plan_code")
    cfa = v.req_number(data, "conditioned_floor_area_sqft", 0, exclusive_min=True)
    volume = v.req_number(data, "conditioned_volume_cuft", 0, exclusive_min=True)
    bedrooms = v.req_int(data, "bedrooms", min_value=1)
    ua = v.req_number(data, "envelope_ua_btu_per_hr_f", 0, exclusive_min=True)
    ach50 = v.req_number(data, "design_ach50", 0, exclusive_min=True)
    duct = v.req_number(data, "design_duct_leakage_cfm25_per_100sqft", 0)
    hvac = v.req_number(data, "hvac_efficiency_index", 1, max_value=20)
    pv = v.opt_number(data, "pv_capacity_kw_dc", 0, min_value=0)

    subdivision = require_subdivision(subdivision_id)

    for existing in plan_models_of_subdivision(subdivision_id):
        if existing["plan_code"] == plan_code:
            raise ApiError("ERR_DUPLICATE_PLAN_CODE")

    row = new_row(
        "PlanModel",
        {
            "subdivision_id": subdivision_id,
            "plan_code": plan_code,
            "conditioned_floor_area_sqft": cfa,
            "conditioned_volume_cuft": volume,
            "bedrooms": bedrooms,
            "envelope_ua_btu_per_hr_f": ua,
            "design_ach50": ach50,
            "design_duct_leakage_cfm25_per_100sqft": duct,
            "hvac_efficiency_index": hvac,
            "pv_capacity_kw_dc": pv,
            "projected_index": None,
            "status": "ACTIVE",
        },
    )
    row["projected_index"] = calc.projected_index(row, subdivision)
    db.plan_models[row["id"]] = row
    return Result(row, plan_model_out, status=201)


@bp.get("/subdivisions/<subdivision_id>/plan-models")
@endpoint(list(ALL_ROLES))
def list_subdivision_plan_models(subdivision_id):
    limit, offset = v.pagination()
    require_subdivision(subdivision_id)
    rows = plan_models_of_subdivision(subdivision_id)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, plan_model_out, page=(limit, offset, total))


# --- Homes ----------------------------------------------------------------
@bp.post("/homes")
@endpoint(["BuilderRep"])
def create_home():
    data = v.body()
    subdivision_id = v.req_str(data, "subdivision_id")
    plan_model_id = v.req_str(data, "plan_model_id")
    lot_number = v.req_str(data, "lot_number")
    permit_date = v.req_date(data, "permit_date")

    subdivision = require_subdivision(subdivision_id)
    plan = require_plan_model(plan_model_id)

    require_owner(subdivision["builder_id"])

    if plan["subdivision_id"] != subdivision_id or plan["status"] != "ACTIVE":
        raise ApiError("ERR_PLAN_MODEL_MISMATCH")

    for existing in homes_of_subdivision(subdivision_id):
        if existing["lot_number"] == lot_number:
            raise ApiError("ERR_DUPLICATE_LOT_NUMBER")

    row = new_row(
        "Home",
        {
            "subdivision_id": subdivision_id,
            "plan_model_id": plan_model_id,
            "sample_set_id": None,
            "lot_number": lot_number,
            "permit_date": permit_date,
            "sampling_role": "UNASSIGNED",
            "individual_testing_required": False,
        },
    )
    db.homes[row["id"]] = row
    return Result(row, home_out, status=201)


@bp.get("/homes/<home_id>")
@endpoint(list(ALL_ROLES))
def get_home(home_id):
    return Result(require_home(home_id), home_out)


@bp.get("/homes")
@endpoint(list(ALL_ROLES))
def list_homes():
    limit, offset = v.pagination()
    subdivision_id = v.query_str("subdivision_id")
    plan_model_id = v.query_str("plan_model_id")
    sample_set_id = v.query_str("sample_set_id")
    sampling_role = v.query_enum("sampling_role", SAMPLING_ROLES)

    rows = []
    for home in db.homes.values():
        if subdivision_id is not None and home["subdivision_id"] != subdivision_id:
            continue
        if plan_model_id is not None and home["plan_model_id"] != plan_model_id:
            continue
        if sample_set_id is not None and home["sample_set_id"] != sample_set_id:
            continue
        if sampling_role is not None and home["sampling_role"] != sampling_role:
            continue
        rows.append(home)
    rows = ordered(rows)
    page, total = v.paginate(rows, limit, offset)
    return Result(page, home_out, page=(limit, offset, total))


# --- Raters ---------------------------------------------------------------
@bp.post("/raters")
@endpoint(["RatingProviderAdmin"])
def create_rater():
    data = v.body()
    full_name = v.req_str(data, "full_name")
    cert_level = v.req_enum(data, "cert_level", CERT_LEVELS)
    cert_expires_raw, _parsed = v.req_datetime(data, "cert_expires_at")

    row = new_row(
        "Rater",
        {
            "full_name": full_name,
            "cert_level": cert_level,
            "certification_status": "ACTIVE",
            "effective_certification_status": "ACTIVE",
            "cert_expires_at": cert_expires_raw,
            "qa_failure_count": 0,
            "confirmed_rating_count": 0,
            "qa_completed_count": 0,
            "qa_files_owed": 0,
            "registry_hold": False,
        },
    )
    db.raters[row["id"]] = row
    return Result(row, rater_out, status=201)


@bp.get("/raters/<rater_id>")
@endpoint(["RatingProviderAdmin", "CertifiedRater", "FieldInspector", "QADesignee"])
def get_rater(rater_id):
    return Result(require_rater(rater_id), rater_out)


@bp.post("/raters/<rater_id>/reinstate")
@endpoint(["RatingProviderAdmin"])
def reinstate_rater(rater_id):
    data = v.body()
    v.req_datetime(data, "training_completed_at")
    v.opt_str(data, "note")

    rater = require_rater(rater_id)
    if rater["certification_status"] not in ("PROBATION", "SUSPENDED"):
        invalid_state("Only a PROBATION or SUSPENDED rater can be reinstated.")

    rater["certification_status"] = "ACTIVE"
    rater["qa_failure_count"] = 0
    touch(rater)
    return Result(rater, rater_out)


# --- Logical clock --------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@endpoint(["RatingProviderAdmin"])
def set_clock():
    data = v.body()
    _raw, parsed = v.req_datetime(data, "to_iso8601")
    db.logical_clock = parsed
    return Result({"current_utc": clock_now_iso()})


# Keep references so linters do not strip helpers used by other modules.
_UNUSED = (g, iso_ms, require_home)
