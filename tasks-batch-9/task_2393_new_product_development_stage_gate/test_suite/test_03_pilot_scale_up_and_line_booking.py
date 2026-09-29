"""Pilot plant scale-up: the yield floor and allergen-aware line exclusivity."""
import pytest

from test_helpers import (
    PILOT_YIELD_FLOOR_PCT,
    assert_formulation,
    assert_pilot_run,
    book_pilot_run,
    complete_pilot_run,
    create_formulation,
    intake_project,
    pilot_run_payload,
    read_formulation,
    read_project,
    register_pilot_line,
    set_clock,
    start_pilot_run,
    validate_error,
    validate_paginated,
    validate_success,
)

RUN_START = "2026-08-06T08:00:00Z"
RUN_END = "2026-08-06T16:00:00Z"


def _run_ready_project(name, line_code, cost=20000.00):
    """A project with one dedicated line and one SCHEDULED run of 10000 planned units."""
    line = register_pilot_line(line_code=line_code)
    project = intake_project(name=name)
    formulation = create_formulation(project["id"])
    run = book_pilot_run(
        formulation["id"], line["id"], planned_units=10000, committed_cost_usd=cost
    )
    return {"pilot_line": line, "project": project, "formulation": formulation, "run": run}


def test_pilot_yield_exactly_at_the_floor_clears_the_formulation(api, rnd_lead_headers):
    """8500 units out of 10000 is exactly 85.00 percent and passes scale-up.

    PRD: "The pilot yield floor is `85.00` percent. A yield at or above the floor drives the
    formulation to `PILOT_PASSED` — from `DRAFT → PILOT_PASSED` on a first success, or
    `PILOT_FAILED → PILOT_PASSED` when a later run redeems an earlier failure — and
    auto-approves the `PILOT_SCALE_UP_REPORT` checklist item."

    Design: Difficulty/boundary_precision_check/pilot_yield_at_floor_versus_one_hundredth_below
    """
    set_clock("2026-08-03T00:00:00Z")
    ctx = _run_ready_project("Yield Exact", "AKR-1")
    set_clock(RUN_START)
    start_pilot_run(ctx["run"]["id"])

    completed = validate_success(
        api.complete_pilot_run(ctx["run"]["id"], {"actual_units": 8500}, rnd_lead_headers)
    )

    assert_pilot_run(completed)
    assert completed["status"] == "COMPLETED"
    assert completed["yield_pct"] == pytest.approx(85.00, abs=0.01)
    assert completed["yield_pct"] >= PILOT_YIELD_FLOOR_PCT
    formulation = read_formulation(ctx["formulation"]["id"])
    assert_formulation(formulation)
    assert formulation["status"] == "PILOT_PASSED"
    assert formulation["best_pilot_yield_pct"] == pytest.approx(85.00, abs=0.01)


def test_pilot_yield_one_unit_below_the_floor_fails_the_formulation(api, rnd_lead_headers):
    """8499 units out of 10000 is 84.99 percent and the formulation fails scale-up.

    PRD: "A yield below the floor drives the formulation `DRAFT → PILOT_FAILED` and approves
    nothing."

    Design: Difficulty/boundary_precision_check/pilot_yield_at_floor_versus_one_hundredth_below
    """
    set_clock("2026-08-03T00:00:00Z")
    ctx = _run_ready_project("Yield Below", "AKR-2")
    set_clock(RUN_START)
    start_pilot_run(ctx["run"]["id"])

    completed = validate_success(
        api.complete_pilot_run(ctx["run"]["id"], {"actual_units": 8499}, rnd_lead_headers)
    )

    assert completed["status"] == "COMPLETED", "a short run still completes"
    assert completed["yield_pct"] == pytest.approx(84.99, abs=0.01)
    assert completed["yield_pct"] < PILOT_YIELD_FLOOR_PCT
    formulation = read_formulation(ctx["formulation"]["id"])
    assert formulation["status"] == "PILOT_FAILED"
    assert formulation["best_pilot_yield_pct"] == pytest.approx(84.99, abs=0.01)


