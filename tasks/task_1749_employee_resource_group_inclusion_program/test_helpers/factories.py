"""Payload factories — one per entity, input fields only.

Optional inputs are omitted from the payload entirely when None so requests
exercise the server's documented defaults.
"""

from .constants import (
    DEFAULT_EVENT_ENDS_AT,
    DEFAULT_EVENT_STARTS_AT,
    STANDARD_TERM_ENDS_AT,
)


def create_program_payload(fiscal_year=2027, pool_total_cents=100000, goals=None) -> dict:
    payload = {"fiscal_year": fiscal_year, "pool_total_cents": pool_total_cents}
    if goals is not None:
        payload["goals"] = goals
    return payload


def create_sponsor_payload(employee_id, max_groups=3, max_mentees=2) -> dict:
    return {
        "employee_id": employee_id,
        "max_groups": max_groups,
        "max_mentees": max_mentees,
    }


def create_group_payload(
    program_id,
    name,
    mission_statement="A test mission statement",
    category="AFFINITY",
    owner_employee_id=None,
) -> dict:
    payload = {
        "program_id": program_id,
        "name": name,
        "mission_statement": mission_statement,
        "category": category,
    }
    if owner_employee_id is not None:
        payload["owner_employee_id"] = owner_employee_id
    return payload


def assign_sponsor_payload(sponsor_id, expected_group_version) -> dict:
    return {
        "sponsor_id": sponsor_id,
        "expected_group_version": expected_group_version,
    }


def create_membership_payload(group_id, employee_id=None) -> dict:
    payload = {"group_id": group_id}
    if employee_id is not None:
        payload["employee_id"] = employee_id
    return payload


def create_leadership_term_payload(
    group_id,
    leader_employee_id,
    ends_at=STANDARD_TERM_ENDS_AT,
    predecessor_term_id=None,
) -> dict:
    payload = {
        "group_id": group_id,
        "leader_employee_id": leader_employee_id,
        "ends_at": ends_at,
    }
    if predecessor_term_id is not None:
        payload["predecessor_term_id"] = predecessor_term_id
    return payload


def create_funding_request_payload(
    group_id,
    category="EVENT",
    purpose="Test purpose",
    requested_cents=100000,
    external_matching_cents=None,
) -> dict:
    payload = {
        "group_id": group_id,
        "category": category,
        "purpose": purpose,
        "requested_cents": requested_cents,
    }
    if external_matching_cents is not None:
        payload["external_matching_cents"] = external_matching_cents
    return payload


def create_venue_payload(name="Main Hall", capacity=100) -> dict:
    return {"name": name, "capacity": capacity}


def create_event_payload(
    group_id,
    venue_id,
    title="Test Event",
    category="SOCIAL",
    starts_at=DEFAULT_EVENT_STARTS_AT,
    ends_at=DEFAULT_EVENT_ENDS_AT,
    capacity=10,
    funding_request_id=None,
) -> dict:
    payload = {
        "group_id": group_id,
        "venue_id": venue_id,
        "title": title,
        "category": category,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }
    if funding_request_id is not None:
        payload["funding_request_id"] = funding_request_id
    return payload


def reschedule_event_payload(
    starts_at,
    ends_at,
    expected_event_version,
    venue_id=None,
) -> dict:
    payload = {
        "starts_at": starts_at,
        "ends_at": ends_at,
        "expected_event_version": expected_event_version,
    }
    if venue_id is not None:
        payload["venue_id"] = venue_id
    return payload


def create_rsvp_payload(event_id) -> dict:
    return {"event_id": event_id}


def create_climate_survey_payload(
    program_id,
    title="Pulse",
    opens_at="2026-08-01T00:00:00Z",
    closes_at="2026-09-01T00:00:00Z",
    min_responses=1,
) -> dict:
    return {
        "program_id": program_id,
        "title": title,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "min_responses": min_responses,
    }


def create_survey_response_payload(
    survey_id,
    belonging_score=4,
    growth_score=4,
    fairness_score=4,
    safety_score=4,
) -> dict:
    return {
        "survey_id": survey_id,
        "belonging_score": belonging_score,
        "growth_score": growth_score,
        "fairness_score": fairness_score,
        "safety_score": safety_score,
    }


def create_mentoring_engagement_payload(
    program_id,
    sponsor_id,
    starts_at="2026-09-01T00:00:00Z",
    ends_at="2026-09-15T00:00:00Z",
    mentee_employee_id=None,
) -> dict:
    payload = {
        "program_id": program_id,
        "sponsor_id": sponsor_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    if mentee_employee_id is not None:
        payload["mentee_employee_id"] = mentee_employee_id
    return payload
