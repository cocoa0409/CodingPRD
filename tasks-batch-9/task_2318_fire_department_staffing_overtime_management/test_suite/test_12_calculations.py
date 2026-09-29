"""Derived figures: the academy signal, the budget bands, the fatigue merge, the
FLSA premium, coverage arithmetic, seat allocation, closure selection, hiring
order, the forecast horizon and the adjudication queue.
"""

from test_helpers import PAYROLL_ANALYST, STAFFING_OFFICER
from test_helpers import fixtures as fx
from test_helpers import validate_paginated, validate_success


# ---------------------------------------------------------------------------
# Academy hiring signal
# ---------------------------------------------------------------------------
class TestAcademyHiringSignal:
    """Open seats and injured bodies are weighted differently and rounded up."""

    def test_an_injured_body_counts_twice_and_the_class_size_rounds_up(self, api):
        """Five open seats plus one injury recommend a class of two.

        PRD 3.9: "`raw_need` is `open_vacancy_seats` plus twice
        `injury_headcount`, because a member on injury leave leaves a hole on
        every rotation rather than on one shift. `recommended_recruit_count`
        converts that need into bodies by dividing by the four-platoon coverage
        factor and **rounding up** to a whole recruit — one position must be
        covered on every platoon, and a raw need of one already recommends one
        recruit."

        Design: Corner/calculations/academy_hiring_signal_weights_injury_headcount_and_ceils_the_class
        """
        station = fx.create_station(
            api,
            name="Station 90",
            battalion_code="E2",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-90",
            minimum_crew_size=5,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="H Hoyt",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.set_availability(
            api,
            member["id"],
            effective_date="2026-08-01",
            employment_status="INJURY_LEAVE",
            expected_firefighter_version=member["version"],
        )
        fx.published_shift(api, station["id"], "2026-08-11", "C")

        signal = validate_success(
            api.get_academy_hiring_signal(station["id"], STAFFING_OFFICER), 200
        )

        assert signal["station_id"] == station["id"]
        assert signal["open_vacancy_seats"] == 5
        assert signal["injury_headcount"] == 1
        # Five seats plus twice one injured body, not six.
        assert signal["raw_need"] == 7
        # Seven bodies over four platoons rounds up to two recruits, not one.
        assert signal["recommended_recruit_count"] == 2
        assert signal["signal_tier"] == "MONITOR"

    def test_a_single_open_seat_already_recommends_one_recruit(self, api):
        """A raw need of one bands as MONITOR rather than NONE.

        PRD 3.9: "The `signal_tier` then bands the recommendation: a
        recommendation of zero recruits is `NONE`; anything from one through eight
        inclusive is `MONITOR`; anything from nine through twenty inclusive is
        `RECRUIT`; anything above twenty is `SURGE`."

        Design: Corner/calculations/academy_hiring_signal_single_open_seat_already_recommends_one_recruit
        """
        station = fx.create_station(
            api,
            name="Station 92",
            battalion_code="E2",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-92",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        fx.published_shift(api, station["id"], "2026-08-11", "C")

        signal = validate_success(
            api.get_academy_hiring_signal(station["id"], PAYROLL_ANALYST), 200
        )

        assert signal["open_vacancy_seats"] == 1
        assert signal["injury_headcount"] == 0
        assert signal["raw_need"] == 1
        assert signal["recommended_recruit_count"] == 1
        assert signal["signal_tier"] == "MONITOR"
        assert signal["signal_tier"] != "NONE"


# ---------------------------------------------------------------------------
# Budget posture bands
# ---------------------------------------------------------------------------
def _station_ready_to_hire_one_shift(
    api, name, budget, unit, member_name, seniority_rank=1
):
    """A one-seat station whose only open vacancy can be offered immediately.

    ``seniority_rank`` is a parameter because PRD 3.1 makes the key "unique
    department-wide": two stations stood up inside one test may not both enrol a
    member at rank 1.
    """
    station = fx.create_station(
        api,
        name=name,
        battalion_code="E3",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=budget,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation=unit,
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name=member_name,
        platoon="C",
        seniority_rank=seniority_rank,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
    return {"station": station, "member": member, "vacancy": vacancy}


class TestBudgetPostureBandBoundary:
    """Nine thousand basis points is inside the WITHIN band; 9,001 is not."""

    def test_the_same_encumbrance_bands_within_or_watch_on_either_side_of_the_line(
        self, api
    ):
        """One basis point past the band flips the posture.

        PRD 2.10: "Consumption at or below 9,000 basis points is `WITHIN`; above
        that but at or below 10,000 basis points is `WATCH`; anything above 10,000
        basis points is `OVER`."

        Design: Corner/calculations/budget_posture_within_band_boundary_at_exactly_nine_thousand_basis_points
        """
        on_the_line = _station_ready_to_hire_one_shift(
            api, "Station 93", 160_000, "ENGINE-93", "I Ibarra"
        )
        just_past = _station_ready_to_hire_one_shift(
            api, "Station 94", 159_982, "ENGINE-94", "J Jarvis", seniority_rank=2
        )

        # Neither hire is refused: 144000 is at or below both budgets.
        first = fx.dispatch_offer(api, on_the_line["vacancy"]["id"], "VOLUNTARY", 24)
        second = fx.dispatch_offer(api, just_past["vacancy"]["id"], "VOLUNTARY", 24)
        assert first["projected_cost_cents"] == 144000
        assert second["projected_cost_cents"] == 144000

        # 144000 of 160000 is exactly 9,000 basis points.
        within = fx.read_station(api, on_the_line["station"]["id"])
        assert within["ot_committed_cents"] == 144000
        assert within["budget_posture"] == "WITHIN"

        # 144000 of 159982 rounds half up to 9,001 basis points.
        watch = fx.read_station(api, just_past["station"]["id"])
        assert watch["ot_committed_cents"] == 144000
        assert watch["budget_posture"] == "WATCH"


# ---------------------------------------------------------------------------
# The continuous-duty merge and its fatigue premium
# ---------------------------------------------------------------------------
class TestFatiguePremiumOnMergedTours:
    """A zero gap merges, and a merged block over 24 hours is priced up."""

    def test_a_second_consecutive_tour_is_priced_with_the_fatigue_uplift(self, api):
        """The merged forty-eight-hour block adds ten percent to the rate.

        PRD 3.6: "The fatigue premium is a further ten percent, applied when and
        only when the continuous-duty merge of §3.3 shows the new seat landing in
        a merged block longer than twenty-four hours."

        Design: Corner/calculations/continuous_duty_merge_of_adjacent_tours_adds_the_fatigue_premium
        """
        station = fx.create_station(
            api,
            name="Station 95",
            battalion_code="E4",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-95",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="K Keller",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")

        first_shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        fx.seat_member(
            api, first_shift["id"], member["id"], engine["id"], member["id"]
        )
        second_shift = fx.published_shift(api, station["id"], "2026-08-12", "D")
        vacancy = fx.first_vacancy(api, duty_shift_id=second_shift["id"], status="OPEN")

        offer = validate_success(
            api.offer_vacancy(
                vacancy["id"],
                {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
                STAFFING_OFFICER,
            ),
            201,
        )

        assert offer["firefighter_id"] == member["id"]
        # 4000 uplifted by ten percent is 4400; times 24 hours at time and a half.
        assert offer["projected_cost_cents"] == 158400
        assert offer["projected_cost_cents"] != 144000

        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 158400
        assert fx.read_vacancy(api, vacancy["id"])["status"] == "OFFERING"
        assert fx.read_firefighter(api, member["id"])["pending_offer_count"] == 1


# ---------------------------------------------------------------------------
# FLSA premium precision
# ---------------------------------------------------------------------------
class TestFlsaPremiumPrecision:
    """A half-cent product rounds up, never down.

    PRD 3.9 prices the premium at half the hourly rate, so an odd rate over an
    odd hour count lands exactly on a half cent.
    """

    def test_a_half_cent_premium_rounds_half_up(self, api):
        """Twenty-five hours at 4237 cents halved is 52962.5, which becomes 52963.

        PRD 3.9: "`flsa_premium_cents` prices whichever of the two the period's
        `status` selects, at the **half-time** premium: multiply the selected hour
        figure by the member's `hourly_rate_cents`, halve it, and round half up to
        whole cents."

        Design: Corner/calculations/flsa_premium_rounds_half_up_on_odd_hour_and_rate_product
        """
        station = fx.create_station(
            api,
            name="Station 96",
            battalion_code="E4",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="L Lamb",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4237,
        )
        period = fx.work_period_of(api, member["id"])

        adjusted = validate_success(
            api.hour_adjustment(
                period["id"],
                {
                    "adjustment_hours": 229,
                    "adjustment_basis": "SCHEDULED",
                    "reason": "imported hours from the prior 7(k) period",
                },
                PAYROLL_ANALYST,
            ),
            200,
        )

        assert adjusted["adjusted_scheduled_hours"] == 229
        assert adjusted["adjusted_worked_hours"] == 0
        assert adjusted["projected_flsa_overtime_hours"] == 25
        assert adjusted["final_flsa_overtime_hours"] == 0
        assert adjusted["flsa_premium_cents"] == 52963
        assert adjusted["status"] == "OPEN"


# ---------------------------------------------------------------------------
# The hour ledger's input set
# ---------------------------------------------------------------------------
class TestCancelledSeatLeavesTheHourLedger:
    """Only live seats feed the period's scheduled hours."""

    def test_cancelling_one_of_two_tours_halves_the_scheduled_hours(self, api):
        """A cancelled seat contributes nothing rather than staying in the sum.

        PRD 3.3: "the covering work period's scheduled hours are reduced by the
        seat's `scheduled_hours` and both the projected overtime hours and the
        premium are recomputed"

        Design: Corner/calculations/work_period_ledger_excludes_cancelled_seat_hours
        """
        station = fx.create_station(
            api,
            name="Station 97",
            battalion_code="E5",
            minimum_staffing_floor=0,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-97",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="M Mott",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        first_shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        kept = fx.seat_member(
            api, first_shift["id"], member["id"], engine["id"], member["id"]
        )
        second_shift = fx.published_shift(api, station["id"], "2026-08-12", "D")
        released = fx.seat_member(
            api,
            second_shift["id"],
            member["id"],
            engine["id"],
            member["id"],
            assignment_type="OVERTIME",
        )
        period = fx.work_period_of(api, member["id"])

        before = fx.read_work_period(api, period["id"])
        assert before["scheduled_hours"] == 48

        fx.cancel_seat(api, released["id"], member["id"], "second tour released")

        after = fx.read_work_period(api, period["id"])
        assert after["scheduled_hours"] == 24
        assert after["worked_hours"] == 0
        assert after["leave_hours"] == 0

        assert fx.read_assignment(api, released["id"])["status"] == "CANCELLED"
        assert fx.read_assignment(api, kept["id"])["status"] == "SCHEDULED"

        reopened = fx.read_shift(api, second_shift["id"])
        assert reopened["assigned_headcount"] == 0
        assert reopened["open_vacancy_count"] == 1
        assert reopened["status"] == "HIRING"


# ---------------------------------------------------------------------------
# Certification coverage
# ---------------------------------------------------------------------------
class TestCertificationCoverage:
    """The multiset difference is taken per specialty value."""

    def test_seating_one_specialty_closes_exactly_one_gap(self, api):
        """A hazmat seat closes the hazmat gap and leaves the paramedic gap open.

        PRD 2.11: "For each open company, take the multiset of its
        `required_certifications` and subtract the multiset of `seat_certification`
        values carried by that company's `SCHEDULED` assignments on this shift,
        ignoring seats whose `seat_certification` is `NONE`; the size of the
        remaining multiset is that company's gap."

        Design: Corner/calculations/certification_coverage_counts_each_unmet_specialty_separately
        """
        station = fx.create_station(
            api,
            name="Station 98",
            battalion_code="E5",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        squad = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="SQUAD-98",
            apparatus_type="RESCUE",
            minimum_crew_size=2,
            required_certifications=["PARAMEDIC", "HAZMAT_TECH"],
            closure_priority=10,
        )
        technician = fx.create_firefighter(
            api,
            station["id"],
            full_name="N Nunes",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=["HAZMAT_TECH"],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="O Ortiz",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")

        assert shift["certification_gap_count"] == 2
        assert shift["staffing_posture"] == "CRITICAL"

        fx.seat_member(
            api,
            shift["id"],
            technician["id"],
            squad["id"],
            officer["id"],
            seat_certification="HAZMAT_TECH",
        )

        after = fx.read_shift(api, shift["id"])
        assert after["certification_gap_count"] == 1
        assert after["assigned_headcount"] == 1
        assert after["staffing_gap"] == 1
        assert after["open_vacancy_count"] == 1
        assert after["status"] == "HIRING"
        # A non-zero certification gap outranks a small headcount gap.
        assert after["staffing_posture"] == "CRITICAL"

        remaining = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
        assert remaining["required_certification"] == "PARAMEDIC"


# ---------------------------------------------------------------------------
# Vacancy generation order
# ---------------------------------------------------------------------------
class TestVacancyGenerationOrder:
    """Companies are walked by closure priority and seat numbering restarts."""

    def test_seats_are_allocated_company_by_company_with_a_per_company_index(
        self, api
    ):
        """The priority-10 engine is exhausted before the priority-20 medic.

        PRD 3.2: "Walk the open companies sorted by `closure_priority` ascending
        with `created_at` ascending as the tie-break."

        Design: Corner/calculations/vacancy_generation_fills_companies_in_closure_priority_order_with_per_company_seat_index
        """
        station = fx.create_station(
            api,
            name="Station 99",
            battalion_code="E6",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        # Created medic-first, so creation order cannot explain the result.
        medic = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="MEDIC-99",
            apparatus_type="MEDIC",
            minimum_crew_size=1,
            required_certifications=["PARAMEDIC"],
            closure_priority=20,
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-99",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")

        rows, meta = validate_paginated(
            api.list_vacancies(
                STAFFING_OFFICER, duty_shift_id=shift["id"], status="OPEN"
            )
        )
        assert meta["total_count"] == 3
        assert shift["required_staffing"] == 3

        assert rows[0]["apparatus_id"] == engine["id"]
        assert rows[0]["seat_index"] == 1
        assert rows[1]["apparatus_id"] == engine["id"]
        assert rows[1]["seat_index"] == 2
        assert rows[1]["required_certification"] == "NONE"
        # The index restarts inside the next company rather than running to 3.
        assert rows[2]["apparatus_id"] == medic["id"]
        assert rows[2]["seat_index"] == 1
        assert rows[2]["required_certification"] == "PARAMEDIC"

        assert shift["certification_gap_count"] == 1
        assert shift["staffing_posture"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Company closure selection
# ---------------------------------------------------------------------------
class TestClosureSelector:
    """The highest closure priority goes first, and the exempt unit never goes."""

    def test_two_closures_walk_down_the_priority_order_and_spare_the_exempt_engine(
        self, api
    ):
        """Truck closes first, hazmat second, and the requirement falls each time.

        PRD 3.8: "Otherwise the pool is sorted by `closure_priority`
        **descending** — the highest priority number closes first — then by
        `minimum_crew_size` descending, then by `created_at` ascending, and the
        first company in that order is the one closed."

        Design: Corner/calculations/closure_selector_takes_highest_priority_non_exempt_company_first
        """
        station = fx.create_station(
            api,
            name="Station 100",
            battalion_code="E6",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-100",
            minimum_crew_size=4,
            required_certifications=[],
            closure_priority=10,
            closure_exempt=True,
        )
        hazmat = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="HAZMAT-100",
            apparatus_type="HAZMAT",
            minimum_crew_size=4,
            required_certifications=[],
            closure_priority=20,
        )
        truck = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="TRUCK-100",
            apparatus_type="LADDER",
            minimum_crew_size=4,
            required_certifications=[],
            closure_priority=30,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        assert shift["required_staffing"] == 12
        assert shift["staffing_posture"] == "CRITICAL"

        first = fx.close_company(
            api, shift["id"], "no crew available for the third company"
        )
        assert first["closed_apparatus_ids"] == [truck["id"]]
        assert first["required_staffing"] == 8

        second = fx.close_company(
            api, shift["id"], "still critical after the first closure"
        )
        assert second["closed_apparatus_ids"] == [truck["id"], hazmat["id"]]
        assert second["required_staffing"] == 4
        assert engine["id"] not in second["closed_apparatus_ids"]

        # Only the exempt engine's four seats remain open.
        assert second["open_vacancy_count"] == 4
        assert second["staffing_posture"] == "CRITICAL"
        assert second["status"] == "HIRING"

        closed_out = fx.list_vacancies(
            api, duty_shift_id=shift["id"], status="CLOSED_BY_COMPANY_CLOSURE"
        )
        assert len(closed_out) == 8


# ---------------------------------------------------------------------------
# Hiring order: callback versus voluntary
# ---------------------------------------------------------------------------
class TestHiringOrderModeDivergence:
    """Callback reaches off duty; voluntary has no platoon filter at all."""

    def test_callback_and_voluntary_select_different_members_and_price_differently(
        self, api
    ):
        """The same pool yields opposite selections under the two modes.

        PRD 3.6: "Eligible members are those in the base pool whose
        `roster_standing` is `AVAILABLE` and whose `platoon` is **not** the
        platoon on duty for the shift date, because a callback by definition
        reaches somebody who is off duty."

        Design: Corner/calculations/hiring_order_variant_divergence_between_callback_and_voluntary
        """
        station = fx.create_station(
            api,
            name="Station 101",
            battalion_code="E7",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-101",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        on_duty = fx.create_firefighter(
            api,
            station["id"],
            full_name="P Pike",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        off_duty = fx.create_firefighter(
            api,
            station["id"],
            full_name="Q Quinn",
            platoon="D",
            seniority_rank=5,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4237,
        )
        callback_roster = fx.create_hiring_roster(api, station["id"], "CALLBACK", "NONE")
        voluntary_roster = fx.create_hiring_roster(
            api, station["id"], "VOLUNTARY_OT", "NONE"
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        seats = fx.list_vacancies(
            api, duty_shift_id=shift["id"], status="OPEN"
        )
        assert len(seats) == 2

        callback = fx.dispatch_offer(api, seats[0]["id"], "CALLBACK", 4)
        voluntary = fx.dispatch_offer(api, seats[1]["id"], "VOLUNTARY", 24)

        # The senior, cheaper member is on duty, so a callback cannot reach him.
        assert callback["firefighter_id"] == off_duty["id"]
        assert callback["hiring_mode"] == "CALLBACK"
        assert callback["roster_id"] == callback_roster["id"]
        # 4237 cents over four payable hours at double time.
        assert callback["projected_cost_cents"] == 33896

        assert voluntary["firefighter_id"] == on_duty["id"]
        assert voluntary["roster_id"] == voluntary_roster["id"]
        assert voluntary["projected_cost_cents"] == 144000

        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 177896
        assert all(
            fx.read_vacancy(api, seat["id"])["status"] == "OFFERING" for seat in seats
        )

        for roster in (callback_roster, voluntary_roster):
            reread = validate_success(
                api.get_hiring_roster(roster["id"], STAFFING_OFFICER), 200
            )
            assert reread["dispatch_count"] == 1


# ---------------------------------------------------------------------------
# Forecast horizon
# ---------------------------------------------------------------------------
class TestForecastHorizon:
    """The bottom-up horizon is bounded by today and by the fiscal period end."""

    def test_only_the_vacancy_inside_the_window_drives_the_forecast(self, api):
        """A past seat and a post-period seat are both outside the horizon.

        PRD 3.9: "Its horizon is every vacancy at the station in `OPEN` or
        `OFFERING` status whose shift date is on or after the current date and on
        or before the station's `fiscal_period_end_date`; the count of those is
        reported as `horizon_vacancy_count`."

        Design: Corner/calculations/forecast_horizon_excludes_past_and_post_fiscal_vacancies
        """
        station = fx.create_station(
            api,
            name="Station 102",
            battalion_code="E7",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-102",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        fx.create_firefighter(
            api,
            station["id"],
            full_name="R Rossi",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.published_shift(api, station["id"], "2026-08-10", "B")
        fx.published_shift(api, station["id"], "2026-08-12", "D")
        fx.published_shift(api, station["id"], "2026-09-05", "D")
        fx.set_clock(api, "2026-08-11T00:00:00Z")

        forecast = validate_success(
            api.get_overtime_forecast(
                station["id"], STAFFING_OFFICER, method="VACANCY_DRIVEN"
            ),
            200,
        )

        assert forecast["avg_rate_cents"] == 4000
        assert forecast["shift_base_cents"] == 144000
        # Only the 2026-08-12 seat is on or after today and inside the period.
        assert forecast["horizon_vacancy_count"] == 1
        assert forecast["vacancy_driver_cents"] == 144000
        assert forecast["injury_headcount"] == 0
        assert forecast["injury_driver_cents"] == 0
        assert forecast["forecast_cents"] == 144000
        assert forecast["projected_period_total_cents"] == 144000
        assert forecast["variance_cents"] == 356000
        assert forecast["forecast_posture"] == "WITHIN"
        # The unselected method's fields are returned as zero.
        assert forecast["daily_run_rate_cents"] == 0
        assert forecast["remaining_days"] == 0


# ---------------------------------------------------------------------------
# Leave adjudication order
# ---------------------------------------------------------------------------
class TestLeaveAdjudicationOrder:
    """Type priority beats filing order, and the headcount runs down the queue."""

    def test_the_sick_call_is_decided_first_and_consumes_the_only_slack(self, api):
        """The last-filed SICK request is adjudicated first and takes the slack.

        PRD 3.4: "Collect every `QUEUED` request on the shift and sort them by
        leave-type priority ascending, where `INJURY` ranks 1, `SICK` ranks 2,
        `KELLY_DAY` ranks 3, `BEREAVEMENT` ranks 4 and `VACATION` ranks 5; break
        ties by `seniority_rank` ascending, so the most senior member is
        considered first; break remaining ties by `created_at` ascending."

        Design: Corner/calculations/leave_adjudication_orders_by_type_then_seniority_against_running_headcount
        """
        station = fx.create_station(
            api,
            name="Station 103",
            battalion_code="E8",
            minimum_staffing_floor=2,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-103",
            minimum_crew_size=3,
            required_certifications=[],
            closure_priority=10,
        )
        senior = fx.create_firefighter(
            api,
            station["id"],
            full_name="S Stagg",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        junior = fx.create_firefighter(
            api,
            station["id"],
            full_name="T Trent",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )
        sick = fx.create_firefighter(
            api,
            station["id"],
            full_name="U Uhle",
            platoon="C",
            seniority_rank=3,
            kelly_day_cycle_position=3,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="V Vance",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=4,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        senior_seat = fx.seat_member(
            api, shift["id"], senior["id"], engine["id"], officer["id"]
        )
        junior_seat = fx.seat_member(
            api, shift["id"], junior["id"], engine["id"], officer["id"]
        )
        sick_seat = fx.seat_member(
            api, shift["id"], sick["id"], engine["id"], officer["id"]
        )

        # Filed deliberately out of adjudication order.
        junior_leave = fx.file_leave(api, junior["id"], shift["id"], "VACATION", 24)
        senior_leave = fx.file_leave(api, senior["id"], shift["id"], "VACATION", 24)
        sick_leave = fx.file_leave(api, sick["id"], shift["id"], "SICK", 24)

        fx.adjudicate_leave(api, shift["id"], officer["id"])

        decided_sick = fx.read_leave(api, sick_leave["id"])
        assert decided_sick["decision_order_index"] == 1
        assert decided_sick["status"] == "APPROVED"

        decided_senior = fx.read_leave(api, senior_leave["id"])
        assert decided_senior["decision_order_index"] == 2
        assert decided_senior["status"] == "DENIED"
        assert decided_senior["denial_reason"] == "STAFFING_FLOOR"

        decided_junior = fx.read_leave(api, junior_leave["id"])
        assert decided_junior["decision_order_index"] == 3
        assert decided_junior["status"] == "DENIED"
        assert decided_junior["denial_reason"] == "STAFFING_FLOOR"

        assert fx.read_assignment(api, sick_seat["id"])["status"] == "RELIEVED"
        assert fx.read_assignment(api, senior_seat["id"])["status"] == "SCHEDULED"
        assert fx.read_assignment(api, junior_seat["id"])["status"] == "SCHEDULED"

        after = fx.read_shift(api, shift["id"])
        assert after["assigned_headcount"] == 2
        assert after["staffing_gap"] == 1
        assert after["open_vacancy_count"] == 1
        assert after["status"] == "HIRING"
        assert after["staffing_posture"] == "SHORT"

        backfill = fx.first_vacancy(
            api, duty_shift_id=shift["id"], driver="LEAVE", status="OPEN"
        )
        assert backfill["driver_source_id"] == sick_leave["id"]
