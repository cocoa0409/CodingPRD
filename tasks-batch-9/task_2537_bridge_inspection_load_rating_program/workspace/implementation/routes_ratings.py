"""LoadRating, ScourEvaluation and PlanOfAction endpoints."""

from flask import Blueprint

import calc
import db
import params
import response
import serializers
import services
from calc import D, dec
from db import db as store
from errors import ApiError
from middleware import (
    BRIDGE_INSPECTOR,
    DISTRICT_ENGINEER,
    RATING_ENGINEER,
    authenticate,
    authenticate_read,
)

bp = Blueprint("ratings", __name__)

METHODS = ("LRFR", "LFR", "ASD")
RATING_VEHICLES = ("HL93", "HS20")
RATING_STATUSES = ("DRAFT", "SEALED", "APPROVED", "REJECTED", "SUPERSEDED")
EVALUATION_METHODS = ("HEC18_SCREENING", "DETAILED_HYDRAULIC", "FIELD_OBSERVATION")
FOUNDATION_TYPES = ("SPREAD_FOOTING", "PILE", "DRILLED_SHAFT", "UNKNOWN")
SCOUR_STATUSES_DERIVED = ("SCOUR_CRITICAL", "LOW_RISK", "STABILIZED")
EVALUATION_STATUSES = ("DRAFT", "FINAL")
POA_STATUSES = ("REQUIRED", "DRAFT", "SUBMITTED", "APPROVED")
COUNTERMEASURE_TYPES = ("NONE", "RIPRAP", "MONITORING_ONLY", "STRUCTURAL")


def _superstructure_rows(inspection_id):
    return [
        row
        for row in services.element_conditions_of(inspection_id)
        if row["element_group"] == "SUPERSTRUCTURE"
    ]


def _apply_rating_outputs(record, source_inspection_id):
    rows = _superstructure_rows(source_inspection_id)
    record["condition_factor_phi_c"] = calc.condition_factor_phi_c(rows)
    record.update(
        calc.load_rating_outputs(
            record["condition_factor_phi_c"],
            record["system_factor_phi_s"],
            record["resistance_factor_phi"],
            record["capacity_c_kn_m"],
            record["dead_load_dc_kn_m"],
            record["dead_load_dw_kn_m"],
            record["live_load_ll_kn_m"],
            record["impact_im_factor"],
        )
    )
    return record


# --------------------------------------------------------------------------- #
# load ratings
# --------------------------------------------------------------------------- #
@bp.post("/bridges/<bridge_id>/load-ratings")
def create_load_rating(bridge_id):
    authenticate(RATING_ENGINEER)
    body = params.json_body()
    expected_version = params.get_int(body, "expected_bridge_version", required=True, minimum=0)
    source_inspection_id = params.get_string(body, "source_inspection_id", required=True)
    method = params.get_enum(body, "method", METHODS, required=True)
    rating_vehicle = params.get_enum(body, "rating_vehicle", RATING_VEHICLES, required=True)
    capacity = params.get_number(body, "capacity_c_kn_m", required=True, exclusive_minimum=0)
    dead_dc = params.get_number(body, "dead_load_dc_kn_m", required=True, minimum=0)
    dead_dw = params.get_number(body, "dead_load_dw_kn_m", required=True, minimum=0)
    live_load = params.get_number(body, "live_load_ll_kn_m", required=True, exclusive_minimum=0)
    impact = params.get_number(
        body, "impact_im_factor", default=D("1.33"), minimum=D("1.00"), maximum=D("1.50")
    )
    phi_s = params.get_number(
        body, "system_factor_phi_s", default=D("1.00"), minimum=D("0.85"), maximum=D("1.00")
    )
    phi = params.get_number(
        body, "resistance_factor_phi", default=D("0.90"), minimum=D("0.75"), maximum=D("1.00")
    )
    raw_effective, _effective = params.get_instant(body, "rating_effective_date")

    bridge = services.get_bridge(bridge_id)
    inspection = services.get_inspection(source_inspection_id)
    if int(expected_version) != int(bridge["version"]):
        raise ApiError("ERR_STALE_BRIDGE_VERSION")
    if not _superstructure_rows(source_inspection_id):
        raise ApiError("ERR_ELEMENT_GROUP_MISSING")
    if inspection["bridge_id"] != bridge_id or inspection["status"] != "ACCEPTED":
        raise ApiError("ERR_RATING_SOURCE_NOT_ACCEPTED")

    record = db.new_record(
        {
            "bridge_id": bridge_id,
            "source_inspection_id": source_inspection_id,
            "method": method,
            "rating_vehicle": rating_vehicle,
            "capacity_c_kn_m": capacity,
            "dead_load_dc_kn_m": dead_dc,
            "dead_load_dw_kn_m": dead_dw,
            "live_load_ll_kn_m": live_load,
            "impact_im_factor": impact,
            "system_factor_phi_s": phi_s,
            "resistance_factor_phi": phi,
            "rating_status": "DRAFT",
            "sealed_by_id": None,
            "approved_by_id": None,
            "rating_effective_date": raw_effective,
            "rejection_note": None,
        }
    )
    _apply_rating_outputs(record, source_inspection_id)
    store.load_ratings[record["id"]] = record
    services.settle_and_touch(bridge)
    return response.object_response(serializers.load_rating(record), 201)


