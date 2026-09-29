"""Multi-factor money formulas: nested premiums with a mode minimum, and the
per-vacancy rounding of the bottom-up forecast.
"""

from test_helpers import STAFFING_OFFICER, fixtures as fx
from test_helpers import validate_success


# ---------------------------------------------------------------------------
# Offer pricing: certification premium, fatigue premium, mode minimum hours
# ---------------------------------------------------------------------------
def _hazmat_company_with_a_fatigued_technician(api):
    """A hazmat-capable member already holding the previous day's tour."""
    station = fx.create_station(
        api,
        name="Station 43",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-43",
        minimum_crew_size=2,
        required_certifications=["HAZMAT_TECH"],
        closure_priority=10,
    )
    technician = fx.create_firefighter(
        api,
        station["id"],
        full_name="F Farrow",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=["HAZMAT_TECH"],
        hourly_rate_cents=4237,
    )
    generalist = fx.create_firefighter(
        api,
        station["id"],
        full_name="G Gupta",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4237,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="H Hastings",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
    fx.create_hiring_roster(api, station["id"], "CALLBACK", "NONE")

    # The technician works the platoon C tour on 2026-08-11 ...
    previous_shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    fx.seat_member(
        api,
        previous_shift["id"],
        technician["id"],
        engine["id"],
        officer["id"],
        seat_certification="HAZMAT_TECH",
    )

    # ... and the platoon D tour on 2026-08-12 is the one being hired for.
    hiring_shift = fx.published_shift(api, station["id"], "2026-08-12", "D")

    hazmat_vacancy = fx.first_vacancy(
        api,
        duty_shift_id=hiring_shift["id"],
        status="OPEN",
        required_certification="HAZMAT_TECH",
    )
    plain_vacancy = fx.first_vacancy(
        api,
        duty_shift_id=hiring_shift["id"],
        status="OPEN",
        required_certification="NONE",
    )
    return {
        "station": station,
        "engine": engine,
        "technician": technician,
        "generalist": generalist,
        "officer": officer,
        "hiring_shift": hiring_shift,
        "hazmat_vacancy": hazmat_vacancy,
        "plain_vacancy": plain_vacancy,
    }


class TestOvertimeOfferCostComposition:
    """Certification and fatigue uplifts compose, and the mode floors the hours."""

    def test_certification_and_fatigue_uplifts_are_summed_then_rounded_first(self, api):
        """The two uplifts sum into one percentage that is rounded before hours.

        PRD 3.6: "**Sum those two percentages into a single uplift, apply it to
        the member's `hourly_rate_cents`, and round the result half up to whole
        cents first** — that rounded figure is the effective rate."

        Design: Difficulty/combinatorial_formula/overtime_offer_cost_nested_premium_and_mode_minimum_hours
        """
        world = _hazmat_company_with_a_fatigued_technician(api)

        offer = validate_success(
            api.offer_vacancy(
                world["hazmat_vacancy"]["id"],
                {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
                STAFFING_OFFICER,
            ),
            201,
        )

        assert offer["firefighter_id"] == world["technician"]["id"]
        assert offer["hiring_mode"] == "VOLUNTARY"
        assert offer["offer_hours"] == 24
        assert offer["status"] == "OFFERED"
        # 8 per cent hazmat + 10 per cent fatigue on 4237 rounds to 5000 cents
        # per hour, and 5000 * 24 * 1.5 is exactly 180000.
        assert offer["projected_cost_cents"] == 180000

    def test_callback_minimum_hours_raise_the_payable_figure_before_pricing(self, api):
        """A three-hour callback minimum turns a two-hour request into three hours.

        PRD 3.6: "The offer's stored `offer_hours` is that payable figure — so a
        three-hour callback minimum turns a two-hour request into three payable
        hours."

        Design: Difficulty/combinatorial_formula/overtime_offer_cost_nested_premium_and_mode_minimum_hours
        """
        world = _hazmat_company_with_a_fatigued_technician(api)

        hazmat_offer = validate_success(
            api.offer_vacancy(
                world["hazmat_vacancy"]["id"],
                {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
                STAFFING_OFFICER,
            ),
            201,
        )
        callback_offer = validate_success(
            api.offer_vacancy(
                world["plain_vacancy"]["id"],
                {"hiring_mode": "CALLBACK", "offer_hours": 2},
                STAFFING_OFFICER,
            ),
            201,
        )

        assert callback_offer["firefighter_id"] == world["generalist"]["id"]
        assert callback_offer["offer_hours"] == 3
        # No certification premium and no fatigue block, so the effective rate
        # stays 4237 and double time on three hours is 25422.
        assert callback_offer["projected_cost_cents"] == 25422

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == (
            hazmat_offer["projected_cost_cents"] + callback_offer["projected_cost_cents"]
        )
        assert station["ot_committed_cents"] == 205422


# ---------------------------------------------------------------------------
# Forecast: rounding per vacancy before summation
# ---------------------------------------------------------------------------
def _station_with_three_differently_certified_open_seats(api):
    """Three single-seat companies whose specialties carry different uplifts."""
    station = fx.create_station(
        api,
        name="Station 44",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-44",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=["PARAMEDIC"],
        closure_priority=10,
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="HAZMAT-44",
        apparatus_type="HAZMAT",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=20,
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="TRUCK-44",
        apparatus_type="LADDER",
        minimum_crew_size=1,
        required_certifications=["TECHNICAL_RESCUE"],
        closure_priority=30,
    )
    for name, seniority, kelly, rate in (
        ("I Ibarra", 1, 1, 4237),
        ("J Jansen", 2, 2, 3916),
        ("K Kimura", 3, 3, 4602),
    ):
        fx.create_firefighter(
            api,
            station["id"],
            full_name=name,
            platoon="C",
            seniority_rank=seniority,
            kelly_day_cycle_position=kelly,
            certifications=[],
            hourly_rate_cents=rate,
        )
    shift = fx.published_shift(api, station["id"], "2026-08-23", "C")
    return {"station": station, "shift": shift}


class TestVacancyDrivenForecastRounding:
    """Each open seat is rounded on its own before the amounts are added."""

    def test_each_open_seat_is_rounded_before_the_amounts_are_added(self, api):
        """Rounding per vacancy and summing afterwards is the only correct order.

        PRD 2.9: "**The vacancy-driven forecast rounds per vacancy, before
        summation.** Each open seat's uplifted cost is rounded to whole cents
        individually and the rounded amounts are then added. Summing first and
        uplifting once yields a different integer and is wrong."

        Design: Difficulty/combinatorial_formula/forecast_rounds_each_vacancy_before_summing
        """
        world = _station_with_three_differently_certified_open_seats(api)

        forecast = validate_success(
            api.get_overtime_forecast(
                world["station"]["id"], STAFFING_OFFICER, method="VACANCY_DRIVEN"
            ),
            200,
        )

        # 171441 (paramedic) + 153072 (none) + 165318 (technical rescue)
        assert forecast["vacancy_driver_cents"] == 489831
        assert forecast["vacancy_driver_cents"] != 489830, (
            "summing before uplifting loses a cent"
        )
        assert forecast["forecast_cents"] == 489831

    def test_forecast_base_and_tail_are_reported_alongside_the_seat_total(self, api):
        """The shared base and tail figures accompany the bottom-up total.

        PRD 3.9: "`projected_period_total_cents` is `ot_actual_cents` plus
        `ot_committed_cents` plus `forecast_cents`; `variance_cents` is
        `fiscal_ot_budget_cents` less that total; and `forecast_posture` reads
        `WITHIN` when `variance_cents` is zero or positive and `OVER` when it is
        negative."

        Design: Difficulty/combinatorial_formula/forecast_rounds_each_vacancy_before_summing
        """
        world = _station_with_three_differently_certified_open_seats(api)

        forecast = validate_success(
            api.get_overtime_forecast(
                world["station"]["id"], STAFFING_OFFICER, method="VACANCY_DRIVEN"
            ),
            200,
        )

        assert forecast["station_id"] == world["station"]["id"]
        assert forecast["avg_rate_cents"] == 4252
        assert forecast["shift_base_cents"] == 153072
        assert forecast["horizon_vacancy_count"] == 3
        assert forecast["injury_headcount"] == 0
        assert forecast["injury_driver_cents"] == 0
        assert forecast["projected_period_total_cents"] == 489831
        assert forecast["variance_cents"] == 8510169
        assert forecast["forecast_posture"] == "WITHIN"
