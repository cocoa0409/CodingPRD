"""Cook-chill production batches, HACCP logs and the parallel QA axis (PRD 3.5)."""
from flask import Blueprint

from core import (
    ApiError, Field, ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN, all_rows,
    authorize, base_row, body_json, elapsed_minutes, filter_eq, insert, listing,
    now_logical, pagination, parse_instant, present, public, respond_object,
    touch, validate_fields,
)
from calc import (
    batch_logs, chiller_overlap_count, chiller_window, latest_transport_arrive_at,
    recompute_batch_anchors, rows_where, temperature_in_range,
)
from ops import (
    need_batch, need_facility, need_forecast, not_terminal, paged, sync_facility,
)

bp = Blueprint("batch", __name__, url_prefix="/cfs")

SITES = ("MAIN_KITCHEN", "SATELLITE_A", "SEGREGATION_UNIT")
LOG_POINTS = ("COOK_END", "CHILL_INTERMEDIATE", "CHILL_FINAL",
              "TRANSPORT_DEPART", "TRANSPORT_ARRIVE", "REHEAT_SERVE")
STAGES = ("PLANNED", "COOKED", "CHILLED", "STAGED", "SERVED", "DISCARDED")
QA_DECISIONS = ("QA_PASSED", "QA_HELD", "QA_CONDEMNED")
STAGE_TERMINAL = ("SERVED", "DISCARDED")
QA_TERMINAL = ("QA_CONDEMNED",)
FORWARD_STAGE = {"PLANNED": "COOKED", "COOKED": "CHILLED",
                 "CHILLED": "STAGED", "STAGED": "SERVED"}
QA_ORIGINS = {
    "QA_PASSED": ("QA_PENDING", "QA_HELD"),
    "QA_HELD": ("QA_PENDING", "QA_PASSED"),
    "QA_CONDEMNED": ("QA_PENDING", "QA_HELD", "QA_PASSED"),
}

BATCH_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN,
                    ROLE_COMPLIANCE_AUDITOR, ROLE_CONTRACT_ADMINISTRATOR)
LOG_READ_ROLES = (ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN,
                  ROLE_COMPLIANCE_AUDITOR)

BATCH_STATE_FIELDS = ("cook_end_at", "chill_final_at", "chill_minutes",
                      "cook_chill_compliant", "qa_status", "qa_reason",
                      "production_stage")


# --------------------------------------------------------------------------
# Production batches
# --------------------------------------------------------------------------
@bp.route("/production-batches", methods=["POST"])
def create_batch():
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("facility_id", "string", required=True),
        Field("meal_forecast_id", "string", required=True),
        Field("recipe_component", "string", required=True),
        Field("planned_trays", "integer", required=True, min_exclusive=0),
        Field("scheduled_cook_start_at", "datetime", required=True),
        Field("service_site", "string", required=True, enum=SITES),
        Field("expected_facility_version", "integer", required=True),
    ])
    facility = need_facility(body["facility_id"])
    forecast = need_forecast(body["meal_forecast_id"])
    if forecast["facility_id"] != facility["id"]:
        raise ApiError("ERR_FACILITY_MISMATCH",
                       "The forecast belongs to a different facility.")
    if int(body["expected_facility_version"]) != int(facility["version"]):
        raise ApiError("ERR_STALE_FACILITY_VERSION")
    if facility["kitchen_posture"] != "OPEN":
        raise ApiError("ERR_KITCHEN_POSTURE_BLOCKED")

    start = parse_instant(body["scheduled_cook_start_at"])
    chill_deadline_at, buffered_release_at = chiller_window(start)
    if chiller_overlap_count(facility["id"], start, buffered_release_at) >= \
            int(facility["blast_chiller_capacity"]):
        raise ApiError("ERR_CHILLER_CAPACITY_EXCEEDED")
    if forecast["status"] != "LOCKED":
        raise ApiError("ERR_FORECAST_NOT_LOCKED")
    planned = int(body["planned_trays"])
    committed = sum(int(b["planned_trays"]) for b in rows_where(
        "production_batches", meal_forecast_id=forecast["id"])
        if b["production_stage"] != "DISCARDED")
    if committed + planned > int(forecast["total_forecast_trays"]):
        raise ApiError("ERR_TRAY_BUDGET_EXCEEDED")

    row = base_row()
    row.update({
        "facility_id": facility["id"],
        "meal_forecast_id": forecast["id"],
        "recipe_component": body["recipe_component"],
        "planned_trays": planned,
        "produced_trays": 0,
        "scheduled_cook_start_at": start,
        "chill_deadline_at": chill_deadline_at,
        "buffered_release_at": buffered_release_at,
        "service_site": body["service_site"],
        "production_stage": "PLANNED",
        "qa_status": "QA_PENDING",
        "cook_end_at": None,
        "chill_final_at": None,
        "chill_minutes": None,
        "cook_chill_compliant": False,
        "qa_reason": None,
    })
    insert("production_batches", row)
    # The facility's chiller occupancy changed.
    sync_facility(facility, force=True)
    return respond_object(public(row), 201)


