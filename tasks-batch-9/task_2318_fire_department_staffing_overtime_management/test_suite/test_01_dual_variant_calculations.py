"""Computed reads that deliberately disagree: the two forecast methods, and the
two hour bases an FLSA work period can be priced on.
"""

from test_helpers import STAFFING_OFFICER, fixtures as fx
from test_helpers import validate_success


# ---------------------------------------------------------------------------
# Forecast divergence
# ---------------------------------------------------------------------------
def _station_with_realised_spend_and_one_open_paramedic_seat(api):
    """One completed paramedic tour of realised spend plus one still-open seat."""
    station = fx.create_station(
        api,
        name="Station 41",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-41",
        minimum_crew_size=1,
        required_certifications=["PARAMEDIC"],
        closure_priority=10,
    )
    medic_a = fx.create_firefighter(
        api,
        station["id"],
        full_name="A Abbott",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=["PARAMEDIC"],
        hourly_rate_cents=4237,
    )
    fx.create_firefighter(
        api,
        station["id"],
        full_name="B Baptiste",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=["PARAMEDIC"],
        hourly_rate_cents=3916,
    )
    fx.create_firefighter(
        api,
        station["id"],
        full_name="C Cortez",
        platoon="C",
        seniority_rank=3,
        kelly_day_cycle_position=3,
        certifications=["PARAMEDIC"],
        hourly_rate_cents=4602,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")

    worked_shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    fx.staffed_shift_via_overtime(
        api, station["id"], worked_shift["id"], medic_a["id"], "VOLUNTARY", 24
    )

    future_shift = fx.published_shift(api, station["id"], "2026-08-23", "C")

    fx.set_clock(api, "2026-08-13T00:00:00Z")
    fx.complete_shift(api, worked_shift["id"])

    return {
        "station": station,
        "engine": engine,
        "worked_shift": worked_shift,
        "future_shift": future_shift,
    }


class TestOvertimeForecastVariantDivergence:
    """The bottom-up and run-rate methods price the same station differently."""

    def test_vacancy_driven_method_prices_the_open_seat_bottom_up(self, api):
        """The vacancy-driven forecast is built from open seats and injury leave.

        PRD 3.9: "For each one, uplift `shift_base_cents` by the certification
        premium keyed to that vacancy's `required_certification` — nothing for
        `NONE`, twelve percent for `PARAMEDIC`, eight percent for `HAZMAT_TECH`,
        eight percent for `TECHNICAL_RESCUE` — and round half up **per
        vacancy**; the sum of those rounded amounts is `vacancy_driver_cents`."

        Design: Difficulty/dual_variant_calc/forecast_variant_divergence_on_station_fiscal_projection
        """
        world = _station_with_realised_spend_and_one_open_paramedic_seat(api)

        response = api.get_overtime_forecast(
            world["station"]["id"], STAFFING_OFFICER, method="VACANCY_DRIVEN"
        )
        forecast = validate_success(response, 200)

        assert forecast["method"] == "VACANCY_DRIVEN"
        assert forecast["avg_rate_cents"] == 4252
        assert forecast["shift_base_cents"] == 153072
        assert forecast["horizon_vacancy_count"] == 1
        assert forecast["vacancy_driver_cents"] == 171441
        assert forecast["injury_headcount"] == 0
        assert forecast["injury_driver_cents"] == 0
        assert forecast["forecast_cents"] == 171441
        assert forecast["projected_period_total_cents"] == 342261
        assert forecast["variance_cents"] == 8657739
        assert forecast["forecast_posture"] == "WITHIN"

    def test_run_rate_method_extrapolates_realised_spend_and_diverges(self, api):
        """The run-rate forecast ignores the open seat and extrapolates spend.

        PRD 3.9: "`daily_run_rate_cents` is `ot_actual_cents` divided by
        `elapsed_days`, rounded half up. `forecast_cents` is
        `daily_run_rate_cents` multiplied by `remaining_days`."

        Design: Difficulty/dual_variant_calc/forecast_variant_divergence_on_station_fiscal_projection
        """
        world = _station_with_realised_spend_and_one_open_paramedic_seat(api)

        run_rate = validate_success(
            api.get_overtime_forecast(
                world["station"]["id"], STAFFING_OFFICER, method="RUN_RATE"
            ),
            200,
        )
        vacancy_driven = validate_success(
            api.get_overtime_forecast(
                world["station"]["id"], STAFFING_OFFICER, method="VACANCY_DRIVEN"
            ),
            200,
        )

        assert run_rate["method"] == "RUN_RATE"
        assert run_rate["remaining_days"] == 48
        assert run_rate["daily_run_rate_cents"] == 13140
        assert run_rate["forecast_cents"] == 630720
        assert run_rate["projected_period_total_cents"] == 801540
        assert run_rate["variance_cents"] == 8198460
        assert run_rate["forecast_posture"] == "WITHIN"

        # Fields belonging to the method that was not selected read zero.
        assert run_rate["horizon_vacancy_count"] == 0
        assert run_rate["vacancy_driver_cents"] == 0
        assert run_rate["injury_headcount"] == 0
        assert run_rate["injury_driver_cents"] == 0
        assert vacancy_driven["daily_run_rate_cents"] == 0
        assert vacancy_driven["remaining_days"] == 0

        assert (
            run_rate["forecast_cents"] - vacancy_driven["forecast_cents"] == 459279
        ), "the two methods must disagree on the same station"


# ---------------------------------------------------------------------------
# FLSA scheduled basis versus worked basis
# ---------------------------------------------------------------------------
def _member_with_two_tours_and_both_hour_bases_adjusted(api):
    """A member holding two 24-hour tours plus scheduled and worked adjustments."""
    station = fx.create_station(
        api,
        name="Station 42",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-42",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="D Duarte",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4237,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="E Elden",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )

    first_shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    first_seat = fx.seat_member(
        api, first_shift["id"], member["id"], engine["id"], officer["id"]
    )
    second_shift = fx.published_shift(api, station["id"], "2026-08-27", "C")
    second_seat = fx.seat_member(
        api, second_shift["id"], member["id"], engine["id"], officer["id"]
    )

    period = fx.work_period_of(api, member["id"])
    fx.adjust_hours(api, period["id"], 204, "SCHEDULED")
    fx.adjust_hours(api, period["id"], 192, "WORKED")

    fx.set_clock(api, "2026-08-28T00:00:00Z")
    fx.complete_shift(api, first_shift["id"])

    return {
        "station": station,
        "member": member,
        "period": fx.read_work_period(api, period["id"]),
        "first_shift": first_shift,
        "second_shift": second_shift,
        "first_seat": first_seat,
        "second_seat": second_seat,
    }


class TestWorkPeriodScheduledVersusWorkedBasis:
    """Closing the period swaps the premium from the projection to the payable."""

    def test_closing_the_period_reprices_the_premium_on_the_worked_basis(self, api):
        """An OPEN period prices the projection; a CLOSED period prices the payable.

        PRD 3.9: "An `OPEN` period prices on the **scheduled basis** — an
        upper-bound, forward-looking projection that includes seats which are
        only scheduled — and a `CLOSED` period prices on the **worked basis**,
        the payable figure, from which relieved, cancelled and leave-covered
        seats have dropped out, so the payable figure is at or below the
        projection and the delta is written to `flsa_premium_cents` at close."

        Design: Difficulty/dual_variant_calc/flsa_period_priced_on_scheduled_versus_worked_basis
        """
        world = _member_with_two_tours_and_both_hour_bases_adjusted(api)

        before = world["period"]
        assert before["status"] == "OPEN"
        assert before["adjusted_scheduled_hours"] == 204
        assert before["projected_flsa_overtime_hours"] == 48
        assert before["flsa_premium_cents"] == 101688

        fx.complete_shift(api, world["second_shift"]["id"])

        after = fx.read_work_period(api, before["id"])
        assert after["status"] == "CLOSED"
        assert after["adjusted_scheduled_hours"] == 204
        assert after["projected_flsa_overtime_hours"] == 48
        assert after["adjusted_worked_hours"] == 192
        assert after["final_flsa_overtime_hours"] == 36
        assert after["flsa_premium_cents"] == 76266
        assert before["flsa_premium_cents"] - after["flsa_premium_cents"] == 25422

    def test_close_out_stamps_worked_hours_and_spawns_the_successor_period(self, api):
        """Close-out stamps actual hours and opens the next 27-day window.

        PRD 3.9: "Then every work period of the involved members whose
        `period_end_date` falls on or before the shift date moves `OPEN →
        CLOSED`, has its `flsa_premium_cents` re-priced on the worked basis
        instead of the scheduled basis, and spawns a successor period in `OPEN`
        status beginning the day after the closed period ended and running its
        own twenty-seven days."

        Design: Difficulty/dual_variant_calc/flsa_period_priced_on_scheduled_versus_worked_basis
        """
        world = _member_with_two_tours_and_both_hour_bases_adjusted(api)

        fx.complete_shift(api, world["second_shift"]["id"])

        second_seat = fx.read_assignment(api, world["second_seat"]["id"])
        assert second_seat["status"] == "WORKED"
        assert second_seat["actual_hours"] == 24

        periods = fx.work_periods_of(api, world["member"]["id"])
        closed = [p for p in periods if p["status"] == "CLOSED"]
        successors = [p for p in periods if p["status"] == "OPEN"]
        assert len(closed) == 1, f"expected exactly one closed period, got {periods}"
        assert len(successors) == 1, f"expected exactly one successor, got {periods}"

        successor = successors[0]
        assert successor["period_start_date"] == "2026-08-28"
        assert successor["period_end_date"] == "2026-09-23"
        assert successor["flsa_threshold_hours"] == 204
        assert successor["scheduled_hours"] == 0
        assert successor["worked_hours"] == 0
        assert successor["flsa_premium_cents"] == 0
