"""DiagnosticEvaluation endpoints — PRD §3.2."""
from flask import Blueprint, g, jsonify

from ..auth import require_auth
from ..clock import parse_iso
from ..errors import APIError
from ..helpers import get_json_body, require_field
from ..responses import success_response
from ..services.lookups import (
    get_evaluation,
    get_patient,
    get_therapist,
)
from ..services.serialize import serialize_evaluation
from ..store import get_lock, get_store, stamp_create, stamp_update


bp = Blueprint("evaluations", __name__)


SEVERITY_LEVELS = {"LEVEL_1", "LEVEL_2", "LEVEL_3"}


@bp.post("/patients/<patient_id>/evaluations")
@require_auth("BCBA", "ClinicAdmin")
def create_evaluation(patient_id):
    body = get_json_body()
    with get_lock():
        patient = get_patient(patient_id)  # path FK first
        clinic = get_store().clinics[patient["clinic_id"]]

        evaluator_therapist_id = require_field(body, "evaluator_therapist_id")
        scheduled_at = require_field(body, "scheduled_at")

        # Validate scheduled_at parseable.
        parse_iso(scheduled_at)

        therapist = get_therapist(evaluator_therapist_id)
        if therapist["credential"] != "BCBA":
            raise APIError("ERR_VALIDATION", "evaluator_therapist_id must reference a BCBA therapist")
        if therapist["clinic_id"] != patient["clinic_id"]:
            raise APIError("ERR_VALIDATION", "evaluator therapist must belong to the same clinic")

        record = stamp_create(
            {
                "patient_id": patient_id,
                "evaluator_therapist_id": evaluator_therapist_id,
                "scheduled_at": scheduled_at,
                "completed_at": None,
                "diagnosis_code": None,
                "severity_level": None,
                "recommended_weekly_hours": None,
                "status": "SCHEDULED",
            },
            now=clinic["now_ts"],
        )
        get_store().evaluations[record["id"]] = record

    body_out, status = success_response(serialize_evaluation(record), status=201)
    return jsonify(body_out), status


@bp.post("/evaluations/<evaluation_id>/start")
@require_auth("BCBA")
def start_evaluation(evaluation_id):
    with get_lock():
        ev = get_evaluation(evaluation_id)
        # Ownership precedes state check.
        if ev["evaluator_therapist_id"] != g.user_id:
            raise APIError("ERR_NOT_THERAPIST_OF_RECORD",
                           "Acting BCBA is not this evaluation's evaluator_therapist_id")
        if ev["status"] != "SCHEDULED":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot start evaluation in status {ev['status']}")
        patient = get_patient(ev["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        if parse_iso(clinic["now_ts"]) < parse_iso(ev["scheduled_at"]):
            raise APIError("ERR_INVALID_STATE", "clinic.now_ts has not reached scheduled_at")

        ev["status"] = "IN_PROGRESS"
        stamp_update(ev, now=clinic["now_ts"])

    body_out, status = success_response(serialize_evaluation(ev))
    return jsonify(body_out), status


@bp.post("/evaluations/<evaluation_id>/complete")
@require_auth("BCBA")
def complete_evaluation(evaluation_id):
    body = get_json_body()
    with get_lock():
        ev = get_evaluation(evaluation_id)
        if ev["evaluator_therapist_id"] != g.user_id:
            raise APIError("ERR_NOT_THERAPIST_OF_RECORD",
                           "Acting BCBA is not this evaluation's evaluator_therapist_id")
        if ev["status"] != "IN_PROGRESS":
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot complete evaluation in status {ev['status']}")

        diagnosis_code = require_field(body, "diagnosis_code")
        severity_level = require_field(body, "severity_level")
        recommended_weekly_hours = require_field(body, "recommended_weekly_hours")

        if not isinstance(diagnosis_code, str) or not diagnosis_code.strip():
            raise APIError("ERR_VALIDATION", "diagnosis_code must be a non-empty string")
        if severity_level not in SEVERITY_LEVELS:
            raise APIError("ERR_VALIDATION", "severity_level must be LEVEL_1, LEVEL_2, or LEVEL_3")
        if not isinstance(recommended_weekly_hours, int) or isinstance(recommended_weekly_hours, bool):
            raise APIError("ERR_VALIDATION", "recommended_weekly_hours must be an integer")
        if not (5 <= recommended_weekly_hours <= 40):
            raise APIError("ERR_VALIDATION", "recommended_weekly_hours must be in [5, 40]")

        patient = get_patient(ev["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        ev["diagnosis_code"] = diagnosis_code
        ev["severity_level"] = severity_level
        ev["recommended_weekly_hours"] = recommended_weekly_hours
        ev["completed_at"] = clinic["now_ts"]
        ev["status"] = "COMPLETED"
        stamp_update(ev, now=clinic["now_ts"])

    body_out, status = success_response(serialize_evaluation(ev))
    return jsonify(body_out), status


@bp.post("/evaluations/<evaluation_id>/void")
@require_auth("ClinicAdmin")
def void_evaluation(evaluation_id):
    with get_lock():
        ev = get_evaluation(evaluation_id)
        if ev["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            raise APIError("ERR_INVALID_STATE",
                           f"Cannot void evaluation in status {ev['status']}")
        patient = get_patient(ev["patient_id"])
        clinic = get_store().clinics[patient["clinic_id"]]
        ev["status"] = "VOID"
        stamp_update(ev, now=clinic["now_ts"])
    body_out, status = success_response(serialize_evaluation(ev))
    return jsonify(body_out), status