@bp.route("/production-batches/<row_id>", methods=["GET"])
def read_batch(row_id):
    authorize(*BATCH_READ_ROLES)
    return respond_object(public(need_batch(row_id)), 200)


@bp.route("/production-batches", methods=["GET"])
def list_batches():
    authorize(*LOG_READ_ROLES)
    rows = filter_eq(all_rows("production_batches"), "facility_id")
    rows = filter_eq(rows, "meal_forecast_id")
    rows = filter_eq(rows, "production_stage")
    rows = filter_eq(rows, "qa_status")
    return listing(rows)


# --------------------------------------------------------------------------
# Temperature logs (immutable: no updated_at, no version)
# --------------------------------------------------------------------------
def _has_log(batch_id, log_point):
    return any(l["log_point"] == log_point for l in batch_logs(batch_id))


@bp.route("/production-batches/<row_id>/temperature-logs", methods=["POST"])
def post_temperature_log(row_id):
    actor = authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("log_point", "string", required=True, enum=LOG_POINTS),
        Field("temperature_f", "number", required=True,
              min_inclusive="-40.0", max_inclusive="500.0"),
        Field("site", "string", required=True, enum=SITES),
    ])
    batch = need_batch(row_id)
    log_point = body["log_point"]

    # Readings must arrive in physical order.
    if log_point != "COOK_END" and not _has_log(batch["id"], "COOK_END"):
        raise ApiError("ERR_LOG_POINT_OUT_OF_SEQUENCE")
    if log_point == "TRANSPORT_ARRIVE" and not _has_log(batch["id"], "TRANSPORT_DEPART"):
        raise ApiError("ERR_LOG_POINT_OUT_OF_SEQUENCE")
    if log_point == "REHEAT_SERVE" and batch["service_site"] != "MAIN_KITCHEN" \
            and not _has_log(batch["id"], "TRANSPORT_ARRIVE"):
        raise ApiError("ERR_LOG_POINT_OUT_OF_SEQUENCE")
    if batch["production_stage"] == "DISCARDED":
        raise ApiError("ERR_BATCH_DISCARDED")

    logged_at = now_logical()
    if log_point == "COOK_END":
        minutes_since_cook_end = None
    elif batch.get("cook_end_at") is not None:
        minutes_since_cook_end = elapsed_minutes(batch["cook_end_at"], logged_at)
    else:
        minutes_since_cook_end = None
    minutes_since_arrive = None
    if log_point == "REHEAT_SERVE":
        arrive_at = latest_transport_arrive_at(batch["id"])
        if arrive_at is not None:
            minutes_since_arrive = elapsed_minutes(arrive_at, logged_at)

    in_range = temperature_in_range(log_point, body["temperature_f"],
                                    minutes_since_cook_end, minutes_since_arrive)
    log = base_row(with_version=False)
    log.update({
        "production_batch_id": batch["id"],
        "log_point": log_point,
        "temperature_f": body["temperature_f"],
        "site": body["site"],
        "logged_at": logged_at,
        "logged_by_user_id": actor.user_id,
        "minutes_since_cook_end": minutes_since_cook_end,
        "in_range": bool(in_range),
    })
    insert("temperature_logs", log)

    before = dict((f, batch.get(f)) for f in BATCH_STATE_FIELDS)
    recompute_batch_anchors(batch)
    if not in_range:
        if log_point in ("CHILL_INTERMEDIATE", "CHILL_FINAL") \
                and batch["qa_status"] in ("QA_PENDING", "QA_PASSED"):
            batch["qa_status"] = "QA_HELD"
            batch["qa_reason"] = "CHILL_GATE_FAILED"
        elif log_point in ("TRANSPORT_ARRIVE", "REHEAT_SERVE") \
                and batch["qa_status"] != "QA_CONDEMNED":
            batch["qa_status"] = "QA_CONDEMNED"
            batch["qa_reason"] = "TRANSPORT_REHEAT_GATE_FAILED"
            if batch["production_stage"] != "SERVED":
                batch["production_stage"] = "DISCARDED"
    if any(batch.get(f) != before[f] for f in BATCH_STATE_FIELDS):
        touch(batch)
    return respond_object(public(log), 201)


