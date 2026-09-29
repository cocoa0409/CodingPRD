"""Exact boundaries: the 204-hour FLSA threshold, and the analytics reads on a
station with nothing open at all.
"""

from test_helpers import STAFFING_OFFICER, fixtures as fx
from test_helpers import validate_success


# ---------------------------------------------------------------------------
# The 204-hour threshold
# ---------------------------------------------------------------------------
def _member_one_tour_short_of_the_threshold(api):
    """A member holding a single 24-hour tour, ready to be walked to 204 hours."""
    station = fx.create_station(
        api,
        name="Station 52",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-52",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="Z Zambrano",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4237,
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    fx.seat_member(api, shift["id"], member["id"], engine["id"], member["id"])
    return {
        "station": station,
        "member": member,
        "shift": shift,
        "period": fx.work_period_of(api, member["id"]),
    }


class TestFlsaThresholdBoundary:
    """The threshold must be exceeded, not merely met."""

    def test_exactly_two_hundred_and_four_hours_yields_no_overtime(self, api):
        """A period at exactly 204 scheduled hours has zero projected overtime.

        PRD 3.9: "A period whose scheduled hours reach exactly 204 has zero
        projected overtime hours and a zero premium, because the threshold must
        be exceeded, not merely met."

        Design: Difficulty/boundary_precision_check/flsa_threshold_exactly_204_hours_yields_zero_overtime
        """
        world = _member_one_tour_short_of_the_threshold(api)

        at_threshold = validate_success(
            api.hour_adjustment(
                world["period"]["id"],
                {
                    "adjustment_hours": 180,
                    "adjustment_basis": "SCHEDULED",
                    "reason": "carry-in hours from the prior 7(k) period",
                },
                fx.PAYROLL_ANALYST,
            ),
            200,
        )

        assert at_threshold["adjusted_scheduled_hours"] == 180
        assert at_threshold["scheduled_hours"] == 204
        assert at_threshold["flsa_threshold_hours"] == 204
        assert at_threshold["projected_flsa_overtime_hours"] == 0
        assert at_threshold["flsa_premium_cents"] == 0
        assert at_threshold["status"] == "OPEN"

    def test_the_two_hundred_and_fifth_hour_prices_at_half_time_rounded_half_up(
        self, api
    ):
        """One hour past the threshold is priced at half the hourly rate.

        PRD 3.9: "`flsa_premium_cents` prices whichever of the two the period's
        `status` selects, at the **half-time** premium: multiply the selected
        hour figure by the member's `hourly_rate_cents`, halve it, and round half
        up to whole cents."

        Design: Difficulty/boundary_precision_check/flsa_threshold_exactly_204_hours_yields_zero_overtime
        """
        world = _member_one_tour_short_of_the_threshold(api)
        fx.adjust_hours(api, world["period"]["id"], 180, "SCHEDULED")

        past_threshold = validate_success(
            api.hour_adjustment(
                world["period"]["id"],
                {
                    "adjustment_hours": 1,
                    "adjustment_basis": "SCHEDULED",
                    "reason": "drill time posted after the fact",
                },
                fx.PAYROLL_ANALYST,
            ),
            200,
        )

        assert past_threshold["scheduled_hours"] == 205
        assert past_threshold["projected_flsa_overtime_hours"] == 1
        # 4237 halved is 2118.5, which rounds half up to 2119.
        assert past_threshold["flsa_premium_cents"] == 2119
        assert past_threshold["status"] == "OPEN"


# ---------------------------------------------------------------------------
# Analytics on an empty horizon
# ---------------------------------------------------------------------------
def _station_with_a_single_member_and_no_shifts(api):
    """A registered station whose calendar is completely empty."""
    station = fx.create_station(
        api,
        name="Station 53",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-53",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="A Ahlgren",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4001,
    )
    return {"station": station, "member": member}


class TestAnalyticsOnAnEmptyHorizon:
    """Both computed reads answer cleanly when nothing is open."""

    def test_forecast_reports_a_zero_horizon_without_dividing_by_anything(self, api):
        """With no vacancies and no injuries the bottom-up forecast is zero.

        PRD 3.9: "`forecast_cents` is `vacancy_driver_cents` plus
        `injury_driver_cents`."

        Design: Difficulty/boundary_precision_check/forecast_and_academy_signal_on_zero_vacancy_horizon
        """
        world = _station_with_a_single_member_and_no_shifts(api)

        forecast = validate_success(
            api.get_overtime_forecast(world["station"]["id"], STAFFING_OFFICER), 200
        )

        assert forecast["method"] == "VACANCY_DRIVEN"
        assert forecast["avg_rate_cents"] == 4001
        assert forecast["shift_base_cents"] == 144036
        assert forecast["horizon_vacancy_count"] == 0
        assert forecast["vacancy_driver_cents"] == 0
        assert forecast["injury_headcount"] == 0
        assert forecast["injury_driver_cents"] == 0
        assert forecast["forecast_cents"] == 0
        assert forecast["projected_period_total_cents"] == 0
        assert forecast["variance_cents"] == 9_000_000
        assert forecast["forecast_posture"] == "WITHIN"

    def test_academy_signal_recommends_nothing_when_no_seat_is_open(self, api):
        """A recommendation of zero recruits bands as NONE.

        PRD 3.9: "The `signal_tier` then bands the recommendation: a
        recommendation of zero recruits is `NONE`; anything from one through
        eight inclusive is `MONITOR`; anything from nine through twenty inclusive
        is `RECRUIT`; anything above twenty is `SURGE`."

        Design: Difficulty/boundary_precision_check/forecast_and_academy_signal_on_zero_vacancy_horizon
        """
        world = _station_with_a_single_member_and_no_shifts(api)

        signal = validate_success(
            api.get_academy_hiring_signal(world["station"]["id"], STAFFING_OFFICER), 200
        )

        assert signal["station_id"] == world["station"]["id"]
        assert signal["open_vacancy_seats"] == 0
        assert signal["injury_headcount"] == 0
        assert signal["raw_need"] == 0
        assert signal["recommended_recruit_count"] == 0
        assert signal["signal_tier"] == "NONE"
