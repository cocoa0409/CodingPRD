"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import (
    ADULT_MOUSE_DOB,
    DEFAULT_PERIOD_END,
    DEFAULT_PERIOD_START,
    GRANT_EXPIRES_ISO,
    TEST_DEFAULTS,
)

# Unique-value counters so repeated creates inside one test never collide on
# unique fields (email, grant_number, cage_barcode, animal_tag).
_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


def create_investigator_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Dr. Test {n}",
        "email": f"pi{n}@uni.edu",
        "department": "Biology",
    }
    defaults.update(overrides)
    return defaults


def create_grant_payload(investigator_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "grant_number": f"R01-{n:05d}",
        "investigator_id": investigator_id,
        "budget_total_cents": TEST_DEFAULTS["GRANT_BUDGET_CENTS"],
        "expires_on": GRANT_EXPIRES_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_personnel_payload(**overrides) -> dict:
    n = _seq()
    defaults = {
        "full_name": f"Tech Test {n}",
        "email": f"tech{n}@uni.edu",
        "role_on_protocols": "TECHNICIAN",
    }
    defaults.update(overrides)
    return defaults


def create_training_enrollment_payload(personnel_id, **overrides) -> dict:
    defaults = {
        "personnel_id": personnel_id,
        "course_code": "ANIMAL_HANDLING",
    }
    defaults.update(overrides)
    return defaults


def create_occ_health_enrollment_payload(personnel_id, **overrides) -> dict:
    defaults = {"personnel_id": personnel_id}
    defaults.update(overrides)
    return defaults


def create_protocol_payload(investigator_id, grant_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "investigator_id": investigator_id,
        "grant_id": grant_id,
        "title": f"Study {n}",
        "species": "MOUSE",
        "max_animals_justified": TEST_DEFAULTS["MAX_ANIMALS_JUSTIFIED"],
        "pain_category": "C",
        "review_path": "DMR",
    }
    defaults.update(overrides)
    return defaults


def create_cage_payload(protocol_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "cage_barcode": f"CAGE-{n:05d}",
        "room_code": "VIV-101",
        "species": "MOUSE",
        "cage_kind": "STANDARD",
        "capacity_adults": 5,
        "protocol_id": protocol_id,
    }
    defaults.update(overrides)
    return defaults


def create_animal_payload(cage_id, protocol_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "animal_tag": f"TAG-{n:05d}",
        "cage_id": cage_id,
        "protocol_id": protocol_id,
        "species": "MOUSE",
        "date_of_birth": ADULT_MOUSE_DOB,
        "sex": "M",
    }
    defaults.update(overrides)
    return defaults


def create_litter_payload(cage_id, protocol_id, **overrides) -> dict:
    defaults = {
        "cage_id": cage_id,
        "protocol_id": protocol_id,
        "born_on": DEFAULT_PERIOD_START,
        "pup_count": 4,
    }
    defaults.update(overrides)
    return defaults


def create_census_record_payload(cage_id, **overrides) -> dict:
    defaults = {
        "cage_id": cage_id,
        "census_date": DEFAULT_PERIOD_START,
        "physical_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_billing_run_payload(**overrides) -> dict:
    defaults = {
        "period_start": DEFAULT_PERIOD_START,
        "period_end": DEFAULT_PERIOD_END,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "inspection_kind": "FACILITY",
        "scheduled_for": "2026-08-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def complete_inspection_payload(**overrides) -> dict:
    defaults = {
        "completed_at": "2026-08-15T00:00:00Z",
        "deficiency_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_adverse_event_payload(protocol_id, animal_id, reported_by_personnel_id,
                                 **overrides) -> dict:
    defaults = {
        "protocol_id": protocol_id,
        "animal_id": animal_id,
        "reported_by_personnel_id": reported_by_personnel_id,
        "severity": "MINOR",
        "description": "clinical observation",
    }
    defaults.update(overrides)
    return defaults


def create_protocol_deviation_payload(protocol_id, reported_by_personnel_id,
                                      **overrides) -> dict:
    defaults = {
        "protocol_id": protocol_id,
        "reported_by_personnel_id": reported_by_personnel_id,
        "description": "deviation narrative",
        "seriousness": "SERIOUS",
    }
    defaults.update(overrides)
    return defaults


def create_room_booking_payload(protocol_id, booked_by_personnel_id, **overrides) -> dict:
    n = _seq()
    defaults = {
        "room_code": f"PROC-{n:03d}",
        "protocol_id": protocol_id,
        "booked_by_personnel_id": booked_by_personnel_id,
        "start_at": "2026-08-15T09:00:00Z",
        "end_at": "2026-08-15T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def dmr_decision_payload(reviewer_id, decision="APPROVE") -> dict:
    """Single designated-member decision payload for a DMR protocol (PRD §3.3).

    Decisions bind to reviewer rows by their server-minted `reviewer_id` —
    the rows listed by GET /iacuc/protocols/{id}/reviewers after submission
    ("exactly one decision for the single `DESIGNATED_MEMBER` row").
    """
    return {"decisions": [{"reviewer_id": reviewer_id, "decision": decision}]}


def fcr_decision_payload(reviewer_ids, *decisions) -> dict:
    """Three committee-member decisions for an FCR protocol (PRD §3.3),
    zipped positionally with the given COMMITTEE_MEMBER reviewer ids."""
    return {
        "decisions": [
            {"reviewer_id": rid, "decision": d}
            for rid, d in zip(reviewer_ids, decisions)
        ]
    }
