"""Two scheduled resources with deliberately opposite interval semantics.

A deposition chamber is shared and half-open: several runs may overlap while the
instantaneous loaded area fits inside the budget, and two windows that merely
touch share no instant at all. A grinding cell is exclusive and closed: touching
endpoints do collide, and beyond the collision the cell also demands a
changeover gap.
"""

from test_helpers import ApiErrorId
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_coating_run, assert_grinding_run
from test_helpers.fixtures import COAT, PLAN
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── The deposition chamber: shared, half-open, area budgeted ────────────────

def _chamber_with_a_loaded_run(api) -> dict:
    """A recipe plus one SCHEDULED CH1 run carrying 2500.00 cm2 over [06:00, 12:00)."""
    recipe = fx.coating_recipe(api)
    run = validate_success(
        api.create_coating_run(
            f.coating_run_payload(
                recipe["id"],
                window_start="2026-08-10T06:00:00Z",
                window_end="2026-08-10T12:00:00Z",
                loaded_area_cm2=2500.00,
            ),
            COAT,
        ),
        201,
    )
    return {"recipe": recipe, "run": run}


def test_an_overlapping_load_that_breaches_the_chamber_budget_is_refused(api):
    """2500.00 already booked plus a requested 1600.00 is 4100.00 over two shared hours.

    PRD §2.11: "27. **Chamber area capacity.** →
    `ERR_CHAMBER_CAPACITY_EXCEEDED`, on coating-run creation."

    PRD §3.3: "For the requested chamber, at every instant covered by the new
    half-open interval, the sum of `loaded_area_cm2` over all `SCHEDULED` and
    `COMPLETED` runs whose own half-open windows cover that instant, plus the
    requested `loaded_area_cm2`, must not exceed 4000.00; otherwise the booking
    is rejected with `ERR_CHAMBER_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/coating_chamber_aggregate_area_within_overlap
    """
    state = _chamber_with_a_loaded_run(api)

    response = api.create_coating_run(
        f.coating_run_payload(
            state["recipe"]["id"],
            window_start="2026-08-10T10:00:00Z",
            window_end="2026-08-10T16:00:00Z",
            loaded_area_cm2=1600.00,
        ),
        COAT,
    )

    validate_error(response, ApiErrorId.ERR_CHAMBER_CAPACITY_EXCEEDED, 409)
    existing = validate_success(api.get_coating_run(state["run"]["id"], COAT))
    assert existing["loaded_area_cm2"] == 2500.00, (
        f"the rejected booking must not restate the standing run, got {existing['loaded_area_cm2']}"
    )
    rows, _meta = validate_paginated(api.list_coating_runs(COAT))
    assert len(rows) == 1, (
        f"the rejected booking must not have created a row, got {len(rows)} runs"
    )


def test_an_overlapping_load_that_lands_exactly_on_the_chamber_budget_is_accepted(api):
    """2500.00 plus 1500.00 is exactly 4000.00 during the shared hours, so it books.

    PRD §3.3: "Unlike a grinding cell, a chamber is shared: several runs may
    occupy it at once, subject to an area budget of 4000.00 square centimetres."

    PRD §3.3: "The run opens at `status` `SCHEDULED` and captures
    `pinned_recipe_revision` from the recipe's current `revision`, which is what
    later ties the run's measurements to a specific layer stack rather than to
    whatever the recipe has since become."

    Design: Difficulty/resource_temporal_overlap/coating_chamber_aggregate_area_within_overlap
    """
    state = _chamber_with_a_loaded_run(api)

    response = api.create_coating_run(
        f.coating_run_payload(
            state["recipe"]["id"],
            window_start="2026-08-10T10:00:00Z",
            window_end="2026-08-10T16:00:00Z",
            loaded_area_cm2=1500.00,
        ),
        COAT,
    )

    run = validate_success(response, 201)
    assert_coating_run(run)
    assert run["status"] == "SCHEDULED", (
        "the aggregate sits exactly on the 4000.00 budget, which is accepted, "
        f"got {run['status']}"
    )
    assert run["loaded_area_cm2"] == 1500.00, (
        f"the requested load is recorded as asked, got {run['loaded_area_cm2']}"
    )


def test_two_back_to_back_chamber_windows_may_both_carry_a_full_load(api):
    """A run starting the instant its neighbour ends shares no instant, so 4000.00 books.

    PRD §3.3: "Chamber windows are **half-open**: the interval runs from
    `window_start` inclusive to `window_end` exclusive."

    PRD §3.3: "Because the intervals are half-open, two touching windows — where
    the earlier run's `window_end` equals the new run's `window_start` — share no
    instant at all, and both may legitimately be loaded to the full 4000.00."

    Design: Difficulty/resource_temporal_overlap/coating_chamber_aggregate_area_within_overlap
    """
    state = _chamber_with_a_loaded_run(api)
    validate_success(
        api.create_coating_run(
            f.coating_run_payload(
                state["recipe"]["id"],
                window_start="2026-08-10T10:00:00Z",
                window_end="2026-08-10T16:00:00Z",
                loaded_area_cm2=1500.00,
            ),
            COAT,
        ),
        201,
    )

    response = api.create_coating_run(
        f.coating_run_payload(
            state["recipe"]["id"],
            window_start="2026-08-10T16:00:00Z",
            window_end="2026-08-10T22:00:00Z",
            loaded_area_cm2=4000.00,
        ),
        COAT,
    )

    run = validate_success(response, 201)
    assert run["status"] == "SCHEDULED", (
        "the window opens at the instant its neighbour's window closes, so the "
        f"chamber is free for a full load, got {run['status']}"
    )
    rows, _meta = validate_paginated(api.list_coating_runs(COAT))
    assert len(rows) == 3, (
        f"all three bookings stand in CH1, got {len(rows)} runs"
    )


