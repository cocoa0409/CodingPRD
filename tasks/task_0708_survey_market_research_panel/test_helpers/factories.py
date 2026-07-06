"""Payload factories — one per entity, input fields only.

Each factory supplies sensible defaults for the PRD's required input fields
and accepts **overrides for fields a test needs to control.
"""
import itertools

# Monotonic counter so factory-built emails/segments/IRBs stay unique within a
# single test (the database is reset before every test, so cross-test
# uniqueness is irrelevant — this only guards against in-test collisions).
_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_study_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Study",
        "irb_protocol_number": _uniq("IRB"),
        "estimated_minutes": 10,
        "base_incentive_points": 100,
        "screener_min_age": 0,
        # required_consent_version intentionally omitted by default (defaults to 1).
    }
    defaults.update(overrides)
    return defaults


def create_quota_cell_payload(**overrides) -> dict:
    defaults = {
        "segment_key": _uniq("SEG"),
        "target_n": 2,
    }
    defaults.update(overrides)
    return defaults


def create_panelist_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_uniq('p')}@example.com",
        "full_name": "Test Panelist",
        "age": 30,
        "segment_key": _uniq("SEG"),
    }
    defaults.update(overrides)
    return defaults


def create_consent_payload(panelist_id, study_id, **overrides) -> dict:
    defaults = {
        "panelist_id": panelist_id,
        "study_id": study_id,
        "consent_version": 1,
        "decision": "ACCEPTED",
    }
    defaults.update(overrides)
    return defaults


def create_participation_payload(study_id, panelist_id, quota_cell_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "panelist_id": panelist_id,
        "quota_cell_id": quota_cell_id,
    }
    defaults.update(overrides)
    return defaults


def create_attention_check_payload(**overrides) -> dict:
    defaults = {
        "check_kind": "TRAP_QUESTION",
        "passed": True,
    }
    defaults.update(overrides)
    return defaults


def submit_payload(**overrides) -> dict:
    defaults = {
        "completion_seconds": 600,
        "straightline_run": 0,
    }
    defaults.update(overrides)
    return defaults


def create_payout_request_payload(panelist_id, expected_panelist_version, **overrides) -> dict:
    defaults = {
        "panelist_id": panelist_id,
        "payout_method": "CASH",
        "points_requested": 100,
        "expected_panelist_version": expected_panelist_version,
    }
    defaults.update(overrides)
    return defaults


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Room"),
        "capacity": 10,
        # turnaround_minutes intentionally omitted by default (defaults to 0).
    }
    defaults.update(overrides)
    return defaults


def create_focus_group_payload(study_id, facility_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "facility_id": facility_id,
        "starts_at": "2026-04-01T10:00:00Z",
        "ends_at": "2026-04-01T11:00:00Z",
        "seats": 5,
    }
    defaults.update(overrides)
    return defaults


def create_focus_group_booking_payload(focus_group_id, panelist_id,
                                       expected_focus_group_version, **overrides) -> dict:
    defaults = {
        "focus_group_id": focus_group_id,
        "panelist_id": panelist_id,
        "expected_focus_group_version": expected_focus_group_version,
    }
    defaults.update(overrides)
    return defaults


def create_data_delivery_payload(study_id, **overrides) -> dict:
    defaults = {
        "study_id": study_id,
        "report_format": "CSV",
    }
    defaults.update(overrides)
    return defaults