@bp.get("/load-ratings/<rating_id>")
def read_load_rating(rating_id):
    authenticate_read()
    record = services.get_load_rating(rating_id)
    return response.object_response(serializers.load_rating(record))


@bp.get("/load-ratings")
def list_load_ratings():
    authenticate_read()
    limit, offset = params.query_pagination()
    bridge_id = params.query_string("bridge_id")
    source_inspection_id = params.query_string("source_inspection_id")
    sealed_by_id = params.query_string("sealed_by_id")
    approved_by_id = params.query_string("approved_by_id")
    rating_status = params.query_enum("rating_status", RATING_STATUSES)
    method = params.query_enum("method", METHODS)
    posting_required = params.query_bool("posting_required")
    items = []
    for record in services.rows("load_ratings"):
        if bridge_id is not None and record["bridge_id"] != bridge_id:
            continue
        if source_inspection_id is not None and record["source_inspection_id"] != source_inspection_id:
            continue
        if sealed_by_id is not None and record["sealed_by_id"] != sealed_by_id:
            continue
        if approved_by_id is not None and record["approved_by_id"] != approved_by_id:
            continue
        if rating_status is not None and record["rating_status"] != rating_status:
            continue
        if method is not None and record["method"] != method:
            continue
        if posting_required is not None and bool(record["posting_required"]) != posting_required:
            continue
        items.append(serializers.load_rating(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/load-ratings/<rating_id>/seal")
def seal_load_rating(rating_id):
    actor = authenticate(RATING_ENGINEER)
    body = params.json_body()
    sealed_by_id = params.get_string(body, "sealed_by_id", required=True)
    record = services.get_load_rating(rating_id)
    engineer = services.get_personnel(sealed_by_id)
    if sealed_by_id != actor.user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")
    if record["rating_status"] != "DRAFT":
        raise ApiError("ERR_RATING_STATE_INVALID")
    if (
        not engineer["load_rating_engineer_licensed"]
        or engineer["pe_license_number"] is None
        or not services.person_is_current(engineer)
    ):
        raise ApiError("ERR_RATING_ENGINEER_NOT_LICENSED")
    record["rating_status"] = "SEALED"
    record["sealed_by_id"] = sealed_by_id
    _apply_rating_outputs(record, record["source_inspection_id"])
    db.touch(record)
    return response.object_response(serializers.load_rating(record))


@bp.post("/load-ratings/<rating_id>/approve")
def approve_load_rating(rating_id):
    actor = authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    approved_by_id = params.get_string(body, "approved_by_id", required=True)
    record = services.get_load_rating(rating_id)
    services.get_personnel(approved_by_id)
    if approved_by_id != actor.user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")
    if record["rating_status"] != "SEALED":
        raise ApiError("ERR_RATING_STATE_INVALID")
    if record["sealed_by_id"] is not None and record["sealed_by_id"] == approved_by_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    source = store.inspections.get(record["source_inspection_id"])
    if source is None or source["status"] != "ACCEPTED":
        raise ApiError("ERR_RATING_SOURCE_NOT_ACCEPTED")

    bridge = services.get_bridge(record["bridge_id"])
    for other in services.load_ratings_of(bridge["id"]):
        if other["id"] != record["id"] and other["rating_status"] == "APPROVED":
            other["rating_status"] = "SUPERSEDED"
            db.touch(other)
    record["rating_status"] = "APPROVED"
    record["approved_by_id"] = approved_by_id
    record["rating_effective_date"] = db.now()
    db.touch(record)
    services.settle_and_touch(bridge)
    return response.object_response(serializers.load_rating(record))


@bp.post("/load-ratings/<rating_id>/reject")
def reject_load_rating(rating_id):
    authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    rejection_note = params.get_string(body, "rejection_note", required=True)
    record = services.get_load_rating(rating_id)
    if record["rating_status"] != "SEALED":
        raise ApiError("ERR_RATING_STATE_INVALID")
    record["rating_status"] = "REJECTED"
    record["rejection_note"] = rejection_note
    db.touch(record)
    return response.object_response(serializers.load_rating(record))


# --------------------------------------------------------------------------- #
# scour evaluations
# --------------------------------------------------------------------------- #
@bp.post("/bridges/<bridge_id>/scour-evaluations")
def create_scour_evaluation(bridge_id):
    actor = authenticate(RATING_ENGINEER, BRIDGE_INSPECTOR)
    body = params.json_body()
    evaluated_by_id = params.get_string(body, "evaluated_by_id", required=True)
    evaluation_method = params.get_enum(
        body, "evaluation_method", EVALUATION_METHODS, required=True
    )
    scour_code = params.get_int(body, "scour_code", required=True, minimum=0, maximum=9)
    foundation_type = params.get_enum(body, "foundation_type", FOUNDATION_TYPES)
    depth = params.get_number(body, "observed_scour_depth_m", default=D("0"), minimum=0)

    bridge = services.get_bridge(bridge_id)
    evaluator = services.get_personnel(evaluated_by_id)
    if evaluated_by_id != actor.user_id:
        raise ApiError("ERR_IDENTITY_MISMATCH")
    if not services.person_is_current(evaluator):
        raise ApiError("ERR_TEAM_LEADER_NOT_QUALIFIED")
    if not bridge["spans_water"]:
        raise ApiError("ERR_INSPECTION_TYPE_NOT_APPLICABLE")

    record = db.new_record(
        {
            "bridge_id": bridge_id,
            "evaluated_by_id": evaluated_by_id,
            "evaluation_method": evaluation_method,
            "foundation_type": foundation_type,
            "scour_code": scour_code,
            "observed_scour_depth_m": depth,
            "status": "DRAFT",
            "finalized_at": None,
            "derived_scour_status": calc.derived_scour_status(scour_code),
        }
    )
    store.scour_evaluations[record["id"]] = record
    return response.object_response(serializers.scour_evaluation(record), 201)


@bp.get("/scour-evaluations/<evaluation_id>")
def read_scour_evaluation(evaluation_id):
    authenticate_read()
    record = services.get_scour_evaluation(evaluation_id)
    return response.object_response(serializers.scour_evaluation(record))


@bp.get("/scour-evaluations")
def list_scour_evaluations():
    authenticate_read()
    limit, offset = params.query_pagination()
    bridge_id = params.query_string("bridge_id")
    evaluated_by_id = params.query_string("evaluated_by_id")
    status = params.query_enum("status", EVALUATION_STATUSES)
    evaluation_method = params.query_enum("evaluation_method", EVALUATION_METHODS)
    derived = params.query_enum("derived_scour_status", SCOUR_STATUSES_DERIVED)
    items = []
    for record in services.rows("scour_evaluations"):
        if bridge_id is not None and record["bridge_id"] != bridge_id:
            continue
        if evaluated_by_id is not None and record["evaluated_by_id"] != evaluated_by_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if evaluation_method is not None and record["evaluation_method"] != evaluation_method:
            continue
        if derived is not None and record["derived_scour_status"] != derived:
            continue
        items.append(serializers.scour_evaluation(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/scour-evaluations/<evaluation_id>/finalize")
def finalize_scour_evaluation(evaluation_id):
    authenticate(RATING_ENGINEER)
    record = services.get_scour_evaluation(evaluation_id)
    if record["status"] != "DRAFT":
        raise ApiError("ERR_RATING_STATE_INVALID")
    engineer = store.personnel.get(record["evaluated_by_id"])
    if (
        engineer is None
        or not engineer["load_rating_engineer_licensed"]
        or engineer["pe_license_number"] is None
        or not services.person_is_current(engineer)
    ):
        raise ApiError("ERR_RATING_ENGINEER_NOT_LICENSED")
    services.finalize_scour(record)
    return response.object_response(serializers.scour_evaluation(record))


# --------------------------------------------------------------------------- #
# plans of action
# --------------------------------------------------------------------------- #
@bp.get("/plans-of-action/<plan_id>")
def read_plan_of_action(plan_id):
    authenticate_read()
    record = services.get_plan_of_action(plan_id)
    return response.object_response(serializers.plan_of_action(record))


@bp.get("/plans-of-action")
def list_plans_of_action():
    authenticate_read()
    limit, offset = params.query_pagination()
    bridge_id = params.query_string("bridge_id")
    evaluation_id = params.query_string("scour_evaluation_id")
    approved_by_id = params.query_string("approved_by_id")
    status = params.query_enum("status", POA_STATUSES)
    countermeasure_type = params.query_enum("countermeasure_type", COUNTERMEASURE_TYPES)
    items = []
    for record in services.rows("plans_of_action"):
        if bridge_id is not None and record["bridge_id"] != bridge_id:
            continue
        if evaluation_id is not None and record["scour_evaluation_id"] != evaluation_id:
            continue
        if approved_by_id is not None and record["approved_by_id"] != approved_by_id:
            continue
        if status is not None and record["status"] != status:
            continue
        if countermeasure_type is not None and record["countermeasure_type"] != countermeasure_type:
            continue
        items.append(serializers.plan_of_action(record))
    page, total = response.paginate(items, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.put("/plans-of-action/<plan_id>")
def update_plan_of_action(plan_id):
    authenticate(DISTRICT_ENGINEER, BRIDGE_INSPECTOR)
    body = params.json_body()
    months = params.get_int(
        body, "monitoring_frequency_months", required=True, minimum=1, maximum=24
    )
    stage = params.get_number(body, "closure_trigger_stage_m", required=True, exclusive_minimum=0)
    countermeasure = params.get_enum(
        body, "countermeasure_type", COUNTERMEASURE_TYPES, default="NONE"
    )
    record = services.get_plan_of_action(plan_id)
    if record["status"] not in ("REQUIRED", "DRAFT"):
        raise ApiError("ERR_RATING_STATE_INVALID")
    record["monitoring_frequency_months"] = months
    record["closure_trigger_stage_m"] = stage
    record["countermeasure_type"] = countermeasure
    record["status"] = "DRAFT"
    db.touch(record)
    return response.object_response(serializers.plan_of_action(record))


@bp.post("/plans-of-action/<plan_id>/submit")
def submit_plan_of_action(plan_id):
    authenticate(DISTRICT_ENGINEER, BRIDGE_INSPECTOR)
    record = services.get_plan_of_action(plan_id)
    if record["status"] != "DRAFT":
        raise ApiError("ERR_RATING_STATE_INVALID")
    if (
        record["monitoring_frequency_months"] is None
        or record["closure_trigger_stage_m"] is None
        or record["countermeasure_type"] == "NONE"
    ):
        raise ApiError("ERR_RATING_STATE_INVALID")
    record["status"] = "SUBMITTED"
    record["submitted_at"] = db.now()
    db.touch(record)
    return response.object_response(serializers.plan_of_action(record))


@bp.post("/plans-of-action/<plan_id>/decision")
def decide_plan_of_action(plan_id):
    actor = authenticate(DISTRICT_ENGINEER)
    body = params.json_body()
    decision = params.get_enum(body, "decision", ("APPROVE", "RETURN"), required=True)
    approved_by_id = params.get_string(
        body, "approved_by_id", required=(decision == "APPROVE")
    )
    return_note = params.get_string(body, "return_note")
    record = services.get_plan_of_action(plan_id)
    if approved_by_id is not None:
        services.get_personnel(approved_by_id)
        if approved_by_id != actor.user_id:
            raise ApiError("ERR_IDENTITY_MISMATCH")
    if record["status"] != "SUBMITTED":
        raise ApiError("ERR_RATING_STATE_INVALID")

    if decision == "APPROVE":
        record["status"] = "APPROVED"
        record["approved_by_id"] = approved_by_id
        record["approved_at"] = db.now()
        db.touch(record)
        bridge = services.get_bridge(record["bridge_id"])
        services.settle_and_touch(bridge)
    else:
        record["status"] = "DRAFT"
        record["revision_count"] = int(record["revision_count"]) + 1
        record["return_note"] = return_note
        db.touch(record)
    return response.object_response(serializers.plan_of_action(record))
