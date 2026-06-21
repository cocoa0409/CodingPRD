"""Payload factories — one per entity, input fields only.

Field names match the PRD exactly. Only `source: input` fields appear.
"""
import itertools
from .constants import JURISDICTION_A

# Process-wide counters keep license/citation numbers unique within a run, so
# the unique-within-jurisdiction constraints never collide across helper calls.
_lic_counter = itertools.count(1)
_cit_counter = itertools.count(1)


def unique_license_number(prefix="LIC"):
    return f"{prefix}-{next(_lic_counter)}"


def unique_citation_number(prefix="CIT"):
    return f"{prefix}-{next(_cit_counter)}"


def create_jurisdiction_payload(**overrides) -> dict:
    """Standard Jurisdiction A fee schedule; override any field as needed."""
    defaults = dict(JURISDICTION_A)
    defaults.update(overrides)
    return defaults


def create_driver_payload(jurisdiction_id, **overrides) -> dict:
    defaults = {
        "jurisdiction_id": jurisdiction_id,
        "license_number": unique_license_number(),
        "full_name": "Test Driver",
    }
    defaults.update(overrides)
    return defaults


def create_citation_payload(driver_id, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "citation_number": unique_citation_number(),
        "issued_at": "2026-01-10T00:00:00Z",
        "appear_by": "2026-02-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(citation_id, **overrides) -> dict:
    defaults = {
        "citation_id": citation_id,
        "violation_code": "VC22350",
        "description": "Unsafe speed",
        "base_fine_cents": 20000,
        "points": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, method="CARD", installment_id=None, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "method": method,
    }
    if installment_id is not None:
        defaults["installment_id"] = installment_id
    defaults.update(overrides)
    return defaults


def create_installment_plan_payload(term_count, expected_citation_version,
                                    first_due_at="2026-03-01T00:00:00Z", **overrides) -> dict:
    defaults = {
        "term_count": term_count,
        "first_due_at": first_due_at,
        "expected_citation_version": expected_citation_version,
    }
    defaults.update(overrides)
    return defaults


def create_contest_request_payload(grounds="Disputed the violation", **overrides) -> dict:
    defaults = {"grounds": grounds}
    defaults.update(overrides)
    return defaults


def create_schedule_payload(hearing_at, **overrides) -> dict:
    defaults = {"hearing_at": hearing_at}
    defaults.update(overrides)
    return defaults


def create_decide_payload(verdict, **overrides) -> dict:
    defaults = {"verdict": verdict}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(completion_due_at="2026-04-01T00:00:00Z", **overrides) -> dict:
    defaults = {"completion_due_at": completion_due_at}
    defaults.update(overrides)
    return defaults