# ─── The grinding cell: exclusive, closed, with a changeover gap ─────────────

def _cell_with_a_standing_run(api) -> dict:
    """A CELL_A run over the closed window [06:00, 10:00] on a wheel with ample life."""
    return fx.scheduled_grinding_run(
        api, wheel_overrides={"initial_life_units": 100000}, planned_units=10
    )


def test_a_cell_booking_that_starts_when_its_neighbour_ends_collides(api):
    """Closed intervals share the 10:00 instant, so the handover is a double booking.

    PRD §2.11: "28. **Cell exclusive occupancy.** → `ERR_CELL_DOUBLE_BOOKED`, on
    grinding-run creation."

    PRD §3.4: "If the requested closed window intersects the closed window of
    any `SCHEDULED` or `COMPLETED` run already in that cell, the booking is
    rejected with `ERR_CELL_DOUBLE_BOOKED` — and because both intervals are
    closed, touching endpoints *do* collide: a new run starting at the exact
    instant an existing run ends is a conflict, not a handover."

    Design: Difficulty/resource_temporal_overlap/grinding_cell_exclusive_with_setup_buffer
    """
    state = _cell_with_a_standing_run(api)

    response = api.create_grinding_run(
        f.grinding_run_payload(
            state["wheel"]["id"],
            state["product"]["id"],
            cell_id="CELL_A",
            window_start="2026-08-12T10:00:00Z",
            window_end="2026-08-12T12:00:00Z",
            planned_units=5,
        ),
        PLAN,
    )

    validate_error(response, ApiErrorId.ERR_CELL_DOUBLE_BOOKED, 409)
    rows, _meta = validate_paginated(api.list_grinding_runs(PLAN))
    assert len(rows) == 1, (
        f"the colliding booking must not have created a row, got {len(rows)} runs"
    )


def test_a_forty_four_minute_changeover_gap_is_refused_and_forty_five_is_accepted(api):
    """The buffer is inclusive at 45 minutes and one minute less is a conflict.

    PRD §3.4: "Even where two runs do not overlap, the cell needs time for setup:
    if the gap on either side to the nearest neighbouring run in the same cell is
    smaller than 45 minutes, the booking is rejected with
    `ERR_CELL_BUFFER_CONFLICT`. A gap of exactly 45 minutes is accepted."

    PRD §3.4: "The run opens at `status` `SCHEDULED` with `consumed_life_units`
    at 0 and `tolerance_class` null."

    Design: Difficulty/resource_temporal_overlap/grinding_cell_exclusive_with_setup_buffer
    """
    state = _cell_with_a_standing_run(api)

    refused = api.create_grinding_run(
        f.grinding_run_payload(
            state["wheel"]["id"],
            state["product"]["id"],
            cell_id="CELL_A",
            window_start="2026-08-12T10:44:00Z",
            window_end="2026-08-12T12:00:00Z",
            planned_units=5,
        ),
        PLAN,
    )
    accepted = api.create_grinding_run(
        f.grinding_run_payload(
            state["wheel"]["id"],
            state["product"]["id"],
            cell_id="CELL_A",
            window_start="2026-08-12T10:45:00Z",
            window_end="2026-08-12T12:00:00Z",
            planned_units=5,
        ),
        PLAN,
    )

    validate_error(refused, ApiErrorId.ERR_CELL_BUFFER_CONFLICT, 409)
    run = validate_success(accepted, 201)
    assert_grinding_run(run)
    assert run["status"] == "SCHEDULED", (
        f"a gap of exactly 45 minutes is accepted, got {run['status']}"
    )
    assert run["consumed_life_units"] == 0, (
        f"scheduling charges no abrasive life, got {run['consumed_life_units']}"
    )
    wheel = validate_success(api.get_grinding_wheel(state["wheel"]["id"], PLAN))
    assert wheel["consumed_life_units"] == 0, (
        f"the wheel is untouched until a run is closed out, got {wheel['consumed_life_units']}"
    )


def test_the_second_cell_is_a_separate_resource_and_takes_the_identical_window(api):
    """CELL_B accepts the very window CELL_A is occupied for.

    PRD §3.4: "Booking a grinding run names the `wheel_id` to be mounted, the
    `product_id` being ground, the `cell_id` occupied — either `CELL_A` or
    `CELL_B` — the occupation window as `window_start` and `window_end`, and
    `planned_units`, the number of tools planned, which must be at least 1."

    PRD §3.4: "If the requested closed window intersects the closed window of any
    `SCHEDULED` or `COMPLETED` run already in that cell, the booking is rejected
    with `ERR_CELL_DOUBLE_BOOKED`"

    Design: Difficulty/resource_temporal_overlap/grinding_cell_exclusive_with_setup_buffer
    """
    state = _cell_with_a_standing_run(api)

    response = api.create_grinding_run(
        f.grinding_run_payload(
            state["wheel"]["id"],
            state["product"]["id"],
            cell_id="CELL_B",
            window_start="2026-08-12T06:00:00Z",
            window_end="2026-08-12T10:00:00Z",
            planned_units=5,
        ),
        PLAN,
    )

    run = validate_success(response, 201)
    assert run["cell_id"] == "CELL_B", (
        f"the booking lands in the requested cell, got {run['cell_id']}"
    )
    assert run["status"] == "SCHEDULED", (
        "exclusivity and the setup buffer are per cell, so the identical window "
        f"is free in CELL_B, got {run['status']}"
    )
