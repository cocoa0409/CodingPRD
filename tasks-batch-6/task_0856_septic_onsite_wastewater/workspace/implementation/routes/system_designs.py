"""System designs: sizing, well setback, variances and plan review."""
from flask import Blueprint

import derive
import lookup
import response
import serialize
import store
import validate as v
from auth import authenticate
from errors import ApiError
from store import touch
from util import now

bp = Blueprint("system_designs", __name__)

SYSTEM_TYPES = ("CONVENTIONAL", "MOUND", "ATU", "DRIP")
DESIGN_READ_ROLES = ["Applicant", "DesignProfessional",
                     "EnvironmentalHealthSpecialist", "HealthOfficer",
                     "RecordsClerk"]
DESIGN_DECISIONS = ("APPROVE", "REQUEST_REVISIONS")
VARIANCE_DECISIONS = ("GRANT", "DENY")
APPROVABLE_SETBACKS = ("NOT_APPLICABLE", "COMPLIANT", "VARIANCE_GRANTED")


@bp.post("/system-designs")
def create_system_design():
    actor = authenticate(["DesignProfessional"])
    body = v.body()
    evaluation = lookup.site_evaluation(v.req_fk(body, "site_evaluation_id"))
    expected_version = v.req_int(body, "expected_site_evaluation_version")
    system_type = v.req_enum(body, "system_type", SYSTEM_TYPES)
    bedrooms = v.req_int(body, "bedrooms", minimum=1, maximum=8)
    tank_capacity_gal = v.req_int(body, "tank_capacity_gal", minimum=750)
    drainfield_x_ft = v.req_num(body, "drainfield_x_ft")
    drainfield_y_ft = v.req_num(body, "drainfield_y_ft")

    if expected_version != evaluation["version"]:
        raise ApiError("ERR_STALE_SITE_EVALUATION_VERSION")

    design = store.new_record()
    design.update({
        "site_evaluation_id": evaluation["id"],
        "designer_user_id": actor.user_id,
        "system_type": system_type,
        "bedrooms": bedrooms,
        "tank_capacity_gal": tank_capacity_gal,
        "drainfield_x_ft": drainfield_x_ft,
        "drainfield_y_ft": drainfield_y_ft,
        "design_flow_gpd": None,
        "required_drainfield_sqft": None,
        "nearest_well_distance_ft": None,
        "required_setback_ft": None,
        "setback_status": "NOT_APPLICABLE",
        "status": "DRAFT",
        "review_ehs_user_id": None,
        "revision_round": 0,
    })
    store.system_designs[design["id"]] = design
    derive.recompute_design(design)

    touch(evaluation)
    return response.ok(serialize.system_design(design), 201)


@bp.get("/system-designs/<design_id>")
def read_system_design(design_id):
    authenticate(DESIGN_READ_ROLES)
    design = lookup.system_design(design_id)
    return response.ok(serialize.system_design(design))


@bp.post("/system-designs/<design_id>/submit")
def submit_system_design(design_id):
    authenticate(["DesignProfessional"])
    design = lookup.system_design(design_id)
    evaluation = store.site_evaluations[design["site_evaluation_id"]]

    if design["status"] not in ("DRAFT", "REVISIONS_REQUIRED"):
        raise ApiError("ERR_INVALID_STATE")
    if evaluation["status"] != "APPROVED":
        raise ApiError("ERR_SITE_EVALUATION_NOT_APPROVED")
    if design["setback_status"] == "VARIANCE_DENIED":
        raise ApiError("ERR_SETBACK_VIOLATION")
    if now() > evaluation["valid_until"]:
        raise ApiError("ERR_SITE_EVALUATION_EXPIRED")

    derive.recompute_design(design)
    design["status"] = "UNDER_REVIEW"
    design["revision_round"] += 1
    touch(design)
    return response.ok(serialize.system_design(design))


@bp.post("/system-designs/<design_id>/review")
def review_system_design(design_id):
    actor = authenticate(["EnvironmentalHealthSpecialist"])
    design = lookup.system_design(design_id)
    body = v.body()
    decision = v.req_enum(body, "decision", DESIGN_DECISIONS)

    if design["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_INVALID_STATE")

    if decision == "APPROVE":
        evaluation = store.site_evaluations[design["site_evaluation_id"]]
        if evaluation["soil_loading_rate_gpd_per_sqft"] is None:
            raise ApiError("ERR_SOIL_UNSUITABLE")
        if design["setback_status"] not in APPROVABLE_SETBACKS:
            raise ApiError("ERR_SETBACK_VIOLATION")
        design["status"] = "APPROVED"
        design["review_ehs_user_id"] = actor.user_id
        touch(design)
        for sibling in derive.designs_of_evaluation(design["site_evaluation_id"]):
            if sibling["id"] != design["id"] and sibling["status"] == "APPROVED":
                sibling["status"] = "SUPERSEDED"
                touch(sibling)
    else:
        design["status"] = "REVISIONS_REQUIRED"
        touch(design)

    return response.ok(serialize.system_design(design))


@bp.post("/system-designs/<design_id>/variance-decision")
def variance_decision(design_id):
    authenticate(["HealthOfficer"])
    design = lookup.system_design(design_id)
    body = v.body()
    decision = v.req_enum(body, "decision", VARIANCE_DECISIONS)

    if design["status"] not in ("DRAFT", "UNDER_REVIEW", "REVISIONS_REQUIRED"):
        raise ApiError("ERR_INVALID_STATE")
    if design["setback_status"] != "VARIANCE_REQUIRED":
        raise ApiError("ERR_INVALID_STATE")

    if decision == "GRANT":
        parcel = derive.parcel_of_design(design)
        if parcel is not None and parcel["water_quality_flag"]:
            raise ApiError("ERR_WATER_QUALITY_HOLD")
        design["setback_status"] = "VARIANCE_GRANTED"
        touch(design)
    else:
        design["setback_status"] = "VARIANCE_DENIED"
        if design["status"] == "UNDER_REVIEW":
            design["status"] = "REVISIONS_REQUIRED"
        touch(design)

    return response.ok(serialize.system_design(design))
