"""MedicalEvidence: submit, accept, reject."""

from __future__ import annotations

from datetime import timedelta

from app import clock, store
from app.errors import bad_request, invalid_state, resource_not_found
from app.routes._helpers import fetch_claimant
from app.util import new_uuid, parse_iso_date


_VALID_SOURCE = {"LISTING_MATCH", "RFC_ASSESSMENT"}
_VALID_EXERTION = {"SEDENTARY", "LIGHT", "MEDIUM", "HEAVY"}
_VALID_SKILL = {"UNSKILLED", "SEMI_SKILLED", "SKILLED"}
_VALID_AGE_CAT = {"YOUNGER", "CLOSELY_APPROACHING", "ADVANCED"}
_VALID_EDU = {"ILLITERATE", "LIMITED", "HIGH_SCHOOL_OR_MORE"}


def submit_evidence(claimant_id: str, body: dict) -> dict:
    claimant = fetch_claimant(claimant_id)

    source_type = body.get("source_type")
    if source_type not in _VALID_SOURCE:
        raise bad_request("source_type must be LISTING_MATCH or RFC_ASSESSMENT")

    medical_findings = body.get("medical_findings")
    if not isinstance(medical_findings, str) or len(medical_findings) < 20:
        raise bad_request("medical_findings must be a string of at least 20 chars")

    if not body.get("evidence_date"):
        raise bad_request("evidence_date is required")
    evidence_date = parse_iso_date(body["evidence_date"], "evidence_date")

    aod = claimant["alleged_onset_date"]
    filing = claimant["filing_date"]
    upper_bound = filing + timedelta(days=730)
    if evidence_date < aod:
        raise bad_request("evidence_date must be on or after alleged_onset_date")
    if evidence_date > upper_bound:
        raise bad_request("evidence_date must be on or before filing_date + 730 days")

    listing_code = body.get("listing_code")
    rfc_exertional = body.get("rfc_exertional_level")
    rfc_skill = body.get("rfc_skill_level")
    age_cat = body.get("age_category_at_decision")
    edu = body.get("education_level")

    if source_type == "LISTING_MATCH":
        if not isinstance(listing_code, str) or not listing_code.strip():
            raise bad_request("listing_code is required when source_type=LISTING_MATCH")
        rfc_exertional = None
        rfc_skill = None
        age_cat = None
        edu = None
    else:  # RFC_ASSESSMENT
        if rfc_exertional not in _VALID_EXERTION:
            raise bad_request("rfc_exertional_level must be SEDENTARY|LIGHT|MEDIUM|HEAVY")
        if rfc_skill not in _VALID_SKILL:
            raise bad_request("rfc_skill_level must be UNSKILLED|SEMI_SKILLED|SKILLED")
        if age_cat not in _VALID_AGE_CAT:
            raise bad_request("age_category_at_decision must be YOUNGER|CLOSELY_APPROACHING|ADVANCED")
        if edu not in _VALID_EDU:
            raise bad_request("education_level must be ILLITERATE|LIMITED|HIGH_SCHOOL_OR_MORE")
        listing_code = None

    now = clock.now()
    new_id = new_uuid()
    record = {
        "id": new_id,
        "claimant_id": claimant_id,
        "source_type": source_type,
        "listing_code": listing_code,
        "rfc_exertional_level": rfc_exertional,
        "rfc_skill_level": rfc_skill,
        "age_category_at_decision": age_cat,
        "education_level": edu,
        "medical_findings": medical_findings,
        "evidence_date": evidence_date,
        "status": "SUBMITTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    with store.lock():
        store.medical_evidence[new_id] = record
    return record


def _fetch_evidence(claimant_id: str, evidence_id: str) -> dict:
    fetch_claimant(claimant_id)  # 404 first
    m = store.medical_evidence.get(evidence_id)
    if not m or m["claimant_id"] != claimant_id:
        raise resource_not_found(f"MedicalEvidence {evidence_id} not found")
    return m


def accept_evidence(claimant_id: str, evidence_id: str) -> dict:
    with store.lock():
        m = _fetch_evidence(claimant_id, evidence_id)
        if m["status"] != "SUBMITTED":
            raise invalid_state(f"Evidence in status {m['status']} cannot be accepted")
        m["status"] = "ACCEPTED"
        m["updated_at"] = clock.now()
        m["version"] += 1
    return m


def reject_evidence(claimant_id: str, evidence_id: str) -> dict:
    with store.lock():
        m = _fetch_evidence(claimant_id, evidence_id)
        if m["status"] != "SUBMITTED":
            raise invalid_state(f"Evidence in status {m['status']} cannot be rejected")
        m["status"] = "REJECTED"
        m["updated_at"] = clock.now()
        m["version"] += 1
    return m
