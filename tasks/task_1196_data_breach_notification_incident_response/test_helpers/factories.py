"""Payload factories — one per entity, input fields only (PRD §3)."""
from typing import Optional

# Default 64-hex preservation_hash (PRD §3.2: 64 lowercase hex chars).
DEFAULT_HASH = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"

# 200+ char notice body (PRD §3.7 submit-for-review requires body_text >= 200).
LONG_NOTICE_BODY = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod "
    "tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim "
    "veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea "
    "commodo consequat."
)


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "title": "Breach Incident",
        "discovered_at": "2026-04-28T10:00:00Z",
        "occurred_at": "2026-04-25T03:00:00Z",
        "source_channel": "INTERNAL_DETECTION",
    }
    defaults.update(overrides)
    return defaults


def create_forensic_scope_payload(**overrides) -> dict:
    defaults = {
        "scope_statement": "Initial scope",
        "systems_in_scope": ["CRM"],
        "data_elements_at_risk": ["SSN"],
        "exfiltration_likelihood_pct": 100,
    }
    defaults.update(overrides)
    return defaults


def create_evidence_item_payload(**overrides) -> dict:
    defaults = {
        "label": "firewall-log-2026-04-29.gz",
        "evidence_type": "LOG",
        "collected_at": "2026-04-29T00:00:00Z",
        "collected_by_user_id": "fl-default",
        "preservation_hash": DEFAULT_HASH,
    }
    defaults.update(overrides)
    return defaults


def create_custody_log_payload(evidence_item_id: str, **overrides) -> dict:
    defaults = {
        "evidence_item_id": evidence_item_id,
        "custodian_user_id": "custodian-1",
        "start_at": "2026-05-01T10:00:00Z",
        "end_at": "2026-05-01T12:00:00Z",
        "purpose": "intake",
    }
    defaults.update(overrides)
    return defaults


def create_affected_subject_payload(**overrides) -> dict:
    defaults = {
        "external_subject_ref": "SUBJ-1",
        "full_name": "Test Subject",
        "residence_state_code": "CA",
        "data_elements_exposed": ["SSN"],
        "record_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_evaluation_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "statute_reference": "Cal. Civ. Code 1798.82",
        "record_count_threshold": 1,
        "deadline_days": 30,
        "deadline_kind": "CALENDAR_DAYS",
        "requires_ag_notification": False,
        "requires_credit_agencies": False,
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(
    jurisdiction_evaluation_id: str,
    expected_incident_version: int,
    supersedes_notice_id: Optional[str] = None,
    **overrides,
) -> dict:
    defaults = {
        "jurisdiction_evaluation_id": jurisdiction_evaluation_id,
        "body_text": LONG_NOTICE_BODY,
        "expected_incident_version": expected_incident_version,
    }
    if supersedes_notice_id is not None:
        defaults["supersedes_notice_id"] = supersedes_notice_id
    defaults.update(overrides)
    return defaults


def create_mailing_batch_payload(
    notice_id: str,
    expected_incident_version: int,
    **overrides,
) -> dict:
    defaults = {
        "notice_id": notice_id,
        "vendor_code": "PRINTCO_A",
        "scheduled_ship_date": "2026-05-01T00:00:00Z",
        "expected_incident_version": expected_incident_version,
    }
    defaults.update(overrides)
    return defaults


def create_credit_monitoring_offer_payload(
    affected_subject_id: str, **overrides
) -> dict:
    defaults = {
        "affected_subject_id": affected_subject_id,
        "vendor_code": "CM_VENDOR_X",
        "term_months": 12,
        "unit_cost_cents": 999,
    }
    defaults.update(overrides)
    return defaults


def create_call_center_staffing_plan_payload(**overrides) -> dict:
    defaults = {
        "effective_from": "2026-05-02T00:00:00Z",
        "effective_until": "2026-06-02T00:00:00Z",
        "languages_supported": ["en"],
    }
    defaults.update(overrides)
    return defaults


def create_regulator_submission_payload(
    jurisdiction_evaluation_id: str, notice_id: str, **overrides
) -> dict:
    defaults = {
        "jurisdiction_evaluation_id": jurisdiction_evaluation_id,
        "notice_id": notice_id,
        "submission_channel": "PORTAL",
    }
    defaults.update(overrides)
    return defaults


def create_remediation_action_payload(**overrides) -> dict:
    defaults = {
        "title": "Rotate CRM API keys",
        "category": "TECHNICAL",
        "owner_user_id": "ic-owner-1",
        "due_at": "2026-05-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
