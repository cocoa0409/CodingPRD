"""Allocation lifecycle: candidate set, ranking, family-size and accessibility filters,
PUBLISHED transition, no-eligible-application failure, ownership-gated confirm/reject.

Covers PRD §3.4 (allocation matching, public notice, objections), and supports
SCAFFOLD_DIFFICULTY_DESIGN instances:
- allocation_requires_unit_available (cross_entity_state_dependency)
- housing_unit_lease_overlap_closed_intervals (resource_temporal_overlap)

# difficulty: cross_entity_state_dependency/allocation_requires_unit_available
# difficulty: resource_temporal_overlap/housing_unit_lease_overlap_closed_intervals
"""

import pytest

from test_helpers import (
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_allocation_payload,
    create_application_in_draft,
    create_application_payload,
    create_housing_unit,
    create_program,
    create_published_allocation,
    create_queued_application,
    emit_full_passing_sync_events,
    enqueue_application,
    fresh_applicant_id,
    make_applicant_headers,
    make_household_member,
    setup_contract_active,
    submit_and_cross_check,
    validate_error,
    validate_success,
)


# ──────────────────────────────────────────────────────────
# Family-size tolerance (PRD §3.4)
# ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "apartment_type,family_size,permitted",
    [
        ("STUDIO", 1, True),
        ("STUDIO", 2, False),
        ("ONE_BEDROOM", 1, True),
        ("ONE_BEDROOM", 2, True),
        ("ONE_BEDROOM", 3, False),
        ("TWO_BEDROOM", 2, True),
        ("TWO_BEDROOM", 4, True),
        ("TWO_BEDROOM", 1, False),
        ("THREE_BEDROOM", 4, True),
        ("THREE_BEDROOM", 7, True),
        ("THREE_BEDROOM", 3, False),
    ],
)
def test_family_size_tolerance(apartment_type, family_size, permitted):
    """PRD §3.4: "The family-size tolerance is fixed: a STUDIO unit accepts only
    family_size exactly 1; a ONE_BEDROOM accepts family_size of 1 or 2; a TWO_BEDROOM
    accepts family_size of 2, 3, or 4; a THREE_BEDROOM accepts family_size of 4, 5, 6,
    or 7".
    """
    program = create_program()
    members = [make_household_member(citizen_id=f"C-{i}") for i in range(family_size)]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    application = enqueue_application(program["id"], application["id"])
    bedroom_count = {"STUDIO": 0, "ONE_BEDROOM": 1, "TWO_BEDROOM": 2, "THREE_BEDROOM": 3}[
        apartment_type
    ]
    unit = create_housing_unit(
        program["id"],
        apartment_type=apartment_type,
        bedroom_count=bedroom_count,
        accessibility_compliant=False,  # so requires_accessibility check doesn't help
    )
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    if permitted:
        allocation = validate_success(res, expected_status=201)
        assert allocation["status"] == "PUBLISHED"
        assert allocation["application_id"] == application["id"]
        assert allocation["housing_unit_id"] == unit["id"]
    else:
        validate_error(res, "ERR_NO_ELIGIBLE_APPLICATION")


# ──────────────────────────────────────────────────────────
# Accessibility (PRD §3.4)
# ──────────────────────────────────────────────────────────


def test_non_accessible_unit_excludes_accessibility_needers():
    """PRD §3.4: "when the unit's accessibility_compliant is false, every application
    whose requires_accessibility is true is excluded".
    """
    program = create_program()
    members = [make_household_member(has_disability=True)]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    application = enqueue_application(program["id"], application["id"])
    assert application["requires_accessibility"] is True
    unit = create_housing_unit(
        program["id"], apartment_type="ONE_BEDROOM", bedroom_count=1, accessibility_compliant=False
    )
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    validate_error(res, "ERR_NO_ELIGIBLE_APPLICATION")


def test_accessible_unit_keeps_all_candidates():
    """PRD §3.4: "when the unit's accessibility_compliant is true, no application is
    excluded on accessibility grounds — both accessibility-needers and others remain
    candidates".
    """
    program = create_program()
    members = [make_household_member(has_disability=False)]
    application, applicant_id = create_application_in_draft(
        program["id"], household_members=members
    )
    emit_full_passing_sync_events(program["id"], application)
    application = submit_and_cross_check(program["id"], application["id"], applicant_id)
    application = enqueue_application(program["id"], application["id"])
    unit = create_housing_unit(
        program["id"], apartment_type="ONE_BEDROOM", bedroom_count=1, accessibility_compliant=True
    )
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    allocation = validate_success(res, expected_status=201)
    assert allocation["application_id"] == application["id"]


# ──────────────────────────────────────────────────────────
# Difficulty: cross_entity_state_dependency/allocation_requires_unit_available
# ──────────────────────────────────────────────────────────


