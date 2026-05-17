"""OASIS routes — SCAFFOLD §1.5 / PRD §3.3."""
from decimal import Decimal

from flask import Blueprint, jsonify

from ..auth import require_auth
from ..clock import clock_today_iso, parse_date
from ..errors import APIError
from ..helpers import get_json_body, optional_field, require_field
from ..responses import success_response
from ..services.calculations import to_decimal
from ..services.serialize import oasis_view
from ..store import get_lock, get_store, new_id, stamp_create, stamp_update


bp = Blueprint("oasis", __name__)


VALID_REASONS = {"START_OF_CARE", "RECERTIFICATION", "RESUMPTION_OF_CARE"}
VALID_CLINICAL = {"MMTA_OTHER", "NEURO", "WOUND", "MS_REHAB", "BEHAVIORAL", "COMPLEX"}
VALID_FUNCTIONAL = {"LOW", "MEDIUM", "HIGH"}
VALID_ADMISSION = {"COMMUNITY", "INSTITUTIONAL"}


def _find_patient(patient_id: str) -> dict:
    p = get_store().patients.get(patient_id)
    if p is None:
        raise APIError("ERR_NOT_FOUND", f"Patient {patient_id} not found")
    return p


def _find_oasis(patient_id: str, oasis_id: str) -> dict:
    # left-to-right: patient first
    _find_patient(patient_id)
    o = get_store().oasis_assessments.get(oasis_id)
    if o is None or o["patient_id"] != patient_id:
        raise APIError("ERR_NOT_FOUND", f"OASIS {oasis_id} not found for patient {patient_id}")
    return o


@bp.post("/patients/<patient_id>/oasis")
@require_auth("IntakeCoordinator")
def create_oasis(patient_id: str):
    patient = _find_patient(patient_id)
    body = get_json_body()

    reason = require_field(body, "assessment_reason")
    if reason not in VALID_REASONS:
        raise APIError(
            "ERR_VALIDATION",
            f"assessment_reason must be one of {sorted(VALID_REASONS)}",
        )
    assessment_date = require_field(body, "assessment_date")
    parse_date(assessment_date)

    clinical = require_field(body, "clinical_grouping")
    if clinical not in VALID_CLINICAL:
        raise APIError(
            "ERR_VALIDATION",
            f"clinical_grouping must be one of {sorted(VALID_CLINICAL)}",
        )
    functional = require_field(body, "functional_impairment_level")
    if functional not in VALID_FUNCTIONAL:
        raise APIError(
            "ERR_VALIDATION",
            f"functional_impairment_level must be one of {sorted(VALID_FUNCTIONAL)}",
        )
    admission = require_field(body, "admission_source")
    if admission not in VALID_ADMISSION:
        raise APIError(
            "ERR_VALIDATION",
            f"admission_source must be one of {sorted(VALID_ADMISSION)}",
        )

    hha_raw = optional_field(body, "hha_companion_hours_ordered", 0)
    if hha_raw is None:
        hha_raw = 0
    try:
        hha = to_decimal(hha_raw)
    except (TypeError, ValueError, Exception):
        raise APIError("ERR_VALIDATION", "hha_companion_hours_ordered must be a number")
    if hha < 0:
        raise APIError("ERR_VALIDATION", "hha_companion_hours_ordered must be >= 0")

    with get_lock():
        record = {
            "id": new_id(),
            "patient_id": patient["id"],
            "assessment_reason": reason,
            "assessment_date": assessment_date,
            "clinical_grouping": clinical,
            "functional_impairment_level": functional,
            "admission_source": admission,
            "hha_companion_hours_ordered": hha,
            "status": "DRAFT",
        }
        stamp_create(record)
        get_store().oasis_assessments[record["id"]] = record
        body_out, status = success_response(oasis_view(record), status=201)
    return jsonify(body_out), status


@bp.post("/patients/<patient_id>/oasis/<oasis_id>/lock")
@require_auth("IntakeCoordinator")
def lock_oasis(patient_id: str, oasis_id: str):
    with get_lock():
        oasis = _find_oasis(patient_id, oasis_id)
        if oasis["status"] != "DRAFT":
            raise APIError("ERR_OASIS_NOT_DRAFT", "OASIS is not in DRAFT")

        # All required fields populated — they are required on create, but
        # we double-check here per SCAFFOLD lock precondition.
        for f in ("assessment_reason", "clinical_grouping",
                  "functional_impairment_level", "admission_source"):
            if oasis.get(f) in (None, ""):
                raise APIError("ERR_VALIDATION", f"OASIS missing required field: {f}")

        reason = oasis["assessment_reason"]
        store = get_store()

        # Patient's prior episodes (chronological by start_date).
        patient_episodes = sorted(
            (e for e in store.episodes.values() if e["patient_id"] == patient_id),
            key=lambda e: (e["start_date"], e["created_at"]),
        )

        if reason == "RECERTIFICATION":
            # Must have a prior episode whose recert_due_date <= current_date <= end_date.
            today = clock_today_iso()
            ok = False
            for prior in patient_episodes:
                if prior["recert_due_date"] <= today <= prior["end_date"]:
                    ok = True
                    break
            if not ok:
                raise APIError(
                    "ERR_RECERT_WINDOW_VIOLATION",
                    "RECERT OASIS locked outside the prior episode's recertification window",
                )
        elif reason == "RESUMPTION_OF_CARE":
            has_open = any(e["status"] == "OPEN" for e in patient_episodes)
            if not has_open:
                raise APIError(
                    "ERR_VALIDATION",
                    "RESUMPTION_OF_CARE OASIS requires an existing OPEN episode",
                )
        # START_OF_CARE: no precondition.

        # Side effect: supersede other DRAFT OASIS for the same patient.
        for o in store.oasis_assessments.values():
            if (
                o["patient_id"] == patient_id
                and o["id"] != oasis["id"]
                and o["status"] == "DRAFT"
            ):
                o["status"] = "SUPERSEDED"
                stamp_update(o)

        # If this is a RECERTIFICATION lock, supersede any LOCKED prior OASIS
        # whose episode is now CLOSED or EXPIRED (closes the chain — see PRD §3.3).
        if reason == "RECERTIFICATION":
            for prior_o in store.oasis_assessments.values():
                if (
                    prior_o["patient_id"] == patient_id
                    and prior_o["id"] != oasis["id"]
                    and prior_o["status"] == "LOCKED"
                ):
                    # Find episode opened from this OASIS.
                    spawned = next(
                        (e for e in store.episodes.values()
                         if e.get("source_oasis_id") == prior_o["id"]),
                        None,
                    )
                    if spawned is not None and spawned["status"] in ("CLOSED", "EXPIRED"):
                        prior_o["status"] = "SUPERSEDED"
                        stamp_update(prior_o)

        oasis["status"] = "LOCKED"
        stamp_update(oasis)

        body_out, status = success_response(oasis_view(oasis))
    return jsonify(body_out), status


@bp.get("/patients/<patient_id>/oasis/<oasis_id>")
@require_auth("IntakeCoordinator", "BillingSpecialist")
def get_oasis(patient_id: str, oasis_id: str):
    o = _find_oasis(patient_id, oasis_id)
    body_out, status = success_response(oasis_view(o))
    return jsonify(body_out), status
