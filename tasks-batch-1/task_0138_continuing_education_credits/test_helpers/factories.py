"""Payload factories — one per entity, input fields only.

Each factory builds the request body for a create/transition endpoint. Only
client-supplied (source: input) fields appear; system/computed fields are never
sent. Defaults can be overridden via **overrides.
"""
import itertools

# Monotonic license-number generator so each licensee in a test is unique on
# (home_board_id, license_number) without the caller having to bookkeep.
_license_seq = itertools.count(1)


def create_license_board_payload(**overrides) -> dict:
    defaults = {
        "name": "CA Board",
        "jurisdiction_code": "CA",
        "credit_unit": "CLE",
        "cycle_length_months": 24,
        "total_required_hours": 30.0,
        "carryover_cap_hours": 10.0,
        "reminder_lead_days": 60,
        "audit_cooldown_days": 365,
    }
    defaults.update(overrides)
    return defaults


def create_requirement_payload(category: str, min_hours: float, **overrides) -> dict:
    defaults = {"category": category, "min_hours": min_hours}
    defaults.update(overrides)
    return defaults


def create_provider_payload(board_id: str, **overrides) -> dict:
    defaults = {"name": "Provider P", "board_id": board_id}
    defaults.update(overrides)
    return defaults


def accredit_provider_payload(accredited_until: str = "2030-01-01T00:00:00Z", **overrides) -> dict:
    defaults = {"accredited_until": accredited_until}
    defaults.update(overrides)
    return defaults


def create_course_payload(provider_id: str, category: str, credit_hours: float,
                          title: str = "Course", **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "title": title,
        "category": category,
        "credit_hours": credit_hours,
    }
    defaults.update(overrides)
    return defaults


def create_licensee_payload(home_board_id: str, **overrides) -> dict:
    defaults = {
        "full_name": "Test Licensee",
        "home_board_id": home_board_id,
        "license_number": f"L-{next(_license_seq):05d}",
    }
    defaults.update(overrides)
    return defaults


def create_renewal_cycle_payload(licensee_id: str, board_id: str,
                                 cycle_start: str = "2026-01-01T00:00:00Z",
                                 **overrides) -> dict:
    defaults = {
        "licensee_id": licensee_id,
        "board_id": board_id,
        "cycle_start": cycle_start,
    }
    defaults.update(overrides)
    return defaults


def create_completion_payload(licensee_id: str, course_id: str, cycle_id: str,
                              completed_at: str = "2026-02-01T00:00:00Z",
                              **overrides) -> dict:
    defaults = {
        "licensee_id": licensee_id,
        "course_id": course_id,
        "cycle_id": cycle_id,
        "completed_at": completed_at,
    }
    defaults.update(overrides)
    return defaults


def create_reciprocity_grant_payload(licensee_id: str, target_cycle_id: str,
                                     source_jurisdiction_code: str, category: str,
                                     credit_hours: float, **overrides) -> dict:
    defaults = {
        "licensee_id": licensee_id,
        "target_cycle_id": target_cycle_id,
        "source_jurisdiction_code": source_jurisdiction_code,
        "category": category,
        "credit_hours": credit_hours,
    }
    defaults.update(overrides)
    return defaults


def renew_cycle_payload(expected_renewal_cycle_version: int, **overrides) -> dict:
    defaults = {"expected_renewal_cycle_version": expected_renewal_cycle_version}
    defaults.update(overrides)
    return defaults


def create_audit_payload(cycle_id: str, **overrides) -> dict:
    defaults = {"cycle_id": cycle_id}
    defaults.update(overrides)
    return defaults


def submit_attestation_payload(attested_hours: float,
                               statement: str = "I attest these completions are accurate.",
                               **overrides) -> dict:
    defaults = {"statement": statement, "attested_hours": attested_hours}
    defaults.update(overrides)
    return defaults


def decide_audit_payload(decision: str, **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