def test_allocation_rejected_when_unit_not_available_reserved():
    """PRD §3.4: "The selected unit must be in AVAILABLE, otherwise the request is
    rejected with ERR_UNIT_NOT_AVAILABLE".

    # difficulty: cross_entity_state_dependency/allocation_requires_unit_available
    """
    program = create_program()
    # First applicant takes the unit -> RESERVED.
    a1, _ = create_queued_application(program["id"])
    a2, _ = create_queued_application(program["id"])
    unit = create_housing_unit(program["id"], apartment_type="ONE_BEDROOM", bedroom_count=1)
    validate_success(
        api.create_allocation(
            program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    # Now try again on the same unit while it is RESERVED.
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


def test_allocation_rejected_when_unit_already_occupied():
    """PRD §3.4: "The selected unit must be in AVAILABLE, otherwise the request is
    rejected with ERR_UNIT_NOT_AVAILABLE". Second instance: unit in OCCUPIED status.

    # difficulty: cross_entity_state_dependency/allocation_requires_unit_available
    """
    program = create_program()
    # Walk one applicant to OCCUPIED on a unit.
    application, allocation, contract, unit, applicant_id = setup_contract_active(program["id"])
    assert unit["status"] == "OCCUPIED"
    # Try a new allocation on the OCCUPIED unit.
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


# ──────────────────────────────────────────────────────────
# Difficulty: resource_temporal_overlap/housing_unit_lease_overlap_closed_intervals
# ──────────────────────────────────────────────────────────


def test_unit_lease_overlap_blocks_second_allocation():
    """PRD §3.4: status semantics enforce closed-closed lease overlap — a unit becomes
    RESERVED on allocation and OCCUPIED on handover, and an allocation request requires
    the unit to be AVAILABLE. PRD §3.4: "the request is rejected with
    ERR_UNIT_NOT_AVAILABLE".

    # difficulty: resource_temporal_overlap/housing_unit_lease_overlap_closed_intervals
    """
    program = create_program(notice_period_length=1, grace_period_length=2)
    application, allocation, contract, unit, _ = setup_contract_active(
        program["id"], notice_period_length=1, unit_overrides={"monthly_base_rent_cents": 50_000}
    )
    # The unit is now OCCUPIED for the entire lease window.
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


def test_unit_lease_overlap_blocks_during_reserved_window():
    """PRD §3.4: "the request is rejected with ERR_UNIT_NOT_AVAILABLE". Second instance:
    overlap exists during the RESERVED window before handover too.

    # difficulty: resource_temporal_overlap/housing_unit_lease_overlap_closed_intervals
    """
    program = create_program()
    a1, _ = create_queued_application(program["id"])
    a2, _ = create_queued_application(program["id"])
    unit = create_housing_unit(program["id"])
    validate_success(
        api.create_allocation(
            program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
        ),
        expected_status=201,
    )
    # During RESERVED status, second allocation request is rejected.
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    validate_error(res, "ERR_UNIT_NOT_AVAILABLE")


# ──────────────────────────────────────────────────────────
# Allocation transitions cascade unit and application
# ──────────────────────────────────────────────────────────


def test_published_allocation_cascades_unit_to_reserved_and_app_to_allocated():
    """PRD §3.4: "As a single transactional bundle, the unit transitions from AVAILABLE
    to RESERVED, the picked application transitions from QUEUED to ALLOCATED".
    """
    program = create_program()
    allocation, application, unit, applicant_id = create_published_allocation(program["id"])
    assert allocation["status"] == "PUBLISHED"
    application = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    unit = validate_success(api.get_housing_unit(program["id"], unit["id"], OFFICER_HEADERS))
    assert application["status"] == "ALLOCATED"
    assert unit["status"] == "RESERVED"


def test_applicant_reject_allocation_returns_unit_to_available_and_app_to_queued():
    """PRD §3.5: "the applicant may instead reject the offered allocation while it is
    PUBLISHED; rejection transitions the allocation to REVERTED, returns the application
    from ALLOCATED to QUEUED, returns the housing unit from RESERVED to AVAILABLE".
    """
    program = create_program()
    allocation, application, unit, applicant_id = create_published_allocation(program["id"])
    headers = make_applicant_headers(applicant_id)
    res = api.reject_allocation(program["id"], allocation["id"], headers)
    allocation_after = validate_success(res)
    assert allocation_after["status"] == "REVERTED"
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    unit_after = validate_success(api.get_housing_unit(program["id"], unit["id"], OFFICER_HEADERS))
    assert application_after["status"] == "QUEUED"
    assert unit_after["status"] == "AVAILABLE"


def test_confirm_requires_notice_period_elapsed():
    """PRD §3.5: "the request is accepted only when current_period_index is greater than
    or equal to notice_end_period (else ERR_NOTICE_PERIOD_NOT_ELAPSED)".
    """
    program = create_program(notice_period_length=5)
    allocation, application, unit, applicant_id = create_published_allocation(program["id"])
    res = api.confirm_allocation(
        program["id"], allocation["id"], make_applicant_headers(applicant_id)
    )
    validate_error(res, "ERR_NOTICE_PERIOD_NOT_ELAPSED")


def test_confirm_requires_ownership():
    """PRD §3.5: "X-User-ID equals the parent application's applicant_user_id (else
    ERR_INSUFFICIENT_PERMISSIONS)".
    """
    program = create_program(notice_period_length=1)
    allocation, application, unit, applicant_id = create_published_allocation(program["id"])
    advance_clock_by(program["id"], 1)
    # Different applicant id.
    other_id = fresh_applicant_id("other")
    res = api.confirm_allocation(
        program["id"], allocation["id"], make_applicant_headers(other_id)
    )
    validate_error(res, "ERR_INSUFFICIENT_PERMISSIONS")


def test_no_eligible_application_when_queue_empty():
    """PRD §3.4: "If the candidate set is empty, the system rejects the request with
    ERR_NO_ELIGIBLE_APPLICATION".
    """
    program = create_program()
    unit = create_housing_unit(program["id"], apartment_type="ONE_BEDROOM", bedroom_count=1)
    res = api.create_allocation(
        program["id"], create_allocation_payload(unit["id"]), OFFICER_HEADERS
    )
    validate_error(res, "ERR_NO_ELIGIBLE_APPLICATION")
