"""Payload factories — one per write endpoint, input fields only."""
import itertools

_counter = itertools.count(1)


def unique_suffix() -> int:
    return next(_counter)


_STATE_CODES = [
    a + b
    for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
]
_state_codes = iter(_STATE_CODES)


def unique_state_code() -> str:
    """A fresh uppercase two-character state code (PRD §3.1 uniqueness)."""
    return next(_state_codes)


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "state_code": unique_state_code(),
        "display_name": "Test Jurisdiction",
        "min_legal_review_days": 0,
        "ack_deadline_days": 30,
        "retention_years": 5,
        "required_language_codes": ["en"],
    }
    defaults.update(overrides)
    return defaults


def create_legal_reviewer_payload(jurisdiction_id, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "full_name": f"Counsel {unique_suffix()}",
        "bar_number": f"BAR-{unique_suffix():06d}",
    }
    defaults.update(overrides)
    return defaults


def create_employee_payload(jurisdiction_id, **overrides) -> dict:
    n = unique_suffix()
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "work_email": f"employee{n}@example.com",
        "full_name": f"Employee {n}",
    }
    defaults.update(overrides)
    return defaults


def create_policy_document_payload(**overrides) -> dict:
    defaults = {
        "title": f"Handbook Chapter {unique_suffix()}",
        "category": "CODE_OF_CONDUCT",
    }
    defaults.update(overrides)
    return defaults


def create_policy_version_payload(
    required_jurisdiction_ids, expected_policy_document_version, **overrides
) -> dict:
    defaults = {
        "body_text": "Canonical English policy body text.",
        "section_count": 2,
        "required_jurisdiction_ids": list(required_jurisdiction_ids),
        "expected_policy_document_version": expected_policy_document_version,
    }
    defaults.update(overrides)
    return defaults


def create_addendum_payload(jurisdiction_id, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "body_text": "State-specific amending text.",
    }
    defaults.update(overrides)
    return defaults


def create_legal_review_payload(jurisdiction_id, reviewer_id, due_at, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "reviewer_id": reviewer_id,
        "due_at": due_at,
    }
    defaults.update(overrides)
    return defaults


def create_translation_payload(language_code="en", **overrides) -> dict:
    defaults = {"language_code": language_code}
    defaults.update(overrides)
    return defaults


def create_release_package_payload(scope_jurisdiction_ids, effective_date, **overrides) -> dict:
    defaults = {
        "name": f"Release {unique_suffix()}",
        "effective_date": effective_date,
        "scope_jurisdiction_ids": list(scope_jurisdiction_ids),
    }
    defaults.update(overrides)
    return defaults


def create_acknowledgment_payload(assignment_id, **overrides) -> dict:
    defaults = {
        "assignment_id": assignment_id,
        "method": "ESIGN",
        "language_code": "en",
        "signature_text": "Typed Full Name",
    }
    defaults.update(overrides)
    return defaults


def create_policy_exception_payload(
    policy_version_id, expected_employee_version, **overrides
) -> dict:
    defaults = {
        "policy_version_id": policy_version_id,
        "reason_code": "RELIGIOUS",
        "justification": "Sincerely held religious objection.",
        "requested_days": 30,
        "expected_employee_version": expected_employee_version,
    }
    defaults.update(overrides)
    return defaults
