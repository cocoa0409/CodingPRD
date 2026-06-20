"""Scheduling: eligibility gate, level-of-service authorization, validation
precedence, and immediate leg creation.

Mixes difficulty queue A (cross_entity_state_dependency, priority_pair) and
corner queue B (validations, consistency_model).
"""
import pytest
from test_helpers import (
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    create_member_payload,
    create_eligibility_span_payload,
    create_trip_payload,
)
from test_helpers import fixtures

COORD = TEST_USERS["coordinator_headers"]


def _suspended_member_with_draft_trip(api, *, medicaid_id, mobility, trip_modality,
                                      trip_los, span_los="ROUTINE",
                                      span_end="2026-02-01T00:00:00Z",
                                      clock="2026-03-04T00:00:00Z",
                                      appointment="2026-03-05T09:00:00Z"):
    """Member whose only span has lapsed -> SUSPENDED after recompute, plus a DRAFT trip."""
    fixtures.set_clock(clock)
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id=medicaid_id, mobility_level=mobility,
                              home_county="C1"), COORD))
    get_success_data(api.create_eligibility_span(
        create_eligibility_span_payload(member["id"], level_of_service=span_los,
                                        coverage_start="2026-01-01T00:00:00Z",
                                        coverage_end=span_end), COORD))
    get_success_data(api.recompute_eligibility(member["id"], COORD))
    trip = get_success_data(api.create_trip(
        create_trip_payload(member["id"], modality=trip_modality,
                            requested_level_of_service=trip_los,
                            appointment_at=appointment, scheduled_loaded_miles=6,
                            is_round_trip=False), COORD))
    return member, trip


