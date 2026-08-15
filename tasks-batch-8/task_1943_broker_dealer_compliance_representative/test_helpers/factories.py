"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS


def create_branch_payload(**overrides) -> dict:
    defaults = {"name": "Test Branch", "region": TEST_DEFAULTS["REGION"]}
    defaults.update(overrides)
    return defaults


def create_representative_payload(branch_id: str, **overrides) -> dict:
    defaults = {
        "crd_number": "100001",
        "full_name": "Test Rep",
        "branch_id": branch_id,
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(
    branch_id: str, expected_branch_version, **overrides
) -> dict:
    defaults = {
        "branch_id": branch_id,
        "scheduled_date": TEST_DEFAULTS["INSPECTION_SCHEDULED_DATE"],
        "expected_branch_version": expected_branch_version,
    }
    defaults.update(overrides)
    return defaults


def close_inspection_payload(expected_branch_version, **overrides) -> dict:
    defaults = {"expected_branch_version": expected_branch_version}
    defaults.update(overrides)
    return defaults


def create_finding_payload(inspection_id: str, **overrides) -> dict:
    defaults = {
        "inspection_id": inspection_id,
        "severity": "LOW",
        "description": "Test finding",
        "due_date": TEST_DEFAULTS["FINDING_DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def remediate_payload(**overrides) -> dict:
    defaults = {"remediation_note": "remediated"}
    defaults.update(overrides)
    return defaults


def adjudicate_payload(decision: str = "VERIFY", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_correspondence_payload(rep_id: str, **overrides) -> dict:
    defaults = {
        "rep_id": rep_id,
        "channel": "EMAIL",
        "subject": "Client note",
        "lexicon_hits": 0,
    }
    defaults.update(overrides)
    return defaults


def review_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def create_activity_payload(**overrides) -> dict:
    # rep_id is never a payload field — bound from X-User-ID (PRD §3.4).
    defaults = {
        "activity_type": "OUTSIDE_BUSINESS_ACTIVITY",
        "description": "Outside activity",
        "compensation_expected": False,
        "start_date": TEST_DEFAULTS["ACTIVITY_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def decide_payload(decision: str = "APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def revoke_payload(**overrides) -> dict:
    defaults = {"reason": "policy change"}
    defaults.update(overrides)
    return defaults


def create_complaint_payload(rep_id: str, **overrides) -> dict:
    defaults = {
        "rep_id": rep_id,
        "allegation_type": "OTHER",
        "damages_claimed_cents": 100000,
        "received_date": TEST_DEFAULTS["RECEIVED_DATE"],
    }
    defaults.update(overrides)
    return defaults


def patch_complaint_payload(damages_claimed_cents, **overrides) -> dict:
    defaults = {"damages_claimed_cents": damages_claimed_cents}
    defaults.update(overrides)
    return defaults


def resolve_complaint_payload(**overrides) -> dict:
    defaults = {"damages_paid_cents": 0, "legal_cost_cents": 0}
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(rep_id: str, **overrides) -> dict:
    defaults = {
        "rep_id": rep_id,
        "event_type": "FELONY_CONVICTION",
        "event_date": TEST_DEFAULTS["DISCLOSURE_EVENT_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_plan_payload(rep_id: str, expected_representative_version, **overrides) -> dict:
    defaults = {
        "rep_id": rep_id,
        "start_date": "2026-08-03",
        "end_date": "2027-08-02",
        "conditions": ["MONTHLY_REVIEW"],
        "expected_representative_version": expected_representative_version,
    }
    defaults.update(overrides)
    return defaults


def create_meeting_payload(**overrides) -> dict:
    defaults = {"year": 2026, "meeting_date": "2026-12-15"}
    defaults.update(overrides)
    return defaults


def create_wsp_payload(**overrides) -> dict:
    defaults = {
        "policy_area": "CORRESPONDENCE",
        "title": "WSP Document",
        "effective_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_exam_request_payload(**overrides) -> dict:
    defaults = {
        "regulator": "FINRA",
        "request_ref": "R-1",
        "document_type": "TRADE_BLOTTER",
        "due_date": "2026-08-10",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
