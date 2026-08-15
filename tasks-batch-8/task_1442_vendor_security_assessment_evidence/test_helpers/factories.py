"""Payload factories — one per writable endpoint, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS

DEFAULT_TEMPLATE_ITEMS = [
    {"item_key": "a", "prompt": "Control in place?", "weight": 1, "control_domain": "general"},
]

DEFAULT_ANSWERS = [{"item_key": "a", "answer_value": "YES"}]

DEFAULT_TASKS = [
    {"task_key": "t1", "description": "Remediate the finding", "due_at": "2026-09-01T00:00:00Z", "owner": "vendor"},
]


def create_tier_policy_payload(**overrides) -> dict:
    defaults = {
        "name": "Baseline Policy",
        "active": True,
        "tier_matrix": {},
        "tier1_reassessment_months": 36,
        "tier2_reassessment_months": 24,
        "tier3_reassessment_months": 12,
        "tier4_reassessment_months": 6,
    }
    defaults.update(overrides)
    return defaults


def create_template_payload(**overrides) -> dict:
    defaults = {
        "title": "Baseline Template",
        "applies_to_tiers": ["TIER_1"],
        "items": [dict(item) for item in DEFAULT_TEMPLATE_ITEMS],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": TEST_DEFAULTS["LEGAL_NAME"],
        "data_sensitivity": "INTERNAL",
        "access_level": "READ_ONLY",
        "criticality": "LOW",
    }
    defaults.update(overrides)
    return defaults


def create_contact_payload(**overrides) -> dict:
    defaults = {
        "email": TEST_DEFAULTS["CONTACT_EMAIL"],
        "full_name": TEST_DEFAULTS["CONTACT_NAME"],
        "is_primary": True,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(template_id: str, expected_vendor_version: int, **overrides) -> dict:
    defaults = {"template_id": template_id, "expected_vendor_version": expected_vendor_version}
    defaults.update(overrides)
    return defaults


def create_response_payload(**overrides) -> dict:
    defaults = {
        "submitted_by": TEST_DEFAULTS["SUBMITTED_BY"],
        "answers": [dict(a) for a in DEFAULT_ANSWERS],
    }
    defaults.update(overrides)
    return defaults


def create_evidence_payload(**overrides) -> dict:
    # Coverage window ending exactly on the default issuance day -> gap 0.
    defaults = {
        "kind": "SOC2_TYPE2",
        "period_start": "2025-08-01T00:00:00Z",
        "period_end": "2026-08-01T00:00:00Z",
        "issued_by": TEST_DEFAULTS["ISSUED_BY"],
    }
    defaults.update(overrides)
    return defaults


def create_exception_payload(**overrides) -> dict:
    defaults = {
        "source": "EVIDENCE",
        "severity": "MEDIUM",
        "description": "Control gap identified during review",
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(exception_ids, **overrides) -> dict:
    defaults = {
        "exception_ids": list(exception_ids),
        "tasks": [dict(t) for t in DEFAULT_TASKS],
    }
    defaults.update(overrides)
    return defaults


def create_acceptance_payload(exception_ids, **overrides) -> dict:
    defaults = {
        "exception_ids": list(exception_ids),
        "justification": "Residual risk accepted by business",
        "compensating_controls": ["enhanced monitoring"],
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_alert_payload(**overrides) -> dict:
    defaults = {
        "signal": "BREACH_REPORT",
        "severity": "CRITICAL",
        "detected_at": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_subprocessor_payload(**overrides) -> dict:
    defaults = {
        "subprocessor_name": "SubCo",
        "data_categories": ["PII"],
        "region": "us-east-1",
    }
    defaults.update(overrides)
    return defaults


def submit_attestation_payload(**overrides) -> dict:
    defaults = {
        "data_returned": True,
        "data_destroyed": True,
        "destruction_method": "crypto-shred",
        "attested_by": "Vendor CTO",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
