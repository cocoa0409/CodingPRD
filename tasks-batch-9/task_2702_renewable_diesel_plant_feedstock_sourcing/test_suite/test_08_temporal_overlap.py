"""Three interval families on one unit, each with its own separation rule.

Turnaround windows demand 72 clear hours on both sides, campaign windows demand
only non-overlap of half-open intervals, and hydrogen nominations are closed on
both ends so sharing a single endpoint really does stack the load on that day.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_HYDROGEN_CAPACITY_EXCEEDED,
    ERR_TURNAROUND_BUFFER_VIOLATION,
    ERR_UNIT_WINDOW_CONFLICT,
)
from test_helpers.assertions import assert_one_decimal, assert_timestamp_equals
from test_helpers.test_users import OPERATOR_HEADERS, TRADER_HEADERS
from test_helpers.types import (
    NOMINATION_CONFIRMED,
    RUN_PLANNED,
    SCOPE_INSPECTION,
    WINDOW_PLANNED,
)

WINDOW_A_START = "2026-09-10T00:00:00Z"
WINDOW_A_END = "2026-09-12T00:00:00Z"


def _unit_with_inspection_window(api):
    """A commissioned unit carrying an APPROVED INSPECTION window over [09-10, 09-12)."""
    plant = fx.commissioned_unit(api)
    fx.make_approved_window(
        api,
        plant["unit"]["id"],
        scope=SCOPE_INSPECTION,
        start_at=WINDOW_A_START,
        end_at=WINDOW_A_END,
    )
    return plant["unit"]["id"]


def test_turnaround_window_touching_the_previous_one_has_no_clearance_at_all(api):
    """PRD §3.3: "Before it is accepted, the proposed interval is tested for adjacency against
    every other window on the same unit that is neither `CANCELLED` nor `COMPLETED`: there
    must be at least 72 hours — three full days — of clear time on **both** sides of the
    proposed interval."
    PRD §3.3: "A proposal whose `start_at` falls exactly on an existing window's `end_at` has
    zero hours of clearance and is refused with `ERR_TURNAROUND_BUFFER_VIOLATION`, as is
    anything else landing inside the buffer on either side."

    Design: Difficulty/resource_temporal_overlap/turnaround_windows_need_seventy_two_clear_hours_touching_is_not_enough
    """
    unit_id = _unit_with_inspection_window(api)

    validate_error(
        api.create_turnaround_window(
            unit_id,
            f.turnaround_window_payload(
                scope=SCOPE_INSPECTION,
                start_at="2026-09-12T00:00:00Z",
                end_at="2026-09-14T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ERR_TURNAROUND_BUFFER_VIOLATION,
    )

    validate_error(
        api.create_turnaround_window(
            unit_id,
            f.turnaround_window_payload(
                scope=SCOPE_INSPECTION,
                start_at="2026-09-14T00:00:00Z",
                end_at="2026-09-16T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ERR_TURNAROUND_BUFFER_VIOLATION,
    )


def test_exactly_seventy_two_clear_hours_admits_the_next_turnaround_window(api):
    """PRD §3.3: "Before it is accepted, the proposed interval is tested for adjacency against
    every other window on the same unit that is neither `CANCELLED` nor `COMPLETED`: there
    must be at least 72 hours — three full days — of clear time on **both** sides of the
    proposed interval."
    PRD §3.3: "The window records the unit it takes down as its `unit_id` and is created at
    status `PLANNED`."

    Design: Difficulty/resource_temporal_overlap/turnaround_windows_need_seventy_two_clear_hours_touching_is_not_enough
    """
    unit_id = _unit_with_inspection_window(api)

    window_c = validate_success(
        api.create_turnaround_window(
            unit_id,
            f.turnaround_window_payload(
                scope=SCOPE_INSPECTION,
                start_at="2026-09-15T00:00:00Z",
                end_at="2026-09-17T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert window_c["status"] == WINDOW_PLANNED, f"got {window_c['status']}"
    assert_timestamp_equals(window_c["start_at"], "2026-09-15T00:00:00Z", "start_at")

    windows = get_success_data(api.list_turnaround_windows(unit_id, OPERATOR_HEADERS))
    assert len(windows) == 3, f"expected the bootstrap window plus A and C, got {len(windows)}"


def _run_and_contract_with_first_nomination(api):
    """A PLANNED eight-day campaign holding one 3000.0 kg/day nomination over [09-01, 09-05]."""
    plant = fx.commissioned_unit(api)
    run = fx.make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-09T00:00:00Z",
    )
    contract = fx.make_contract(api)
    fx.make_nomination(
        api,
        contract["id"],
        run["id"],
        start_at="2026-09-01T00:00:00Z",
        end_at="2026-09-05T00:00:00Z",
        kg_per_day=3000.0,
    )
    return run, contract


def test_nominations_sharing_their_inclusive_endpoint_overload_that_single_day(api):
    """PRD §3.4: "For **every** calendar date the proposal touches, the already-committed
    figure for that date plus the proposal's own `kg_per_day` must not exceed the contract's
    `daily_capacity_kg`. A single overloaded shared day is enough to refuse the whole
    nomination with `ERR_HYDROGEN_CAPACITY_EXCEEDED`. Because both nomination endpoints are
    inclusive, a nomination ending at midnight on the tenth still competes for capacity on
    the tenth against one starting at that same instant."

    Design: Difficulty/resource_temporal_overlap/hydrogen_nominations_collide_on_the_shared_inclusive_end_day
    """
    run, contract = _run_and_contract_with_first_nomination(api)

    validate_error(
        api.create_nomination(
            contract["id"],
            f.nomination_payload(
                run["id"],
                start_at="2026-09-05T00:00:00Z",
                end_at="2026-09-08T00:00:00Z",
                kg_per_day=2500.0,
            ),
            OPERATOR_HEADERS,
        ),
        ERR_HYDROGEN_CAPACITY_EXCEEDED,
    )

    refreshed = validate_success(api.get_hydrogen_contract(contract["id"], TRADER_HEADERS))
    assert_one_decimal(refreshed["peak_committed_kg_per_day"], 3000.0, "peak_committed_kg_per_day")


def test_shifting_the_second_nomination_one_day_clears_the_collision(api):
    """PRD §3.4: "The `peak_committed_kg_per_day` is the maximum of that daily figure taken
    over every calendar date from the contract's `window_start` through its `window_end`
    inclusive, rounded half up to 1 decimal place, and it is 0.0 when the contract holds no
    `CONFIRMED` nomination at all."
    PRD §3.4: "The stored row records the contract it draws on as `contract_id` and starts at
    status `CONFIRMED`."

    Design: Difficulty/resource_temporal_overlap/hydrogen_nominations_collide_on_the_shared_inclusive_end_day
    """
    run, contract = _run_and_contract_with_first_nomination(api)

    second = validate_success(
        api.create_nomination(
            contract["id"],
            f.nomination_payload(
                run["id"],
                start_at="2026-09-06T00:00:00Z",
                end_at="2026-09-08T00:00:00Z",
                kg_per_day=2500.0,
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert second["status"] == NOMINATION_CONFIRMED, f"got {second['status']}"
    assert_one_decimal(second["kg_per_day"], 2500.0, "kg_per_day")

    refreshed = validate_success(api.get_hydrogen_contract(contract["id"], TRADER_HEADERS))
    assert_one_decimal(
        refreshed["peak_committed_kg_per_day"], 3000.0, "peak_committed_kg_per_day"
    )

    bookings = get_success_data(api.list_contract_nominations(contract["id"], OPERATOR_HEADERS))
    assert len(bookings) == 2, f"expected two confirmed bookings, got {len(bookings)}"
    assert all(row["status"] == NOMINATION_CONFIRMED for row in bookings)


def _unit_with_first_run(api):
    """A commissioned unit carrying one PLANNED campaign over [2026-09-01, 2026-09-06)."""
    plant = fx.commissioned_unit(api)
    fx.make_run(
        api,
        plant["unit"]["id"],
        plant["charge"]["id"],
        window_start="2026-09-01T00:00:00Z",
        window_end="2026-09-06T00:00:00Z",
    )
    return plant


def test_campaign_starting_the_instant_the_previous_one_ends_is_accepted(api):
    """PRD §3.5: "Touching endpoints do not intersect — a campaign that ends at the exact
    instant another begins is fine, because unlike turnaround windows there is no buffer
    between campaigns — but a genuine overlap is refused with `ERR_UNIT_WINDOW_CONFLICT`."
    PRD §3.5: "A newly created campaign is `PLANNED`. Its `run_days` is the whole number of
    days between `window_start` and `window_end`."

    Design: Difficulty/resource_temporal_overlap/run_windows_may_touch_but_never_straddle_on_one_unit
    """
    plant = _unit_with_first_run(api)

    run2 = validate_success(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"],
                plant["charge"]["id"],
                window_start="2026-09-06T00:00:00Z",
                window_end="2026-09-11T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )

    assert run2["status"] == RUN_PLANNED, f"got {run2['status']}"
    assert run2["run_days"] == 5, f"got {run2['run_days']}"

    runs = get_success_data(
        api.list_processing_runs(OPERATOR_HEADERS, {"unit_id": plant["unit"]["id"]})
    )
    assert len(runs) == 2, f"expected two campaigns on the unit, got {len(runs)}"


def test_campaign_straddling_either_end_of_the_booked_window_is_refused(api):
    """PRD §3.5: "The interval must not collide on that unit: treated as a half-open interval,
    it must not intersect the interval of any other campaign on the same unit whose status is
    `PLANNED`, `HYDROGEN_SECURED` or `RUNNING`, nor any turnaround window on that unit whose
    status is `PLANNED`, `APPROVED` or `IN_PROGRESS`."
    PRD §3.5: "Touching endpoints do not intersect — a campaign that ends at the exact instant
    another begins is fine, because unlike turnaround windows there is no buffer between
    campaigns — but a genuine overlap is refused with `ERR_UNIT_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/run_windows_may_touch_but_never_straddle_on_one_unit
    """
    plant = _unit_with_first_run(api)

    validate_error(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"],
                plant["charge"]["id"],
                window_start="2026-09-05T00:00:00Z",
                window_end="2026-09-08T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ERR_UNIT_WINDOW_CONFLICT,
    )

    validate_error(
        api.create_processing_run(
            f.processing_run_payload(
                plant["unit"]["id"],
                plant["charge"]["id"],
                window_start="2026-08-30T00:00:00Z",
                window_end="2026-09-02T00:00:00Z",
            ),
            OPERATOR_HEADERS,
        ),
        ERR_UNIT_WINDOW_CONFLICT,
    )

    runs = get_success_data(
        api.list_processing_runs(OPERATOR_HEADERS, {"unit_id": plant["unit"]["id"]})
    )
    assert len(runs) == 1, f"only the original campaign should exist, got {len(runs)}"
