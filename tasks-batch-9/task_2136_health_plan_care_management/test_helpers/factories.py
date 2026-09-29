"""Payload factories — one per resource, carrying only client-supplied fields."""
import itertools

from .constants import TEST_DEFAULTS

_member_seq = itertools.count(1)


def next_external_member_id(prefix: str = "MBR") -> str:
    """PRD §3.1 requires external_member_id to be unique across all members."""
    return f"{prefix}-{next(_member_seq):06d}"


def create_member_payload(**overrides) -> dict:
    payload = {
        "external_member_id": next_external_member_id(),
        "full_name": "Test Member",
        "birth_date": "1970-01-01",
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "chronic_condition_count": 0,
    }
    payload.update(overrides)
    return payload


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": "Test Care Management Program",
        "min_risk_tier": "LOW",
        "stratification_variant": "CONCURRENT",
        "required_credential_levels": ["RN"],
        "staff_minute_budget": TEST_DEFAULTS["STAFF_MINUTE_BUDGET"],
        "hourly_cost_cents": TEST_DEFAULTS["HOURLY_COST_CENTS"],
        "cohort_benchmark_pmpm_cents": TEST_DEFAULTS["COHORT_BENCHMARK_PMPM_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_care_manager_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Care Manager",
        "credential_level": "RN",
        "licensed_state_codes": [TEST_DEFAULTS["STATE_CODE"]],
        "capacity_points": TEST_DEFAULTS["CAPACITY_POINTS"],
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(member_id, program_id, care_manager_id=None, **overrides):
    payload = {"member_id": member_id, "program_id": program_id}
    if care_manager_id is not None:
        payload["care_manager_id"] = care_manager_id
    payload.update(overrides)
    return payload


def create_transition_event_payload(member_id, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "event_type": "ED_VISIT",
        "occurred_at": "2026-07-20T00:00:00Z",
        "facility_name": "Bay General",
        "episode_cost_cents": 0,
        "adjudication_status": "CLOSED",
    }
    payload.update(overrides)
    return payload


def create_care_plan_payload(enrollment_id, **overrides) -> dict:
    payload = {"enrollment_id": enrollment_id, "title": "Test care plan"}
    payload.update(overrides)
    return payload


def create_goal_payload(**overrides) -> dict:
    payload = {
        "domain": "CLINICAL",
        "description": "Test goal description",
        "target_date": "2026-12-01",
    }
    payload.update(overrides)
    return payload


def create_intervention_payload(**overrides) -> dict:
    payload = {"modality": "PHONE", "staff_minutes": 20}
    payload.update(overrides)
    return payload


def create_touch_payload(enrollment_id, care_manager_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "care_manager_id": care_manager_id,
        "touch_type": "ROUTINE",
        "modality": "PHONE",
        "scheduled_start_at": "2026-08-10T09:00:00Z",
        "scheduled_end_at": "2026-08-10T09:30:00Z",
    }
    payload.update(overrides)
    return payload


def create_social_need_payload(enrollment_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "domain": "FOOD",
        "severity": "MODERATE",
    }
    payload.update(overrides)
    return payload


def create_community_resource_payload(**overrides) -> dict:
    payload = {
        "name": "Test Community Organization",
        "served_domains": ["FOOD"],
        "service_state_codes": [TEST_DEFAULTS["STATE_CODE"]],
        "concurrent_slot_capacity": TEST_DEFAULTS["CONCURRENT_SLOT_CAPACITY"],
        "contract_status": "CONTRACTED",
    }
    payload.update(overrides)
    return payload


def create_referral_payload(social_need_id, community_resource_id, **overrides) -> dict:
    payload = {
        "social_need_id": social_need_id,
        "community_resource_id": community_resource_id,
        "service_start_at": "2026-08-10T09:00:00Z",
        "service_end_at": "2026-08-10T11:00:00Z",
    }
    payload.update(overrides)
    return payload