@bp.route("/production-batches/<row_id>/temperature-logs", methods=["GET"])
def list_temperature_logs(row_id):
    authorize(*LOG_READ_ROLES)
    limit, offset = pagination()
    batch = need_batch(row_id)
    rows = filter_eq(batch_logs(batch["id"]), "log_point")
    return paged(rows, limit, offset)


# --------------------------------------------------------------------------
# Production axis
# --------------------------------------------------------------------------
@bp.route("/production-batches/<row_id>/advance-stage", methods=["POST"])
def advance_stage(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR)
    body = body_json()
    validate_fields(body, [
        Field("to_stage", "string", required=True, enum=STAGES),
        Field("produced_trays", "integer", min_exclusive=0),
    ])
    to_stage = body["to_stage"]
    if to_stage == "COOKED" and not present(body, "produced_trays"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'produced_trays' is required when advancing to COOKED.")
    batch = need_batch(row_id)
    not_terminal(batch, "production_stage", STAGE_TERMINAL)
    not_terminal(batch, "qa_status", QA_TERMINAL)
    if FORWARD_STAGE.get(batch["production_stage"]) != to_stage:
        raise ApiError("ERR_ILLEGAL_TRANSITION")

    logs = batch_logs(batch["id"])
    if to_stage == "COOKED":
        if not any(l["log_point"] == "COOK_END" and l["in_range"] for l in logs):
            raise ApiError("ERR_COOK_LOG_MISSING")
    elif to_stage == "CHILLED":
        if not any(l["log_point"] == "CHILL_FINAL" for l in logs):
            raise ApiError("ERR_CHILL_LOG_MISSING")
    elif to_stage == "STAGED":
        if batch["qa_status"] != "QA_PASSED":
            raise ApiError("ERR_QA_NOT_PASSED")
    else:
        if batch["qa_status"] != "QA_PASSED":
            raise ApiError("ERR_QA_NOT_PASSED")
        if batch["service_site"] != "MAIN_KITCHEN" and not any(
                l["log_point"] == "REHEAT_SERVE" and l["in_range"] for l in logs):
            raise ApiError("ERR_REHEAT_LOG_MISSING")

    batch["production_stage"] = to_stage
    if to_stage == "COOKED":
        batch["produced_trays"] = int(body["produced_trays"])
    if to_stage == "CHILLED":
        recompute_batch_anchors(batch)
    touch(batch)
    return respond_object(public(batch), 200)


# --------------------------------------------------------------------------
# QA axis
# --------------------------------------------------------------------------
@bp.route("/production-batches/<row_id>/qa-decision", methods=["POST"])
def qa_decision(row_id):
    authorize(ROLE_FOOD_SERVICE_SUPERVISOR, ROLE_REGISTERED_DIETITIAN)
    body = body_json()
    validate_fields(body, [
        Field("qa_decision", "string", required=True, enum=QA_DECISIONS),
        Field("reason", "string", required=True),
    ])
    batch = need_batch(row_id)
    not_terminal(batch, "qa_status", QA_TERMINAL)
    decision = body["qa_decision"]
    if batch["qa_status"] not in QA_ORIGINS[decision]:
        raise ApiError("ERR_INVALID_STATE")
    if decision == "QA_PASSED" and not batch["cook_chill_compliant"]:
        raise ApiError("ERR_COOK_CHILL_NONCOMPLIANT")
    batch["qa_status"] = decision
    batch["qa_reason"] = body["reason"]
    if decision == "QA_CONDEMNED" and batch["production_stage"] != "SERVED":
        batch["production_stage"] = "DISCARDED"
    touch(batch)
    return respond_object(public(batch), 200)
