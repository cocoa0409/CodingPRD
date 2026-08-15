"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import DEFAULT_SCOPE, SCHEME_DEFAULTS, WITNESS_PASS_DATE


def create_scheme_payload(**overrides) -> dict:
    """All 21 rule constants of a scheme registration (PRD §3.1)."""
    defaults = dict(SCHEME_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Baking Co",
        "contact_email": "qa@acme.test",
        "country": "US",
    }
    defaults.update(overrides)
    return defaults


def create_auditor_payload(**overrides) -> dict:
    defaults = {
        "name": "Audrey Auditor",
        "competency_categories": ["BAKERY", "DAIRY", "MEAT"],
        "conflicted_client_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_witness_audit_payload(**overrides) -> dict:
    defaults = {
        "witnessed_on": WITNESS_PASS_DATE,
        "result": "PASS",
    }
    defaults.update(overrides)
    return defaults


def create_decision_maker_payload(**overrides) -> dict:
    defaults = {"name": "Dana Decider"}
    defaults.update(overrides)
    return defaults


def create_application_payload(scheme_id, **overrides) -> dict:
    defaults = {
        "scheme_id": scheme_id,
        "site_name": "Site A",
        "product_categories": [dict(entry) for entry in DEFAULT_SCOPE],
        "scope_text": "production of baked goods",
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(outcome="ACCEPTED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_assign_payload(auditor_id, **overrides) -> dict:
    defaults = {"auditor_id": auditor_id}
    defaults.update(overrides)
    return defaults


def create_reschedule_payload(window_start, window_end, **overrides) -> dict:
    defaults = {"window_start": window_start, "window_end": window_end}
    defaults.update(overrides)
    return defaults


def create_nonconformity_payload(**overrides) -> dict:
    defaults = {
        "grade": "MINOR",
        "clause_ref": "SQF 2.6.1",
        "description": "minor finding",
    }
    defaults.update(overrides)
    return defaults


def create_submit_report_payload(actual_days=1, **overrides) -> dict:
    defaults = {"actual_days": actual_days}
    defaults.update(overrides)
    return defaults


def create_decision_payload(outcome="GRANT", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_cap_payload(cap_text="corrective action plan", **overrides) -> dict:
    defaults = {"cap_text": cap_text}
    defaults.update(overrides)
    return defaults


def create_cap_review_payload(outcome="ACCEPT", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_suspend_payload(reason="manual regulatory hold", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def create_scope_change_payload(requested_categories, reason,
                                expected_certificate_version, **overrides) -> dict:
    defaults = {
        "requested_categories": requested_categories,
        "reason": reason,
        "expected_certificate_version": expected_certificate_version,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(certificate_id, grounds="appeal grounds",
                          **overrides) -> dict:
    defaults = {"certificate_id": certificate_id, "grounds": grounds}
    defaults.update(overrides)
    return defaults