def test_one_unit_of_ten_thousand_separates_a_passed_from_a_failed_formulation(api, rnd_lead_headers):
    """Two runs identical but for a single unit split at the inclusive floor.

    PRD: "Completing a `RUNNING` run takes `actual_units` (which must be at least 0) and moves
    it `RUNNING → COMPLETED`, computing `yield_pct` as `actual_units` divided by
    `planned_units`, multiplied by 100, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/pilot_yield_at_floor_versus_one_hundredth_below
    """
    set_clock("2026-08-03T00:00:00Z")
    exact = _run_ready_project("Yield Exact", "AKR-1")
    below = _run_ready_project("Yield Below", "AKR-2")
    set_clock(RUN_START)
    start_pilot_run(exact["run"]["id"])
    start_pilot_run(below["run"]["id"])

    passed_run = complete_pilot_run(exact["run"]["id"], 8500)
    failed_run = validate_success(
        api.complete_pilot_run(below["run"]["id"], {"actual_units": 8499}, rnd_lead_headers)
    )

    assert passed_run["yield_pct"] - failed_run["yield_pct"] == pytest.approx(0.01, abs=0.005)
    assert read_formulation(exact["formulation"]["id"])["status"] == "PILOT_PASSED"
    assert read_formulation(below["formulation"]["id"])["status"] == "PILOT_FAILED"
    for ctx in (exact, below):
        project = read_project(ctx["project"]["id"])
        assert project["development_budget_committed_usd"] == pytest.approx(20000.00, abs=0.01), (
            "a completed run keeps its commitment in the ledger"
        )


def test_a_run_inside_the_changeover_buffer_is_refused(api, rnd_lead_headers):
    """A dairy run starting one minute before the buffer expires collides with it.

    PRD: "Booking then compares the requested interval — half-open, running from
    `window_start` up to but not including `window_end` extended by
    `effective_buffer_minutes` — pairwise against the same buffer-extended interval of every
    `SCHEDULED` or `RUNNING` run already on that line, whatever project it belongs to."

    Design: Difficulty/resource_temporal_overlap/pilot_line_buffer_extended_half_open_overlap
    """
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(plant_name="Toledo Pilot", line_code="TOL-1",
                               changeover_buffer_minutes=240, allergen_regime="NONE",
                               hourly_cost_usd=850.00)
    beverage = intake_project(name="Buffer Probe BEVERAGE")
    beverage_formulation = create_formulation(beverage["id"])
    dairy = intake_project(name="Buffer Probe DAIRY", brand="DairyBest", category="DAIRY")
    dairy_formulation = create_formulation(
        dairy["id"], allergen_regime="DAIRY", target_shelf_life_days=120, unit_cost_usd=1.4000
    )
    incumbent = book_pilot_run(
        beverage_formulation["id"], line["id"], window_start=RUN_START, window_end=RUN_END,
        committed_cost_usd=20000.00,
    )
    assert incumbent["effective_buffer_minutes"] == 240, (
        "matching allergen regimes leave the line's base buffer unchanged"
    )

    response = api.create_pilot_run(
        dairy_formulation["id"],
        pilot_run_payload(line["id"], window_start="2026-08-06T19:59:00Z",
                          window_end="2026-08-06T23:00:00Z", planned_units=5000,
                          committed_cost_usd=10000.00),
        rnd_lead_headers,
    )

    validate_error(response, "ERR_PILOT_LINE_CONFLICT", 409)
    _, meta = validate_paginated(
        api.list_pilot_runs(rnd_lead_headers, params={"pilot_line_id": line["id"]})
    )
    assert meta["total_count"] == 1, "the refused booking was never stored"
    assert read_project(dairy["id"])["development_budget_committed_usd"] == pytest.approx(
        0.00, abs=0.01
    ), "a refused booking commits nothing"


