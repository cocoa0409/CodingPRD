"""Consent records, artifacts and the privacy cascade entry points (PRD 3.6)."""
from flask import Blueprint

import serializers
from auth import require_roles
from calc import ARTIFACT_SCOPE, retention_horizon, set_field
from cascade import run_consent_cascade
from clock import clock
from envelope import created, ok, paged_listing
from errors import ApiError
from store import by_created, db
from validators import (
    artifact_or_404,
    body,
    consent_or_404,
    filter_bool,
    filter_enum,
    opt_bool,
    participant_or_404,
    recruitment_or_404,
    ref,
    req_bool,
    req_enum,
    req_int,
    req_str,
    req_str_array,
    study_or_404,
)

bp = Blueprint("consent", __name__)

SCOPES = ("RECORDING", "TRANSCRIPT", "PII_QUOTE")
ARTIFACT_TYPES = ("RECORDING", "TRANSCRIPT", "PII_NOTE")
LIFECYCLE_STATES = ("RETAINED", "PURGED")
CONSENT_STATUSES = ("GRANTED", "REVOKED", "EXPIRED")


@bp.post("/consent-records")
@require_roles("Researcher", "ResearchLead", "PrivacyOfficer")
def create_consent():
    data = body()
    participant = participant_or_404(ref(data, "participant_id"))
    study = study_or_404(ref(data, "study_id"))
    req_str(data, "participant_id")
    req_str(data, "study_id")
    scopes = req_str_array(data, "scopes", allow_empty=False, allow_duplicates=False, members=SCOPES)
    retention_days = req_int(data, "retention_days", minimum=1)
    granted_at = clock.now()
    row = db.new("consents", {
        "participant_id": participant["id"],
        "study_id": study["id"],
        "scopes": list(scopes),
        "retention_days": retention_days,
        "granted_at": granted_at,
        "retention_until": retention_horizon(granted_at, scopes, retention_days),
        "status": "GRANTED",
        "revoked_at": None,
        "revocation_reason": None,
    })
    return created(serializers.consent(row))


@bp.post("/consent-records/<consent_id>/revoke")
@require_roles("PrivacyOfficer")
def revoke_consent(consent_id):
    consent = consent_or_404(consent_id)
    data = body()
    reason = req_str(data, "reason")
    if consent["status"] != "GRANTED":
        raise ApiError("ERR_INVALID_STATE", "Only a GRANTED consent record can be revoked.")
    set_field(consent, "status", "REVOKED")
    set_field(consent, "revoked_at", clock.now())
    set_field(consent, "revocation_reason", reason)
    run_consent_cascade(consent, "CONSENT_REVOKED")
    return ok(serializers.consent(consent))


@bp.get("/consent-records/<consent_id>")
@require_roles("Researcher", "ResearchLead", "PrivacyOfficer", "ResearchOpsAdmin")
def read_consent(consent_id):
    return ok(serializers.consent(consent_or_404(consent_id)))


@bp.get("/consent-records")
@require_roles("Researcher", "ResearchLead", "PrivacyOfficer", "ResearchOpsAdmin")
def list_consents():
    participant = participant_or_404(_filter_id("participant_id"))
    study = study_or_404(_filter_id("study_id"))
    status = filter_enum("status", CONSENT_STATUSES)
    rows = list(db.consents.values())
    if participant is not None:
        rows = [c for c in rows if c["participant_id"] == participant["id"]]
    if study is not None:
        rows = [c for c in rows if c["study_id"] == study["id"]]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    return paged_listing(by_created(rows), serializers.consent)


@bp.post("/recruitments/<recruitment_id>/artifacts")
@require_roles("Researcher", "ResearchLead")
def register_artifact(recruitment_id):
    recruitment = recruitment_or_404(recruitment_id)
    data = body()
    artifact_type = req_enum(data, "artifact_type", ARTIFACT_TYPES)
    contains_pii = req_bool(data, "contains_pii")
    required_scope = ARTIFACT_SCOPE[artifact_type]
    consent = None
    for candidate in by_created(list(db.consents.values())):
        if candidate["status"] != "GRANTED":
            continue
        if candidate["participant_id"] != recruitment["participant_id"]:
            continue
        if candidate["study_id"] != recruitment["study_id"]:
            continue
        if required_scope not in candidate["scopes"]:
            continue
        consent = candidate
        break
    if consent is None:
        raise ApiError(
            "ERR_CONSENT_SCOPE_MISSING",
            "No GRANTED consent record grants the %s scope." % required_scope,
        )
    row = db.new("artifacts", {
        "recruitment_id": recruitment["id"],
        "artifact_type": artifact_type,
        "contains_pii": contains_pii,
        "retention_until": consent["retention_until"],
        "lifecycle_state": "RETAINED",
        "purged_at": None,
        "purge_reason": None,
    })
    return created(serializers.artifact(row))


@bp.get("/recruitments/<recruitment_id>/artifacts")
@require_roles("Researcher", "ResearchLead", "PrivacyOfficer", "ResearchOpsAdmin")
def list_recruitment_artifacts(recruitment_id):
    recruitment = recruitment_or_404(recruitment_id)
    artifact_type = filter_enum("artifact_type", ARTIFACT_TYPES)
    lifecycle_state = filter_enum("lifecycle_state", LIFECYCLE_STATES)
    rows = [a for a in db.artifacts.values() if a["recruitment_id"] == recruitment["id"]]
    if artifact_type is not None:
        rows = [a for a in rows if a["artifact_type"] == artifact_type]
    if lifecycle_state is not None:
        rows = [a for a in rows if a["lifecycle_state"] == lifecycle_state]
    return paged_listing(by_created(rows), serializers.artifact)


@bp.get("/artifacts/<artifact_id>")
@require_roles("Researcher", "ResearchLead", "PrivacyOfficer", "ResearchOpsAdmin")
def read_artifact(artifact_id):
    return ok(serializers.artifact(artifact_or_404(artifact_id)))


@bp.get("/artifacts/<artifact_id>/evidence-links")
@require_roles("Researcher", "ResearchLead", "PrivacyOfficer", "ResearchOpsAdmin")
def list_artifact_links(artifact_id):
    artifact = artifact_or_404(artifact_id)
    is_admissible = filter_bool("is_admissible")
    rows = [l for l in db.links.values() if l["artifact_id"] == artifact["id"]]
    if is_admissible is not None:
        rows = [l for l in rows if l["is_admissible"] == is_admissible]
    return paged_listing(by_created(rows), serializers.link)


def _filter_id(name):
    from flask import request as flask_request
    raw = flask_request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw
