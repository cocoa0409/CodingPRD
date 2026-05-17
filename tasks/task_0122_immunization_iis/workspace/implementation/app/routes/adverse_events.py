"""AdverseEvent routes: create, start-review, conclude-review, submit-vaers, read, list."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, g, jsonify, request

from .. import store
from ..auth import require_roles
from ..clock import format_iso, now, parse_iso
from ..errors import APIError
from ..helpers import (
    check_version_conflict,
    ensure_enum,
    is_bool,
    is_nonempty_list,
    optional_field,
    paginate,
    parse_iso_or_400,
    parse_json_body,
    parse_pagination,
    require_field,
)
from ..responses import build_envelope
from ..services.calculations import compute_vaers_required


bp = Blueprint("adverse_events", __name__)


SERIOUSNESS_VALUES = {"NON_SERIOUS", "SERIOUS", "DEATH"}
CONCLUSION_VALUES = {"CAUSALLY_RELATED", "NOT_RELATED"}
CLINICAL_REVIEW_STATUSES = {"PENDING_REVIEW", "UNDER_REVIEW", "CAUSALLY_RELATED", "NOT_RELATED"}
VAERS_SUBMISSION_STATUSES = {"NOT_SUBMITTED", "SUBMITTED", "ACK_RECEIVED", "REJECTED"}
ACK_OUTCOMES = {"ACK", "REJECT"}


def _serialize(a: dict) -> dict:
    return {
        "id": a["id"],
        "patient_id": a["patient_id"],
        "dose_id": a["dose_id"],
        "onset_at": a["onset_at"],
        "symptom_codes": a["symptom_codes"],
        "seriousness": a["seriousness"],
        "clinical_review_status": a["clinical_review_status"],
        "vaers_submission_status": a["vaers_submission_status"],
        "vaers_submission_id": a.get("vaers_submission_id"),
        "vaers_required": a["vaers_required"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def _require_ae(ae_id: str) -> dict:
    ae = store.adverse_events.get(ae_id)
    if not ae:
        raise APIError("ERR_ADVERSE_EVENT_NOT_FOUND", f"AdverseEvent {ae_id} not found.")
    return ae


# -----------------------------------------------------------------------------
# POST /adverse-events
# -----------------------------------------------------------------------------
@bp.post("/adverse-events")
@require_roles(["ProviderClinician", "ReviewingClinician"])
def create_adverse_event():
    body = parse_json_body()
    patient_id = require_field(body, "patient_id")
    if patient_id not in store.patients:
        raise APIError("ERR_PATIENT_NOT_FOUND", f"Patient {patient_id} not found.")
    dose_id = require_field(body, "dose_id")
    dose = store.administered_doses.get(dose_id)
    if not dose:
        raise APIError("ERR_DOSE_NOT_FOUND", f"Dose {dose_id} not found.")

    # State precondition: the dose must currently be ADMINISTERED.
    if dose["dose_state"] != "ADMINISTERED":
        raise APIError("ERR_INVALID_STATE", f"Dose is in state {dose['dose_state']}, not ADMINISTERED.")

    # Priority 81: dose must belong to patient.
    if dose["patient_id"] != patient_id:
        raise APIError("ERR_DOSE_PATIENT_MISMATCH", "Dose does not belong to patient.")

    onset_raw = require_field(body, "onset_at")
    onset_at = parse_iso_or_400(onset_raw, "onset_at")
    administered_at = parse_iso(dose["administered_at"])

    # Priority 90: onset_at must be in [administered_at, administered_at + 42d].
    if onset_at < administered_at:
        raise APIError("ERR_ONSET_OUT_OF_WINDOW", "onset_at must be at or after administered_at.")
    if onset_at > administered_at + timedelta(days=42):
        raise APIError("ERR_ONSET_OUT_OF_WINDOW", "onset_at must be within 42 days of administered_at.")

    symptom_codes = require_field(body, "symptom_codes", type_check=is_nonempty_list)
    for sc in symptom_codes:
        if not isinstance(sc, str) or not sc:
            raise APIError("ERR_VALIDATION", "symptom_codes entries must be non-empty strings.")
    seriousness = ensure_enum(require_field(body, "seriousness"), SERIOUSNESS_VALUES, "seriousness")

    vaers_required = compute_vaers_required(seriousness, onset_at, administered_at)

    with store.lock:
        rec = {
            "patient_id": patient_id,
            "dose_id": dose_id,
            "onset_at": format_iso(onset_at),
            "symptom_codes": list(symptom_codes),
            "seriousness": seriousness,
            "clinical_review_status": "PENDING_REVIEW",
            "vaers_submission_status": "NOT_SUBMITTED",
            "vaers_submission_id": None,
            "vaers_required": vaers_required,
        }
        store.stamp_create(rec)
        store.adverse_events[rec["id"]] = rec

    return jsonify(build_envelope(_serialize(rec), "object")), 201


# -----------------------------------------------------------------------------
# POST /adverse-events/{id}/start-review
# -----------------------------------------------------------------------------
@bp.post("/adverse-events/<ae_id>/start-review")
@require_roles(["ReviewingClinician"])
def start_review(ae_id: str):
    body = parse_json_body(required=False)
    ae = _require_ae(ae_id)
    if ae["clinical_review_status"] != "PENDING_REVIEW":
        raise APIError("ERR_INVALID_STATE", f"AdverseEvent clinical_review_status is {ae['clinical_review_status']}.")
    check_version_conflict(body, ae)
    # SOD is NOT enforced on start-review per the PRD's SOD scope (conclude and submit only).
    with store.lock:
        ae["clinical_review_status"] = "UNDER_REVIEW"
        store.stamp_update(ae)
    return jsonify(build_envelope(_serialize(ae), "object")), 200


# -----------------------------------------------------------------------------
# POST /adverse-events/{id}/conclude-review
# -----------------------------------------------------------------------------
@bp.post("/adverse-events/<ae_id>/conclude-review")
@require_roles(["ReviewingClinician"])
def conclude_review(ae_id: str):
    body = parse_json_body()
    ae = _require_ae(ae_id)
    if ae["clinical_review_status"] != "UNDER_REVIEW":
        raise APIError("ERR_INVALID_STATE", f"AdverseEvent clinical_review_status is {ae['clinical_review_status']}.")
    # SOD: priority 61.
    dose = store.administered_doses.get(ae["dose_id"])
    if dose and g.user_id == dose.get("administering_clinician_id"):
        raise APIError("ERR_SOD_VIOLATION", "Reviewing clinician must differ from administering clinician.")
    conclusion = ensure_enum(require_field(body, "conclusion"), CONCLUSION_VALUES, "conclusion")
    check_version_conflict(body, ae)
    with store.lock:
        ae["clinical_review_status"] = conclusion
        store.stamp_update(ae)
    return jsonify(build_envelope(_serialize(ae), "object")), 200


# -----------------------------------------------------------------------------
# POST /adverse-events/{id}/submit-vaers
# -----------------------------------------------------------------------------
@bp.post("/adverse-events/<ae_id>/submit-vaers")
@require_roles(["ReviewingClinician"])
def submit_vaers(ae_id: str):
    body = parse_json_body(required=False)
    ae = _require_ae(ae_id)
    # State guard: vaers_submission_status must be NOT_SUBMITTED.
    if ae["vaers_submission_status"] != "NOT_SUBMITTED":
        raise APIError("ERR_VAERS_ALREADY_SUBMITTED", "AdverseEvent already submitted to VAERS.")
    if ae["clinical_review_status"] not in {"UNDER_REVIEW", "CAUSALLY_RELATED", "NOT_RELATED"}:
        raise APIError("ERR_INVALID_STATE", "Clinical review must be at least UNDER_REVIEW before submission.")
    # SOD: priority 61.
    dose = store.administered_doses.get(ae["dose_id"])
    if dose and g.user_id == dose.get("administering_clinician_id"):
        raise APIError("ERR_SOD_VIOLATION", "Reviewing clinician must differ from administering clinician.")
    elective = optional_field(body, "elective", default=False, type_check=is_bool)
    if not ae["vaers_required"] and not elective:
        raise APIError("ERR_VAERS_NOT_REPORTABLE", "AdverseEvent is not VAERS-reportable.")
    check_version_conflict(body, ae)
    with store.lock:
        ae["vaers_submission_status"] = "SUBMITTED"
        ae["vaers_submission_id"] = store.new_id()
        store.stamp_update(ae)
    return jsonify(build_envelope(_serialize(ae), "object")), 200


# -----------------------------------------------------------------------------
# GET /adverse-events/{id}
# -----------------------------------------------------------------------------
@bp.get("/adverse-events/<ae_id>")
@require_roles(["ReviewingClinician", "ProviderClinician", "PublicHealthOfficer"])
def read_ae(ae_id: str):
    ae = _require_ae(ae_id)
    return jsonify(build_envelope(_serialize(ae), "object")), 200


# -----------------------------------------------------------------------------
# GET /adverse-events
# -----------------------------------------------------------------------------
@bp.get("/adverse-events")
@require_roles(["ReviewingClinician", "PublicHealthOfficer"])
def list_ae():
    limit, offset = parse_pagination()
    crs = request.args.get("clinical_review_status")
    vss = request.args.get("vaers_submission_status")
    seriousness = request.args.get("seriousness")
    if crs is not None and crs not in CLINICAL_REVIEW_STATUSES:
        raise APIError("ERR_VALIDATION", "clinical_review_status filter invalid.")
    if vss is not None and vss not in VAERS_SUBMISSION_STATUSES:
        raise APIError("ERR_VALIDATION", "vaers_submission_status filter invalid.")
    if seriousness is not None and seriousness not in SERIOUSNESS_VALUES:
        raise APIError("ERR_VALIDATION", "seriousness filter invalid.")
    rows = list(store.adverse_events.values())
    if crs is not None:
        rows = [r for r in rows if r["clinical_review_status"] == crs]
    if vss is not None:
        rows = [r for r in rows if r["vaers_submission_status"] == vss]
    if seriousness is not None:
        rows = [r for r in rows if r["seriousness"] == seriousness]
    rows.sort(key=lambda r: r["created_at"])
    page, meta = paginate(rows, limit, offset)
    return jsonify(build_envelope([_serialize(r) for r in page], "array", meta)), 200
