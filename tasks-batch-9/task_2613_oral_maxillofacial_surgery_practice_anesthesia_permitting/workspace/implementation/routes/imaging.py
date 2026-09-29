"""Radiographic and cone-beam imaging studies."""
from flask import Blueprint

from db import clock_dt, db, new_record, ordered
from errors import ApiError
from middleware import authorize
from routes.helpers import ALL_ROLES, scope_check, send, send_list
from services.domain import (DOSE_FLAGS, JUSTIFICATION_CODES, MODALITIES,
                             path_row, referenced_row)
from services.imaging import dose_flag_for, justification_allowed, retention_until
from validation import (q_enum, q_string, read_body, v_enum, v_id, v_instant,
                        v_not_after, v_number)

bp = Blueprint("imaging", __name__)


@bp.post("/imaging-studies")
def create_study():
    authorize("Surgeon", "AnesthesiaCoordinator", "PracticeAdministrator")
    body = read_body(
        required=("patient_id", "modality", "justification_code", "acquired_at",
                  "dose_mgy_cm2"),
        optional=("case_id",),
    )
    patient_id = v_id(body, "patient_id")
    modality = v_enum(body, "modality", MODALITIES)
    justification_code = v_enum(body, "justification_code", JUSTIFICATION_CODES)
    acquired_at = v_instant(body, "acquired_at")
    dose_mgy_cm2 = v_number(body, "dose_mgy_cm2", exclusive_min=0)
    case_id = v_id(body, "case_id", default=None)
    v_not_after(acquired_at, "acquired_at", clock_dt())

    patient = referenced_row(db.patients, patient_id)
    case = referenced_row(db.cases, case_id) if case_id else None
    if case is not None:
        scope_check(case["practice_id"], patient["practice_id"])

    if not justification_allowed(modality, justification_code):
        raise ApiError("ERR_CBCT_JUSTIFICATION_INVALID")

    study = new_record({
        "patient_id": patient_id,
        "case_id": case_id,
        "modality": modality,
        "justification_code": justification_code,
        "acquired_at": acquired_at,
        "dose_mgy_cm2": dose_mgy_cm2,
        "dose_flag": dose_flag_for(modality, dose_mgy_cm2),
        "retention_until": retention_until(patient, acquired_at),
    }, immutable=True)
    db.studies[study["id"]] = study
    return send(study, 201)


@bp.get("/imaging-studies/<study_id>")
def read_study(study_id):
    authorize(*ALL_ROLES)
    return send(path_row(db.studies, study_id))


@bp.get("/imaging-studies")
def list_studies():
    authorize(*ALL_ROLES)
    patient_id = q_string("patient_id")
    case_id = q_string("case_id")
    modality = q_enum("modality", MODALITIES)
    dose_flag = q_enum("dose_flag", DOSE_FLAGS)
    rows = ordered([s for s in db.studies.values()
                    if (patient_id is None or s["patient_id"] == patient_id)
                    and (case_id is None or s.get("case_id") == case_id)
                    and (modality is None or s["modality"] == modality)
                    and (dose_flag is None or s["dose_flag"] == dose_flag)])
    return send_list(rows)