def test_schedule_requires_member_eligible(api):
    """PRD 3.3: "The member's `eligibility_status` must be `ELIGIBLE`; otherwise
    the schedule is rejected with `ERR_MEMBER_INELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_member_eligible
    """
    member, trip = _suspended_member_with_draft_trip(
        api, medicaid_id="M-CE1", mobility="WHEELCHAIR", trip_modality="WHEELCHAIR",
        trip_los="ROUTINE", span_los="BARIATRIC")
    resp = api.schedule_trip(trip["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_MEMBER_INELIGIBLE.value)
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["trip_status"] == "DRAFT"


def test_schedule_suspended_member_stays_draft(api):
    """PRD 3.3: "Scheduling advances a trip from `DRAFT` to `SCHEDULED` and is
    where eligibility and authorization are first enforced. The member's
    `eligibility_status` must be `ELIGIBLE`; otherwise the schedule is rejected
    with `ERR_MEMBER_INELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_member_eligible
    """
    member, trip = _suspended_member_with_draft_trip(
        api, medicaid_id="M-CE1b", mobility="AMBULATORY", trip_modality="AMBULATORY",
        trip_los="ROUTINE", span_los="ROUTINE")
    resp = api.schedule_trip(trip["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_MEMBER_INELIGIBLE.value)
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["trip_status"] == "DRAFT"


def test_ineligible_beats_los_on_schedule(api):
    """PRD 2.10: "Note in particular that the eligibility gate precedes every
    fiscal or provider check: a member who is not eligible fails with
    `ERR_MEMBER_INELIGIBLE` before the system ever considers modality, level of
    service, or provider availability."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_beats_los_on_schedule
    """
    # SUSPENDED member (span expired) AND requesting BARIATRIC above the ROUTINE span:
    # eligibility (priority 7) must beat LOS (priority 8).
    member, trip = _suspended_member_with_draft_trip(
        api, medicaid_id="M-PP1", mobility="WHEELCHAIR", trip_modality="WHEELCHAIR",
        trip_los="BARIATRIC", span_los="ROUTINE")
    resp = api.schedule_trip(trip["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_MEMBER_INELIGIBLE.value)
    after = get_success_data(api.get_trip(trip["id"], COORD))
    assert after["trip_status"] == "DRAFT"


def test_eligibility_gate_precedes_los_check(api):
    """PRD 2.10: "the eligibility gate precedes every fiscal or provider check: a
    member who is not eligible fails with `ERR_MEMBER_INELIGIBLE` before the
    system ever considers modality, level of service, or provider availability."

    Design: Difficulty/priority_pair_validation_conflict/ineligible_beats_los_on_schedule
    """
    member, trip = _suspended_member_with_draft_trip(
        api, medicaid_id="M-PP1b", mobility="STRETCHER", trip_modality="STRETCHER",
        trip_los="BARIATRIC", span_los="ROUTINE")
    resp = api.schedule_trip(trip["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_MEMBER_INELIGIBLE.value)


def test_los_not_authorized_when_span_below_requested(api):
    """PRD 3.3: "If the modality exceeds the member's mobility level, or no
    covering span exists at `appointment_at`, or the covering span's level of
    service is below what the trip requests, the schedule is rejected with
    `ERR_LOS_NOT_AUTHORIZED`."

    Design: Corner/validations/los_not_authorized_when_span_below_requested
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id="M-LO1", full_name="Los One",
                              mobility_level="WHEELCHAIR", home_county="C1"), COORD))
    get_success_data(api.create_eligibility_span(
        create_eligibility_span_payload(member["id"], level_of_service="ROUTINE",
                                        coverage_start="2026-01-01T00:00:00Z",
                                        coverage_end="2027-01-01T00:00:00Z"), COORD))
    trip = get_success_data(api.create_trip(
        create_trip_payload(member["id"], modality="WHEELCHAIR",
                            requested_level_of_service="BARIATRIC",
                            appointment_at="2026-03-02T09:00:00Z",
                            scheduled_loaded_miles=6, is_round_trip=False), COORD))
    resp = api.schedule_trip(trip["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_LOS_NOT_AUTHORIZED.value)


def test_los_not_authorized_when_modality_exceeds_mobility(api):
    """PRD 3.3: "The trip's required modality must be within the member's
    approval — the member's `mobility_level` rank must be at least the trip's
    `modality` rank ... If the modality exceeds the member's mobility level ...
    the schedule is rejected with `ERR_LOS_NOT_AUTHORIZED`."

    Design: Corner/validations/los_not_authorized_when_span_below_requested
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id="M-LO2", full_name="Los Two",
                              mobility_level="AMBULATORY", home_county="C1"), COORD))
    get_success_data(api.create_eligibility_span(
        create_eligibility_span_payload(member["id"], level_of_service="BARIATRIC",
                                        coverage_start="2026-01-01T00:00:00Z",
                                        coverage_end="2027-01-01T00:00:00Z"), COORD))
    # Member mobility AMBULATORY, trip requires WHEELCHAIR -> exceeds approval.
    trip = get_success_data(api.create_trip(
        create_trip_payload(member["id"], modality="WHEELCHAIR",
                            requested_level_of_service="ROUTINE",
                            appointment_at="2026-03-02T09:00:00Z",
                            scheduled_loaded_miles=6, is_round_trip=False), COORD))
    resp = api.schedule_trip(trip["id"], COORD)
    validate_error(resp, ApiErrorId.ERR_LOS_NOT_AUTHORIZED.value)


def test_schedule_creates_legs_visible_immediately(api):
    """PRD 3.3: "On success, the system creates the legs: one `OUTBOUND` leg in
    `PENDING`, and — only if `is_round_trip` is true — one `RETURN` leg in
    `PENDING` whose `is_will_call` is copied from the trip's `return_is_will_call`."
    PRD 4: "List a trip's Legs (OUTBOUND first, then RETURN, then created_at ASC)".

    Design: Corner/consistency_model/schedule_creates_legs_visible_immediately
    """
    fixtures.set_clock("2026-03-01T08:00:00Z")
    member = get_success_data(api.create_member(
        create_member_payload(medicaid_id="M-CM1", full_name="Cons One",
                              mobility_level="WHEELCHAIR", home_county="C1"), COORD))
    get_success_data(api.create_eligibility_span(
        create_eligibility_span_payload(member["id"], level_of_service="BARIATRIC",
                                        coverage_start="2026-01-01T00:00:00Z",
                                        coverage_end="2027-01-01T00:00:00Z"), COORD))
    trip = get_success_data(api.create_trip(
        create_trip_payload(member["id"], modality="WHEELCHAIR",
                            requested_level_of_service="ROUTINE",
                            appointment_at="2026-03-02T09:00:00Z",
                            scheduled_loaded_miles=10, is_round_trip=True,
                            return_is_will_call=True), COORD))
    get_success_data(api.schedule_trip(trip["id"], COORD))
    resp = api.list_trip_legs(trip["id"], COORD)
    data, meta = validate_paginated(resp)
    assert resp.json()["response_type"] == "array"
    assert meta["total_count"] == 2
    assert data[0]["direction"] == "OUTBOUND"
    assert data[1]["direction"] == "RETURN"
    assert data[1]["is_will_call"] is True
