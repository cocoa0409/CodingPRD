"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_representative_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "crd_number": f"CRD-{n:06d}",
        "full_name": f"Rep {n}",
        "email": f"rep{n}@example.com",
        "role_tier": "RR",
        "insurance_licensed": False,
        "resident_state_code": "NY",
        "prior_year_excess_hours": 0,
    }
    defaults.update(overrides)
    return defaults


def create_content_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "code": f"C-{n:06d}",
        "title": f"Course {n}",
        "ce_category": "FIRM_ELEMENT",
        "delivery_format": "ELEARNING",
        "credit_hours": 1.0,
        "min_passing_score": 70,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(content_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "content_id": content_id,
        "room_name": f"Room-{n}",
        "start_at": "2026-09-01T09:00:00Z",
        "end_at": "2026-09-01T11:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(rep_id, **overrides) -> dict:
    defaults = {"rep_id": rep_id}
    defaults.update(overrides)
    return defaults


def create_assignment_payload(rep_id, **overrides) -> dict:
    defaults = {"rep_id": rep_id, "cycle_year": 2026}
    defaults.update(overrides)
    return defaults


def create_plan_payload(rep_id, expected_representative_version, **overrides) -> dict:
    defaults = {
        "rep_id": rep_id,
        "plan_year": 2026,
        "expected_representative_version": expected_representative_version,
    }
    defaults.update(overrides)
    return defaults


def create_needs_analysis_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "analysis_document_ref": f"doc-na-{n}",
        "analysis_notes": "annual needs analysis",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(content_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "product_code": f"P-{n:06d}",
        "name": f"Product {n}",
        "required_training_content_id": content_id,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(rep_id, **overrides) -> dict:
    defaults = {
        "rep_id": rep_id,
        "state_code": "CA",
        "required_hours": 24,
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_blackout_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "label": f"blackout-{n}",
        "start_at": "2026-09-10T00:00:00Z",
        "end_at": "2026-09-11T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_complete_payload(score=90) -> dict:
    return {"score": score}


def create_void_payload(**overrides) -> dict:
    defaults = {"justification": "audit correction justification text"}
    defaults.update(overrides)
    return defaults


def create_reject_payload(**overrides) -> dict:
    defaults = {"reason": "insufficient learning objectives"}
    defaults.update(overrides)
    return defaults


def create_attest_payload(**overrides) -> dict:
    defaults = {"attestation_statement": "I attest to completing my firm element plan."}
    defaults.update(overrides)
    return defaults
