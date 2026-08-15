"""Lay-curve projection, flock age transitions, and sampling auto-schedule."""
import pytest

from test_helpers import (
    ApiErrorId,
    get_flock,
    run_daily_ops,
    set_clock,
    setup_farm_house_flock,
    setup_laying_flock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    COMPLIANCE_OFFICER,
    FARM_MANAGER,
    api_client,
)


class TestLayCurvePiecewise:
    def test_lay_curve_piecewise_age_cycle_state_values(self, api):
        """PRD §3.2: "Read against a peak of 95.0, the curve produces 23.75 at
        week 18, 71.25 at week 20, a plateau of 95.00 from week 21 through week
        30, 93.58 at week 31, 52.25 at week 60 for a `FIRST`-cycle flock
        against 44.41 for a `SECOND`-cycle flock, 50.83 at week 61 for `FIRST`
        against 43.20 for `SECOND`, and the floor values of 38.00 (`FIRST`) and
        32.30 (`SECOND`) from week 70 onward."

        Design: Difficulty/combinatorial_formula/lay_curve_piecewise_age_cycle_state
        """
        ctx = setup_laying_flock(
            clock_iso="2027-03-01T00:00:00Z",
            flock_overrides={"initial_hen_count": 800, "pullet_cost_cents": 336000},
            house_overrides={"environment_type": "AVIARY"},
        )
        flock = ctx["flock"]
        assert flock["age_weeks"] == 60, (
            f"placement 2026-01-05 at clock 2027-03-01 must be age 60 weeks, "
            f"got {flock['age_weeks']}"
        )
        assert flock["status"] == "LAYING"
        assert flock["lay_cycle"] == "FIRST"
        assert flock["current_lay_rate_pct"] == pytest.approx(52.25), (
            f"FIRST-cycle week-60 rate must be 52.25, got "
            f"{flock['current_lay_rate_pct']}"
        )

    def test_lay_curve_piecewise_molt_rest_and_second_cycle(self, api):
        """PRD §3.2: "While a flock is `LAYING`, its `current_lay_rate_pct`
        projects the percentage of hens expected to lay each day; at any other
        status the rate reads exactly 0.00, and it is recomputed whenever
        `age_weeks`, `lay_cycle`, or `status` changes."
        PRD §3.2: "A flock in its `SECOND` lay cycle — one that has completed
        a molt — multiplies the resulting base by a post-molt factor of 0.85."

        Design: Difficulty/combinatorial_formula/lay_curve_piecewise_age_cycle_state
        """
        ctx = setup_laying_flock(
            clock_iso="2027-03-01T00:00:00Z",
            flock_overrides={"initial_hen_count": 800, "pullet_cost_cents": 336000},
            house_overrides={"environment_type": "AVIARY"},
        )
        flock_id = ctx["flock"]["id"]

        rested = validate_success(api.induce_molt(flock_id, FARM_MANAGER))
        assert rested["status"] == "MOLT_REST"
        assert rested["current_lay_rate_pct"] == pytest.approx(0.00), (
            "MOLT_REST must force the lay rate to 0.00"
        )

        set_clock("2027-03-15T00:00:00Z")
        resumed = validate_success(api.resume_lay(flock_id, FARM_MANAGER))
        assert resumed["status"] == "LAYING"
        assert resumed["lay_cycle"] == "SECOND"
        assert resumed["molt_count"] == 1
        flock = get_flock(flock_id)
        assert flock["age_weeks"] == 62
        assert flock["current_lay_rate_pct"] == pytest.approx(41.99), (
            f"SECOND-cycle week-62 rate must be 41.99 (95 x 0.52 x 0.85), "
            f"got {flock['current_lay_rate_pct']}"
        )
        assert flock["current_lay_rate_pct"] != pytest.approx(49.40), (
            "the FIRST-cycle value 49.40 must not survive the 0.85 factor"
        )


