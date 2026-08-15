"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import CERT_EXPIRY


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": "CA",
        "name": "California",
        "level": "STATE",
        "eviction_notice_days": 3,
        "habitability_repair_days": 14,
        "deposit_cap_months": 1.0,
        "deposit_interest_required": False,
        "deposit_interest_rate_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_script_payload(jurisdiction_id, issue_category="EVICTION", version_no=1,
                          body="Standard counselor guidance script.",
                          supersedes_script_id=None) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
        "version_no": version_no,
        "body": body,
    }
    if supersedes_script_id is not None:
        payload["supersedes_script_id"] = supersedes_script_id
    return payload


def create_self_help_resource_payload(jurisdiction_id, linked_script_id,
                                      issue_category="EVICTION",
                                      title="Self-help guide",
                                      body="Caller-facing guidance.",
                                      language_code="en") -> dict:
    return {
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
        "title": title,
        "body": body,
        "language_code": language_code,
        "linked_script_id": linked_script_id,
    }


def create_counselor_payload(**overrides) -> dict:
    defaults = {
        "display_name": "Counselor",
        "languages": ["en"],
        "certified_jurisdiction_codes": ["CA"],
        "certified_categories": ["EVICTION"],
        "certification_expires_at": CERT_EXPIRY,
        "is_script_reviewer": False,
    }
    defaults.update(overrides)
    return defaults


def create_interpreter_payload(**overrides) -> dict:
    defaults = {"display_name": "Interpreter", "language_code": "es"}
    defaults.update(overrides)
    return defaults


def create_caller_payload(**overrides) -> dict:
    """Identified caller by default; anonymous callers omit the phone field
    unless a test explicitly passes phone= (PRD §3.4 null-phone rule)."""
    payload = {
        "alias": "caller-1",
        "preferred_language": "en",
        "channel": "PHONE",
        "is_anonymous": False,
    }
    if not overrides.get("is_anonymous", False):
        payload["phone"] = "+15550001"
    payload.update(overrides)
    return payload


def create_session_payload(caller_id, jurisdiction_id, issue_category="EVICTION",
                           **overrides) -> dict:
    payload = {
        "caller_id": caller_id,
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
    }
    payload.update(overrides)
    return payload


def create_case_payload(caller_id, session_id, jurisdiction_id,
                        issue_category="EVICTION", **facts) -> dict:
    payload = {
        "caller_id": caller_id,
        "opened_from_session_id": session_id,
        "jurisdiction_id": jurisdiction_id,
        "issue_category": issue_category,
    }
    payload.update(facts)
    return payload


def create_legal_aid_org_payload(**overrides) -> dict:
    defaults = {
        "name": "LegalAid X",
        "covered_jurisdiction_codes": ["CA"],
        "accepted_categories": ["EVICTION"],
        "weekly_capacity": 3,
    }
    defaults.update(overrides)
    return defaults


def create_retention_policy_payload(retention_days=30, jurisdiction_id=None,
                                    issue_category=None) -> dict:
    payload = {"retention_days": retention_days}
    if jurisdiction_id is not None:
        payload["jurisdiction_id"] = jurisdiction_id
    if issue_category is not None:
        payload["issue_category"] = issue_category
    return payload
