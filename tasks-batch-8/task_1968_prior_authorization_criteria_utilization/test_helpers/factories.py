"""Payload factories — one per creatable resource, input fields only (PRD §3, §4)."""
import itertools

_npi_counter = itertools.count(9000000001)


def next_npi() -> str:
    """Distinct NPI per call so multiple providers can coexist in one test."""
    return str(next(_npi_counter))


def create_provider_payload(**overrides) -> dict:
    defaults = {"npi": next_npi(), "name": "Test Provider"}
    defaults.update(overrides)
    return defaults


def create_criteria_set_payload(**overrides) -> dict:
    defaults = {
        "name": "Spine Imaging Criteria",
        "line_of_business": "COMMERCIAL",
        "service_category": "IMAGING",
    }
    defaults.update(overrides)
    return defaults


def create_guideline_version_payload(**overrides) -> dict:
    defaults = {
        "version_label": "1.0",
        "content": "Clinical criteria content",
        "auto_approve_eligible": False,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_prior_auth_request_payload(**overrides) -> dict:
    defaults = {
        "member_ref": "M-01",
        "service_code": "72148",
        "urgency": "STANDARD",
        "intake_channel": "FAX",
        "documentation_complete": False,
    }
    defaults.update(overrides)
    return defaults


def reviewer_decision_payload(decision="APPROVE", reason_code=None) -> dict:
    payload = {"decision": decision}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return payload


def md_decision_payload(decision="APPROVE", reason_code=None) -> dict:
    payload = {"decision": decision}
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return payload


def p2p_schedule_payload(
    scheduled_start="2026-08-10T14:00:00Z",
    scheduled_end="2026-08-10T15:00:00Z",
    **overrides,
) -> dict:
    defaults = {
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def appeal_payload(appeal_reason="Appeal reason", **overrides) -> dict:
    defaults = {"appeal_reason": appeal_reason}
    defaults.update(overrides)
    return defaults


def appeal_decision_payload(outcome="UPHELD", rationale=None) -> dict:
    payload = {"outcome": outcome}
    if rationale is not None:
        payload["rationale"] = rationale
    return payload


def delegation_arrangement_payload(**overrides) -> dict:
    defaults = {"delegating_plan_name": "Plan X"}
    defaults.update(overrides)
    return defaults


def audit_finding_payload(**overrides) -> dict:
    defaults = {"finding_type": "NOTICE_DEFICIENT"}
    defaults.update(overrides)
    return defaults


def gold_card_evaluation_payload(service_category="IMAGING") -> dict:
    return {"service_category": service_category}


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
