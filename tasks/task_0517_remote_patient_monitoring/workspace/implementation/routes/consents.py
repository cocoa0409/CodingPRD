"""ConsentRecord endpoints (PRD §3.1)."""
from flask import Blueprint

import errors
import serializers
import validation as V
from clock import clock, format_ts
from common import get_json_body, sort_by_created, parse_pagination, paginate
from db import db, stamp_create
from middleware import require_roles
from response import object_response, array_response
from services import lookups

bp = Blueprint("consents", __name__)

CONSENT_TYPES = {"RPM", "CCM", "BOTH"}


def _get_patient_or_404(pid):
    rec = db.patients.get(pid)
    if rec is None:
        raise errors.not_found("Patient not found.")
    return rec


@bp.post("/patients/<pid>/consents")
@require_roles("CareCoordinator")
def create_consent(pid):
    _get_patient_or_404(pid)
    body = get_json_body()
    consent_type = V.require_enum(body, "consent_type", CONSENT_TYPES)
    V.require_datetime(body, "effective_at")  # validate format
    effective_at = body["effective_at"]

    # Supersede a prior ACTIVE consent (PRD §3.1).
    prior = lookups.active_consent(pid)
    if prior is not None:
        prior["status"] = "SUPERSEDED"

    rec = {
        "patient_id": pid,
        "consent_type": consent_type,
        "effective_at": effective_at,
        "revoked_at": None,
        "status": "ACTIVE",
    }
    stamp_create(rec, common_fields=False)
    db.consents[rec["id"]] = rec
    return object_response(serializers.consent(rec), 201)


@bp.get("/patients/<pid>/consents")
@require_roles("CareCoordinator", "Physician", "BillingSpecialist")
def list_consents(pid):
    _get_patient_or_404(pid)
    limit, offset = parse_pagination()
    records = sort_by_created(lookups.consents_of(pid))
    page, total = paginate(records, limit, offset)
    return array_response([serializers.consent(r) for r in page],
                          limit, offset, total)


@bp.post("/patients/<pid>/consents/<consent_id>/revoke")
@require_roles("CareCoordinator")
def revoke_consent(pid, consent_id):
    _get_patient_or_404(pid)
    rec = db.consents.get(consent_id)
    if rec is None or rec["patient_id"] != pid:
        raise errors.not_found("Consent not found.")
    if rec["status"] != "ACTIVE":
        raise errors.invalid_state("Only an ACTIVE consent can be revoked.")
    rec["status"] = "REVOKED"
    rec["revoked_at"] = format_ts(clock.now())
    return object_response(serializers.consent(rec))