class TestFlockComputedFields:
    def test_flock_computed_age_and_lay_rate(self, api):
        """PRD §3.2: "`age_weeks` is computed as the number of whole weeks
        between `placement_date` and the current clock date — the day
        difference divided by seven and rounded down."
        PRD §3.2: "A flock placed already at or past 18 weeks of age walks
        both steps in a single ops run."
        PRD §3.2: "While a flock is `LAYING`, its `current_lay_rate_pct`
        projects the percentage of hens expected to lay each day; at any other
        status the rate reads exactly 0.00"

        Design: Corner/entities/flock_computed_age_and_lay_rate
        """
        ctx = setup_farm_house_flock(placement_date="2026-01-05")
        placed = get_flock(ctx["flock"]["id"])
        assert placed["status"] == "PLACED"
        assert placed["age_weeks"] == 29, (
            f"placement 2026-01-05 vs startup clock 2026-08-01 is 29 weeks, "
            f"got {placed['age_weeks']}"
        )
        assert placed["current_lay_rate_pct"] == pytest.approx(0.00), (
            "a PLACED flock must read 0.00"
        )

        run_daily_ops()
        laying = get_flock(ctx["flock"]["id"])
        assert laying["status"] == "LAYING", (
            "a 29-week-old flock must pass PLACED -> GROWING -> LAYING in one run"
        )
        assert laying["current_lay_rate_pct"] == pytest.approx(95.00), (
            f"peak plateau at week 29 must read 95.00, got "
            f"{laying['current_lay_rate_pct']}"
        )

    def test_production_day_on_growing_flock_rejected(self, api):
        """PRD §3.3: "The flock must be `LAYING`, else `ERR_FLOCK_NOT_LAYING`
        (HTTP 409)."
        PRD §3.2: "The daily ops run moves a `PLACED` flock to `GROWING` once
        `age_weeks` reaches at least 1, and a `GROWING` flock to `LAYING` once
        `age_weeks` reaches at least 18"

        Design: Corner/validations/production_day_on_growing_flock_rejected
        """
        ctx = setup_farm_house_flock(
            placement_date="2026-07-25",
            flock_overrides={"initial_hen_count": 500, "pullet_cost_cents": 210000},
        )
        run_daily_ops()
        flock = get_flock(ctx["flock"]["id"])
        assert flock["status"] == "GROWING"
        assert flock["age_weeks"] == 1

        resp = api.create_production_day(
            {
                "flock_id": ctx["flock"]["id"],
                "lay_date": "2026-08-01",
                "eggs_collected": 10,
                "rejected_eggs": 0,
                "feed_issued_kg": 0,
                "mortality_count": 0,
            },
            FARM_MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_FLOCK_NOT_LAYING)
        assert get_flock(ctx["flock"]["id"])["status"] == "GROWING"


class TestSamplingAutoSchedule:
    def test_ops_run_auto_schedules_environmental_window_test(self, api):
        """PRD §3.7: "The first window covers `age_weeks` from 40 through 45
        inclusive."
        PRD §3.7: "When the clock falls inside a window, and no environmental
        test for the flock already has a `collected_date` inside that window,
        and no `SCHEDULED` test exists for the flock, the run auto-creates an
        `ENVIRONMENTAL` test with a pinned `scheduled_date`: for the first
        window, `placement_date` plus 321 days — the last day on which
        `age_weeks` still reads 45"
        PRD §2.4: "The run answers with a summary object containing
        `lots_expired`, `contracts_expired`, `flocks_advanced`,
        `houses_advanced`, and `tests_auto_scheduled`."

        Design: Corner/calculations/ops_run_auto_schedules_environmental_window_test
        """
        ctx = setup_farm_house_flock(placement_date="2025-10-25")
        summary = run_daily_ops()
        assert summary["flocks_advanced"] >= 1
        assert summary["tests_auto_scheduled"] == 1, (
            f"one ENVIRONMENTAL test must be auto-scheduled, got "
            f"{summary['tests_auto_scheduled']}"
        )

        resp = api.list_salmonella_tests(
            COMPLIANCE_OFFICER, params={"flock_id": ctx["flock"]["id"]}
        )
        tests, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        test = tests[0]
        assert test["test_type"] == "ENVIRONMENTAL"
        assert test["status"] == "SCHEDULED"
        assert test["scheduled_date"][:10] == "2026-09-11", (
            f"pinned scheduled_date must be placement + 321 days (2026-09-11), "
            f"got {test['scheduled_date']!r}"
        )