def test_a_run_starting_when_the_buffer_expires_is_accepted_and_doubles_its_own_buffer(
    api, rnd_lead_headers
):
    """20:00 is the exclusive upper bound of the incumbent's extended interval.

    PRD: "Any overlap is rejected with `ERR_PILOT_LINE_CONFLICT` (409); a run starting exactly
    at the instant a previous run's buffer expires is not an overlap and is accepted."

    Design: Difficulty/resource_temporal_overlap/pilot_line_buffer_extended_half_open_overlap
    """
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(plant_name="Toledo Pilot", line_code="TOL-1",
                               changeover_buffer_minutes=240, allergen_regime="NONE",
                               hourly_cost_usd=850.00)
    beverage = intake_project(name="Buffer Probe BEVERAGE")
    book_pilot_run(
        create_formulation(beverage["id"])["id"], line["id"], window_start=RUN_START,
        window_end=RUN_END, committed_cost_usd=20000.00,
    )
    dairy = intake_project(name="Buffer Probe DAIRY", brand="DairyBest", category="DAIRY")
    dairy_formulation = create_formulation(
        dairy["id"], allergen_regime="DAIRY", target_shelf_life_days=120, unit_cost_usd=1.4000
    )

    accepted = validate_success(
        api.create_pilot_run(
            dairy_formulation["id"],
            pilot_run_payload(line["id"], window_start="2026-08-06T20:00:00Z",
                              window_end="2026-08-06T22:00:00Z", planned_units=5000,
                              committed_cost_usd=10000.00),
            rnd_lead_headers,
        ),
        201,
    )

    assert_pilot_run(accepted)
    assert accepted["status"] == "SCHEDULED"
    assert accepted["effective_buffer_minutes"] == 480, (
        "a DAIRY formulation on a NONE line doubles the 240 minute changeover"
    )
    assert read_project(dairy["id"])["development_budget_committed_usd"] == pytest.approx(
        10000.00, abs=0.01
    )


def test_the_doubled_buffer_holds_the_line_into_the_next_morning(api, rnd_lead_headers):
    """The accepted dairy run reserves the line until 06:00 the following day.

    PRD: "Each run derives `effective_buffer_minutes` from the line's base
    `changeover_buffer_minutes`: unchanged when the formulation's `allergen_regime` equals the
    line's `allergen_regime`, and **doubled** when the two differ, because switching a line
    between, say, a `NUT` regime and a `NONE` regime costs a full sanitation changeover."

    Design: Difficulty/resource_temporal_overlap/pilot_line_buffer_extended_half_open_overlap
    """
    set_clock("2026-08-03T00:00:00Z")
    line = register_pilot_line(plant_name="Toledo Pilot", line_code="TOL-1",
                               changeover_buffer_minutes=240, allergen_regime="NONE",
                               hourly_cost_usd=850.00)
    beverage = intake_project(name="Buffer Probe BEVERAGE")
    book_pilot_run(
        create_formulation(beverage["id"])["id"], line["id"], window_start=RUN_START,
        window_end=RUN_END, committed_cost_usd=20000.00,
    )
    dairy = intake_project(name="Buffer Probe DAIRY", brand="DairyBest", category="DAIRY")
    dairy_formulation = create_formulation(
        dairy["id"], allergen_regime="DAIRY", target_shelf_life_days=120, unit_cost_usd=1.4000
    )
    book_pilot_run(
        dairy_formulation["id"], line["id"], window_start="2026-08-06T20:00:00Z",
        window_end="2026-08-06T22:00:00Z", planned_units=5000, committed_cost_usd=10000.00,
    )

    response = api.create_pilot_run(
        dairy_formulation["id"],
        pilot_run_payload(line["id"], window_start="2026-08-07T05:59:00Z",
                          window_end="2026-08-07T09:00:00Z", planned_units=5000,
                          committed_cost_usd=10000.00),
        rnd_lead_headers,
    )

    validate_error(response, "ERR_PILOT_LINE_CONFLICT", 409)
    _, meta = validate_paginated(
        api.list_pilot_runs(rnd_lead_headers, params={"pilot_line_id": line["id"]})
    )
    assert meta["total_count"] == 2, "only the two accepted runs sit on the line"
    assert read_project(dairy["id"])["development_budget_committed_usd"] == pytest.approx(
        10000.00, abs=0.01
    ), "the second refusal left the ledger on the single accepted dairy run"
