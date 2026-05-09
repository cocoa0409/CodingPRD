"""Objections and the allocation revert/cycle behavior.

Covers PRD §3.4 (objection lifecycle) and supports
SCAFFOLD_DIFFICULTY_DESIGN instance:
- allocation_revert_cycle (non_linear_state_machine)

# difficulty: non_linear_state_machine/allocation_revert_cycle
"""

import pytest

from test_helpers import (
    CITIZEN_HEADERS,
    OFFICER_HEADERS,
    advance_clock_by,
    api_client as api,
    create_objection_payload,
    create_program,
    create_published_allocation,
    setup_under_objection_allocation,
    validate_error,
    validate_success,
)


def test_first_objection_cascades_allocation_to_under_objection():
    """PRD §3.4: "The first objection on a PUBLISHED allocation cascades the allocation
    to UNDER_OBJECTION".
    """
    program = create_program(notice_period_length=5)
    allocation, application, unit, _ = create_published_allocation(program["id"])
    res = api.create_objection(
        program["id"], allocation["id"], create_objection_payload(), CITIZEN_HEADERS
    )
    objection = validate_success(res, expected_status=201)
    assert objection["status"] == "PENDING_REVIEW"
    allocation_after = validate_success(
        api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS)
    )
    assert allocation_after["status"] == "UNDER_OBJECTION"


def test_subsequent_objection_keeps_allocation_under_objection():
    """PRD §3.4: "subsequent objections during the same window leave the allocation in
    UNDER_OBJECTION without further transition".
    """
    program = create_program(notice_period_length=5)
    allocation, objection, _application, _ = setup_under_objection_allocation(program["id"])
    # Submit a second objection.
    res = api.create_objection(
        program["id"], allocation["id"], create_objection_payload(), CITIZEN_HEADERS
    )
    validate_success(res, expected_status=201)
    allocation_after = validate_success(
        api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS)
    )
    assert allocation_after["status"] == "UNDER_OBJECTION"


def test_objection_outside_notice_window_rejected():
    """PRD §3.4: "Filing an objection is permitted only while the notice window is open
    — that is, while current_period_index is strictly less than notice_end_period; an
    attempt at or after notice_end_period is rejected with ERR_NOTICE_PERIOD_CLOSED".
    """
    program = create_program(notice_period_length=2)
    allocation, application, unit, _ = create_published_allocation(program["id"])
    advance_clock_by(program["id"], 2)  # current = notice_end_period (closed)
    res = api.create_objection(
        program["id"], allocation["id"], create_objection_payload(), CITIZEN_HEADERS
    )
    validate_error(res, "ERR_NOTICE_PERIOD_CLOSED")


def test_dismiss_last_pending_objection_returns_allocation_to_published():
    """PRD §3.4: "if the dismissed objection was the last PENDING_REVIEW objection on
    the allocation and no SUSTAINED objections exist on it, the allocation cascades from
    UNDER_OBJECTION back to PUBLISHED".

    # difficulty: non_linear_state_machine/allocation_revert_cycle
    """
    program = create_program(notice_period_length=10)
    allocation, objection, _application, _ = setup_under_objection_allocation(program["id"])
    # Dismiss the only pending objection.
    res = api.dismiss_objection(
        program["id"], allocation["id"], objection["id"], OFFICER_HEADERS
    )
    objection_after = validate_success(res)
    assert objection_after["status"] == "DISMISSED"
    allocation_after = validate_success(
        api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS)
    )
    assert allocation_after["status"] == "PUBLISHED"


def test_sustained_objection_reverts_allocation_and_cascades():
    """PRD §3.4: "A sustain transitions the objection from PENDING_REVIEW to SUSTAINED
    and cascades the parent allocation from UNDER_OBJECTION (or PUBLISHED) to REVERTED;
    the cascade returns the application from ALLOCATED to QUEUED, returns the housing
    unit from RESERVED to AVAILABLE".

    # difficulty: non_linear_state_machine/allocation_revert_cycle
    """
    program = create_program(notice_period_length=10)
    allocation, objection, application, _ = setup_under_objection_allocation(program["id"])
    res = api.sustain_objection(
        program["id"], allocation["id"], objection["id"], OFFICER_HEADERS
    )
    objection_after = validate_success(res)
    assert objection_after["status"] == "SUSTAINED"
    allocation_after = validate_success(
        api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS)
    )
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    unit_after = validate_success(
        api.get_housing_unit(program["id"], allocation["housing_unit_id"], OFFICER_HEADERS)
    )
    assert allocation_after["status"] == "REVERTED"
    assert application_after["status"] == "QUEUED"
    assert unit_after["status"] == "AVAILABLE"


def test_revert_cycle_published_to_under_objection_and_back_then_sustain():
    """PRD §3.4 cycle realization: PUBLISHED -> UNDER_OBJECTION -> PUBLISHED -> ... ->
    REVERTED.

    1) First objection moves PUBLISHED -> UNDER_OBJECTION.
    2) Dismissing returns it to PUBLISHED (cycle).
    3) A second objection re-enters UNDER_OBJECTION.
    4) Sustaining the new objection drives it to REVERTED.

    # difficulty: non_linear_state_machine/allocation_revert_cycle
    """
    program = create_program(notice_period_length=20)
    allocation, application, unit, _ = create_published_allocation(program["id"])
    # 1
    obj1 = validate_success(
        api.create_objection(
            program["id"], allocation["id"], create_objection_payload(), CITIZEN_HEADERS
        ),
        expected_status=201,
    )
    a = validate_success(api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS))
    assert a["status"] == "UNDER_OBJECTION"
    # 2
    validate_success(
        api.dismiss_objection(program["id"], allocation["id"], obj1["id"], OFFICER_HEADERS)
    )
    a = validate_success(api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS))
    assert a["status"] == "PUBLISHED"
    # 3
    obj2 = validate_success(
        api.create_objection(
            program["id"], allocation["id"], create_objection_payload(), CITIZEN_HEADERS
        ),
        expected_status=201,
    )
    a = validate_success(api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS))
    assert a["status"] == "UNDER_OBJECTION"
    # 4
    validate_success(
        api.sustain_objection(program["id"], allocation["id"], obj2["id"], OFFICER_HEADERS)
    )
    a = validate_success(api.get_allocation(program["id"], allocation["id"], OFFICER_HEADERS))
    application_after = validate_success(
        api.get_application(program["id"], application["id"], OFFICER_HEADERS)
    )
    unit_after = validate_success(api.get_housing_unit(program["id"], unit["id"], OFFICER_HEADERS))
    assert a["status"] == "REVERTED"
    assert application_after["status"] == "QUEUED"
    assert unit_after["status"] == "AVAILABLE"


def test_objection_resolution_requires_pending_state():
    """PRD §3.4: "Both sustain and dismiss require the objection to be PENDING_REVIEW;
    otherwise the operation is rejected with ERR_OBJECTION_NOT_PENDING".
    """
    program = create_program(notice_period_length=10)
    allocation, objection, _application, _ = setup_under_objection_allocation(program["id"])
    # Dismiss it once -> now DISMISSED.
    validate_success(
        api.dismiss_objection(program["id"], allocation["id"], objection["id"], OFFICER_HEADERS)
    )
    # Try to sustain the now-resolved objection.
    res = api.sustain_objection(
        program["id"], allocation["id"], objection["id"], OFFICER_HEADERS
    )
    validate_error(res, "ERR_OBJECTION_NOT_PENDING")
