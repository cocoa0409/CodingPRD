"""Two scarce resources booked with deliberately opposite adjacency rules.

A suite window is half-open and carries a directional changeover buffer, so a
batch may start at the exact instant the buffer expires. A lead operator's window
is closed at both ends and spans every suite, so windows that merely touch do
collide.
"""
from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    constants,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import PROGRAM_MANAGER

Json = Dict[str, Any]


def _book(api, program: Json, suite_id: str, qualification_id: str, **kwargs: Any):
    """Attempt a second batch, returning the raw response for inspection."""
    return api.create_batch_order(
        factories.batch_order_payload(
            program["project_id"],
            suite_id,
            qualification_id,
            fixtures.suite_version(api, suite_id),
            batch_number="B-002",
            target_fill_units=10000,
            **kwargs,
        ),
        PROGRAM_MANAGER,
    )


# ---------------------------------------------------------------------------
# Design instance:
#   suite_half_open_window_plus_directional_changeover_buffer_strict_boundary
# ---------------------------------------------------------------------------
def _one_booked_suite(api) -> Json:
    """FS-1 carrying a single 08:00-16:00 batch and a roomy unit budget."""
    program = fixtures.build_program(
        api, stage=fixtures.STAGE_SCHEDULED, reserved_unit_budget=50000
    )
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540
    return program


def test_suite_booking_one_minute_inside_the_changeover_buffer_is_refused(api):
    """A same-molecule follow-on starting at 16:59 collides through the buffer.

    PRD 3.5: "The new batch is rejected when there exists a live batch in the same suite such that the new batch's `planned_start` falls strictly earlier than that batch's `planned_end` advanced by the applicable buffer, *and* that batch's `planned_start` falls strictly earlier than the new batch's `planned_end` advanced by the applicable buffer."

    Design: Difficulty/resource_temporal_overlap/suite_half_open_window_plus_directional_changeover_buffer_strict_boundary
    """
    program = _one_booked_suite(api)

    response = _book(
        api,
        program,
        program["suite_id"],
        program["lead_operator_qualification_id"],
        planned_start="2026-09-10T16:59:00Z",
        planned_end="2026-09-11T00:00:00Z",
    )
    error = validate_error(response, ApiErrorId.SUITE_CHANGEOVER_CONFLICT, 409)
    assert error["error_id"] != ApiErrorId.OPERATOR_DOUBLE_BOOKED

    rows, _meta = validate_paginated(
        api.list_batch_orders(PROGRAM_MANAGER, {"suite_id": program["suite_id"]})
    )
    assert len(rows) == 1
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540


def test_suite_booking_exactly_at_the_buffer_boundary_is_accepted(api):
    """Starting at 17:00 sharp is not strictly earlier, so the booking stands.

    PRD 3.5: "Both comparisons are strict, so a new batch that starts at exactly the instant a previous batch's `planned_end` plus buffer falls is accepted."

    Design: Difficulty/resource_temporal_overlap/suite_half_open_window_plus_directional_changeover_buffer_strict_boundary
    """
    program = _one_booked_suite(api)

    batch = validate_success(
        _book(
            api,
            program,
            program["suite_id"],
            program["lead_operator_qualification_id"],
            planned_start="2026-09-10T17:00:00Z",
            planned_end="2026-09-11T00:00:00Z",
        ),
        201,
    )
    assert batch["changeover_minutes_applied"] == 60
    assert batch["component_demand_units"] == constants.WORKED_COMPONENT_DEMAND_UNITS

    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 1020
    project = fixtures.read_project(api, program["project_id"])
    assert project["committed_demand_units"] == 43120

    rows, _meta = validate_paginated(
        api.list_batch_orders(PROGRAM_MANAGER, {"suite_id": program["suite_id"]})
    )
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Design instance:
#   lead_operator_closed_interval_touching_endpoints_conflict_across_suites
# ---------------------------------------------------------------------------
def _two_suites_sharing_one_lead_operator(api) -> Json:
    """OP-A leads a batch in FS-1 and holds a separate qualification in FS-2."""
    program = _one_booked_suite(api)
    second_suite = fixtures.create_suite(
        api,
        suite_code="FS-2",
        grade="B",
        changeover_minutes_same_product=60,
        changeover_minutes_product_change=240,
        max_committed_minutes=20000,
    )
    _media_fill, qualifications = fixtures.qualify_suite(
        api,
        second_suite["id"],
        operators=("OP-A", "OP-C"),
        scheduled_run_date="2026-09-03T08:00:00Z",
    )
    program["second_suite_id"] = second_suite["id"]
    program["second_qualification_id"] = qualifications[0]["id"]
    return program


def test_lead_operator_windows_that_touch_at_an_endpoint_collide_across_suites(api):
    """A second fill starting exactly when the first ends double-books the lead.

    PRD 3.5: "Both comparisons are non-strict, so windows that merely touch at an endpoint do collide — the exact opposite adjacency treatment from the suite rule above."

    Design: Difficulty/resource_temporal_overlap/lead_operator_closed_interval_touching_endpoints_conflict_across_suites
    """
    program = _two_suites_sharing_one_lead_operator(api)

    response = _book(
        api,
        program,
        program["second_suite_id"],
        program["second_qualification_id"],
        planned_start="2026-09-10T16:00:00Z",
        planned_end="2026-09-11T00:00:00Z",
    )
    error = validate_error(response, ApiErrorId.OPERATOR_DOUBLE_BOOKED, 409)
    assert error["error_id"] != ApiErrorId.SUITE_CHANGEOVER_CONFLICT

    second_suite = fixtures.read_suite(api, program["second_suite_id"])
    assert second_suite["committed_minutes"] == 0


def test_lead_operator_conflict_clears_one_minute_later_and_books_the_other_suite(api):
    """One minute of separation is enough, and the buffer is the initial allowance.

    PRD 3.5: "The operator resource is resolved by taking the `operator_name` of the qualification named by `lead_operator_qualification_id`, and grouping live batches by that name."

    Design: Difficulty/resource_temporal_overlap/lead_operator_closed_interval_touching_endpoints_conflict_across_suites
    """
    program = _two_suites_sharing_one_lead_operator(api)

    batch = validate_success(
        _book(
            api,
            program,
            program["second_suite_id"],
            program["second_qualification_id"],
            planned_start="2026-09-10T16:01:00Z",
            planned_end="2026-09-11T00:00:00Z",
        ),
        201,
    )
    assert batch["changeover_minutes_applied"] == constants.INITIAL_SETUP_MINUTES

    assert fixtures.read_suite(api, program["second_suite_id"])["committed_minutes"] == 539
    assert fixtures.read_suite(api, program["suite_id"])["committed_minutes"] == 540
    project = fixtures.read_project(api, program["project_id"])
    assert project["committed_demand_units"] == 43120

    rows, _meta = validate_paginated(
        api.list_batch_orders(
            PROGRAM_MANAGER,
            {"lead_operator_qualification_id": program["second_qualification_id"]},
        )
    )
    assert len(rows) == 1
