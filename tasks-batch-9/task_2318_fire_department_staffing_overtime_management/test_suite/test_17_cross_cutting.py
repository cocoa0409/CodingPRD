"""Cross-cutting layers: optimistic concurrency on the three guarded writes, the
injury-leave cascade end to end, the overtime pass limit, and the hiring order's
fairness-before-seniority ranking.
"""

from test_helpers import (
    PAYROLL_ANALYST,
    STAFFING_OFFICER,
    ApiErrorId,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Optimistic concurrency on the three guarded writes
# ---------------------------------------------------------------------------
def _two_riders_and_a_published_shift(api):
    """A two-body company with two members available and an officer to seat them."""
    station = fx.create_station(
        api,
        name="Station 130",
        battalion_code="G4",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-130",
        apparatus_type="ENGINE",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    first = fx.create_firefighter(
        api,
        station["id"],
        full_name="Q Quiroz",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    second = fx.create_firefighter(
        api,
        station["id"],
        full_name="R Rowe",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="S Sowell",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    return {
        "station": station,
        "engine": engine,
        "first": first,
        "second": second,
        "officer": officer,
        "shift": shift,
    }


def _seat_payload(world, firefighter_id, version):
    return {
        "duty_shift_id": world["shift"]["id"],
        "firefighter_id": firefighter_id,
        "apparatus_id": world["engine"]["id"],
        "assignment_type": "REGULAR",
        "seat_certification": "NONE",
        "scheduled_hours": 24,
        "expected_duty_shift_version": version,
    }


class TestOptimisticConcurrency:
    def test_a_shift_version_spent_on_one_seat_is_stale_for_the_next_write(self, api):
        """PRD 2.7: "Creating a shift assignment (`POST
        /fire-ops/shift-assignments`) requires `expected_duty_shift_version`
        carrying the client's last observed `version` of the parent `DutyShift`.
        If it does not equal the shift's current `version`, the create is
        rejected with `ERR_STALE_VERSION` and HTTP 412."  The first seat
        increments that version (PRD 3.3: the shift "increments its `version`"),
        so replaying the same number is stale.  Closing a company is guarded "on
        the same terms", and PRD 2.6 ranks the check seventh, ahead of the
        closure-justification rule, so the closure reports 412 rather than
        `ERR_CLOSURE_NOT_JUSTIFIED`.

        Design: Corner/cross_cutting_complexity_layers/stale_parent_versions_are_refused_on_all_three_occ_write_paths
        """
        world = _two_riders_and_a_published_shift(api)
        stale = world["shift"]["version"]

        validate_success(
            api.create_shift_assignment(
                _seat_payload(world, world["first"]["id"], stale),
                fx.make_company_officer_headers(world["officer"]["id"]),
            ),
            201,
        )
        assert fx.read_shift(api, world["shift"]["id"])["version"] == stale + 1

        validate_error(
            api.create_shift_assignment(
                _seat_payload(world, world["second"]["id"], stale),
                fx.make_company_officer_headers(world["officer"]["id"]),
            ),
            ApiErrorId.STALE_VERSION.value,
            412,
        )
        _, meta = validate_paginated(
            api.list_shift_assignments(
                STAFFING_OFFICER, firefighter_id=world["second"]["id"]
            )
        )
        assert meta["total_count"] == 0

        closure = api.company_closure(
            world["shift"]["id"],
            {"expected_duty_shift_version": stale, "justification": "short one rider"},
            STAFFING_OFFICER,
        )
        validate_error(closure, ApiErrorId.STALE_VERSION.value, 412)
        assert closure.json()["data"]["error_id"] != ApiErrorId.CLOSURE_NOT_JUSTIFIED.value

        after = fx.read_shift(api, world["shift"]["id"])
        assert after["version"] == stale + 1
        assert after["closed_apparatus_ids"] == []

    def test_a_member_version_spent_on_one_availability_write_is_stale_for_the_next(
        self, api
    ):
        """PRD 2.7: "Setting a member's availability (`POST
        /fire-ops/firefighters/{firefighter_id}/availability`) requires
        `expected_firefighter_version` carrying the client's last observed
        `version` of the target `Firefighter`, rejected with `ERR_STALE_VERSION`
        (412) on a mismatch."  PRD 3.2 adds that "Each availability change
        increments the member's `version` by one", so the second call replaying
        the first call's version is refused - and because "a request that fails
        any check writes nothing at all" (PRD 2.6), the injury cascade that call
        would have run never starts.

        Design: Corner/cross_cutting_complexity_layers/stale_parent_versions_are_refused_on_all_three_occ_write_paths
        """
        world = _two_riders_and_a_published_shift(api)
        seat = fx.seat_member(
            api,
            world["shift"]["id"],
            world["first"]["id"],
            world["engine"]["id"],
            world["officer"]["id"],
            expected_duty_shift_version=world["shift"]["version"],
        )
        stale_member_version = fx.read_firefighter(api, world["first"]["id"])["version"]

        updated = validate_success(
            api.set_availability(
                world["first"]["id"],
                {
                    "expected_firefighter_version": stale_member_version,
                    "effective_date": "2026-08-01",
                    "roster_standing": "AVAILABLE",
                },
                STAFFING_OFFICER,
            ),
            200,
        )
        assert updated["version"] == stale_member_version + 1

        validate_error(
            api.set_availability(
                world["first"]["id"],
                {
                    "expected_firefighter_version": stale_member_version,
                    "effective_date": "2026-08-01",
                    "employment_status": "INJURY_LEAVE",
                },
                STAFFING_OFFICER,
            ),
            ApiErrorId.STALE_VERSION.value,
            412,
        )

        member = fx.read_firefighter(api, world["first"]["id"])
        assert member["employment_status"] == "ACTIVE"
        assert member["version"] == stale_member_version + 1
        assert fx.read_assignment(api, seat["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# One availability write cascades through five entities
# ---------------------------------------------------------------------------
def _fully_staffed_company_with_a_second_rider(api):
    """A one-body company carrying its permitted extra rider, so the shift is
    STAFFED with two bodies and no open vacancy.
    """
    station = fx.create_station(
        api,
        name="Station 131",
        battalion_code="G4",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-131",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    keeper = fx.create_firefighter(
        api,
        station["id"],
        full_name="T Tull",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    injured = fx.create_firefighter(
        api,
        station["id"],
        full_name="U Ulmer",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="V Vinson",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    keeper_seat = fx.seat_member(
        api,
        shift["id"],
        keeper["id"],
        engine["id"],
        officer["id"],
        expected_duty_shift_version=shift["version"],
    )
    extra_seat = fx.seat_member(
        api,
        shift["id"],
        injured["id"],
        engine["id"],
        officer["id"],
    )
    staffed = fx.read_shift(api, shift["id"])
    assert staffed["status"] == "STAFFED"
    assert staffed["assigned_headcount"] == 2
    assert staffed["open_vacancy_count"] == 0
    return {
        "station": station,
        "engine": engine,
        "keeper": keeper,
        "injured": injured,
        "officer": officer,
        "shift": shift,
        "keeper_seat": keeper_seat,
        "extra_seat": extra_seat,
        "work_period": fx.work_period_of(api, injured["id"]),
    }


class TestInjuryLeaveCascade:
    def test_the_injury_write_cancels_only_that_members_seat_and_opens_a_backfill(
        self, api
    ):
        """PRD 3.2: "Moving a member **to** `INJURY_LEAVE` cascades: every
        `SCHEDULED` assignment the member holds on a shift dated on or after
        `effective_date` moves to `CANCELLED`; for each seat so vacated a vacancy
        is created in `OPEN` status with `driver` set to `INJURY` and
        `driver_source_id` set to the member's own id; and every affected shift
        recomputes its staffing fields, so a `STAFFED` shift falls back to
        `HIRING`."  The colleague's seat is untouched, and because the company's
        minimum crew is one, the surviving body still closes the headcount gap:
        an open backfill seat coexists with `FULLY_STAFFED`.

        Design: Corner/cross_cutting_complexity_layers/injury_leave_cascades_from_availability_through_to_the_academy_signal
        """
        world = _fully_staffed_company_with_a_second_rider(api)
        before = fx.read_firefighter(api, world["injured"]["id"])

        moved = validate_success(
            api.set_availability(
                world["injured"]["id"],
                {
                    "expected_firefighter_version": before["version"],
                    "effective_date": "2026-08-01",
                    "employment_status": "INJURY_LEAVE",
                },
                STAFFING_OFFICER,
            ),
            200,
        )
        assert moved["employment_status"] == "INJURY_LEAVE"
        assert moved["version"] == before["version"] + 1

        assert fx.read_assignment(api, world["extra_seat"]["id"])["status"] == "CANCELLED"
        assert fx.read_assignment(api, world["keeper_seat"]["id"])["status"] == "SCHEDULED"

        backfills = fx.list_vacancies(
            api, duty_shift_id=world["shift"]["id"], driver="INJURY"
        )
        assert len(backfills) == 1
        assert backfills[0]["status"] == "OPEN"
        assert backfills[0]["driver_source_id"] == world["injured"]["id"]

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "HIRING"
        assert shift["open_vacancy_count"] == 1
        assert shift["assigned_headcount"] == 1
        assert shift["staffing_gap"] == 0
        assert shift["staffing_posture"] == "FULLY_STAFFED"

    def test_the_hour_ledger_unwinds_and_the_academy_signal_weights_the_injury(
        self, api
    ):
        """PRD 3.9: "Every operation that puts a member in a seat adds the seat's
        hours and every operation that takes them out subtracts exactly the same
        number", so cancelling the only seat returns the period to zero hours and
        no premium.  PRD 3.10: "`open_vacancy_seats` counts every vacancy at the
        station in `OPEN` or `OFFERING` status ... `injury_headcount` counts the
        station's members whose `employment_status` is `INJURY_LEAVE`. `raw_need`
        is `open_vacancy_seats` plus twice `injury_headcount`, because a member on
        injury leave leaves a hole on every rotation rather than on one shift",
        and one recruit covers a raw need of three across four platoons.

        Design: Corner/cross_cutting_complexity_layers/injury_leave_cascades_from_availability_through_to_the_academy_signal
        """
        world = _fully_staffed_company_with_a_second_rider(api)
        before = fx.read_firefighter(api, world["injured"]["id"])
        fx.set_availability(
            api,
            world["injured"]["id"],
            effective_date="2026-08-01",
            employment_status="INJURY_LEAVE",
            expected_firefighter_version=before["version"],
        )

        period = fx.read_work_period(api, world["work_period"]["id"])
        assert period["scheduled_hours"] == 0
        assert period["flsa_premium_cents"] == 0

        signal = validate_success(
            api.get_academy_hiring_signal(world["station"]["id"], PAYROLL_ANALYST), 200
        )
        assert signal["open_vacancy_seats"] == 1
        assert signal["injury_headcount"] == 1
        assert signal["raw_need"] == 3
        assert signal["recommended_recruit_count"] == 1
        assert signal["signal_tier"] == "MONITOR"

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0


# ---------------------------------------------------------------------------
# The overtime pass limit
# ---------------------------------------------------------------------------
def _lone_member_and_four_open_seats(api):
    station = fx.create_station(
        api,
        name="Station 132",
        battalion_code="G5",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=900_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-132",
        apparatus_type="ENGINE",
        minimum_crew_size=4,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="W Wender",
        rank="FIREFIGHTER",
        platoon="D",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    roster = fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    vacancies = fx.list_vacancies(api, duty_shift_id=shift["id"], status="OPEN")
    assert len(vacancies) == 4
    return {
        "station": station,
        "member": member,
        "roster": roster,
        "shift": shift,
        "vacancies": vacancies,
    }


def _decline_one_offer(api, world, vacancy_id):
    offer = fx.dispatch_offer(api, vacancy_id, "VOLUNTARY", 24)
    assert offer["firefighter_id"] == world["member"]["id"]
    return fx.answer_offer(api, offer["id"], world["member"]["id"], "DECLINE"), offer


class TestOvertimePassLimit:
    def test_two_declines_charge_the_hours_without_passing_the_member(self, api):
        """PRD 3.7: "**Declining** moves the offer `OFFERED -> DECLINED` and
        returns the vacancy `OFFERING -> OPEN` ... the member's
        `voluntary_ot_hours_charged` increases by the offer's payable
        `offer_hours` **exactly as if the hours had been worked**, their
        `ot_pass_count` increases by one ... When `ot_pass_count` reaches three
        or more, the member's `roster_standing` flips to `PASSED`".  Two passes
        do not reach three, so the member is still `AVAILABLE` while carrying 48
        charged hours, and "The station's `ot_committed_cents` is credited back
        the offer's `projected_cost_cents`".

        Design: Corner/cross_cutting_complexity_layers/third_declined_offer_passes_the_member_and_empties_the_candidate_pool
        """
        world = _lone_member_and_four_open_seats(api)

        _decline_one_offer(api, world, world["vacancies"][0]["id"])
        after_one = fx.read_firefighter(api, world["member"]["id"])
        assert after_one["ot_pass_count"] == 1
        assert after_one["voluntary_ot_hours_charged"] == 24
        assert after_one["roster_standing"] == "AVAILABLE"
        assert fx.read_vacancy(api, world["vacancies"][0]["id"])["status"] == "OPEN"

        _, second_offer = _decline_one_offer(api, world, world["vacancies"][1]["id"])
        assert fx.read_offer(api, second_offer["id"])["status"] == "DECLINED"

        after_two = fx.read_firefighter(api, world["member"]["id"])
        assert after_two["ot_pass_count"] == 2
        assert after_two["voluntary_ot_hours_charged"] == 48
        assert after_two["roster_standing"] == "AVAILABLE"
        assert fx.read_station(api, world["station"]["id"])["ot_committed_cents"] == 0

    def test_the_third_decline_passes_the_member_and_empties_the_pool(self, api):
        """PRD 3.7: "When `ot_pass_count` reaches three or more, the member's
        `roster_standing` flips to `PASSED`, which excludes them from the
        voluntary and callback candidate pools", and the hiring order refuses a
        dispatch with "`ERR_NO_ELIGIBLE_CANDIDATE`" when "the pool is empty".
        PRD 2.6 adds that "a request that fails any check writes nothing at
        all", so the refused dispatch leaves the roster's `dispatch_count` at the
        three offers that actually went out.

        Design: Corner/cross_cutting_complexity_layers/third_declined_offer_passes_the_member_and_empties_the_candidate_pool
        """
        world = _lone_member_and_four_open_seats(api)
        for index in range(3):
            _decline_one_offer(api, world, world["vacancies"][index]["id"])

        passed = fx.read_firefighter(api, world["member"]["id"])
        assert passed["ot_pass_count"] == 3
        assert passed["voluntary_ot_hours_charged"] == 72
        assert passed["roster_standing"] == "PASSED"

        validate_error(
            api.offer_vacancy(
                world["vacancies"][3]["id"],
                {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
                STAFFING_OFFICER,
            ),
            ApiErrorId.NO_ELIGIBLE_CANDIDATE.value,
            422,
        )

        assert fx.read_vacancy(api, world["vacancies"][3]["id"])["status"] == "OPEN"
        roster = validate_success(
            api.get_hiring_roster(world["roster"]["id"], STAFFING_OFFICER), 200
        )
        assert roster["dispatch_count"] == 3

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0
        assert station["budget_posture"] == "WITHIN"

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["open_vacancy_count"] == 4
        assert shift["status"] == "HIRING"


# ---------------------------------------------------------------------------
# Fairness hours dominate seniority in the hiring order
# ---------------------------------------------------------------------------
def _two_equal_members_and_two_published_shifts(api):
    station = fx.create_station(
        api,
        name="Station 133",
        battalion_code="G5",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=900_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-133",
        apparatus_type="ENGINE",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    senior = fx.create_firefighter(
        api,
        station["id"],
        full_name="X Xiong",
        rank="FIREFIGHTER",
        platoon="D",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    junior = fx.create_firefighter(
        api,
        station["id"],
        full_name="Y Yerby",
        rank="FIREFIGHTER",
        platoon="D",
        seniority_rank=2,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
    first_shift = fx.published_shift(
        api, station["id"], shift_date="2026-08-11", platoon="C"
    )
    first_vacancies = fx.list_vacancies(
        api, duty_shift_id=first_shift["id"], status="OPEN"
    )
    second_shift = fx.published_shift(
        api, station["id"], shift_date="2026-08-12", platoon="D"
    )
    second_vacancies = fx.list_vacancies(
        api, duty_shift_id=second_shift["id"], status="OPEN"
    )
    assert len(first_vacancies) == 2 and len(second_vacancies) == 2
    return {
        "station": station,
        "senior": senior,
        "junior": junior,
        "first_shift": first_shift,
        "first_vacancies": first_vacancies,
        "second_shift": second_shift,
        "second_vacancies": second_vacancies,
    }


class TestHiringOrderFairness:
    def test_the_tie_on_zero_charged_hours_breaks_on_seniority(self, api):
        """PRD 3.6: `VOLUNTARY` candidates "are ranked by
        `voluntary_ot_hours_charged` ascending - the member who has been charged
        the fewest overtime hours is owed the next opportunity - then by
        `seniority_rank` ascending so the most senior of equals goes first".  Both
        members start at zero, so seniority decides the first offer; the second
        offer on the same shift cannot reach the senior member because the base
        pool requires that candidates "hold no `SCHEDULED` assignment on this
        shift".  Pricing follows PRD 3.6: `VOLUNTARY` "guarantees nothing", so
        four requested hours stay four and price at 4000 * 4 * 1.5.

        Design: Corner/cross_cutting_complexity_layers/hiring_order_tie_breaks_on_seniority_then_yields_to_fewest_charged_hours
        """
        world = _two_equal_members_and_two_published_shifts(api)

        first_offer = fx.dispatch_offer(
            api, world["first_vacancies"][0]["id"], "VOLUNTARY", 24
        )
        assert first_offer["firefighter_id"] == world["senior"]["id"]
        assert first_offer["projected_cost_cents"] == 144_000
        fx.answer_offer(api, first_offer["id"], world["senior"]["id"], "ACCEPT")

        second_offer = fx.dispatch_offer(
            api, world["first_vacancies"][1]["id"], "VOLUNTARY", 4
        )
        assert second_offer["firefighter_id"] == world["junior"]["id"]
        assert second_offer["offer_hours"] == 4
        assert second_offer["projected_cost_cents"] == 24_000
        fx.answer_offer(api, second_offer["id"], world["junior"]["id"], "ACCEPT")

        assert (
            fx.read_firefighter(api, world["senior"]["id"])["voluntary_ot_hours_charged"]
            == 24
        )
        assert (
            fx.read_firefighter(api, world["junior"]["id"])["voluntary_ot_hours_charged"]
            == 4
        )

    def test_fewest_charged_hours_outranks_seniority_on_the_next_shift(self, api):
        """PRD 3.6 ranks `VOLUNTARY` candidates "by
        `voluntary_ot_hours_charged` ascending ... then by `seniority_rank`
        ascending", so seniority only breaks ties: with 4 charged hours against
        24 the junior member is offered first on the following shift.  No fatigue
        premium applies, because PRD 3.3 merges only intervals where "an interval
        whose start is strictly later than the end of the block accumulated so
        far begins a new block" - his four-hour tour ends at 12:00 on 2026-08-11
        and the new tour starts at 08:00 on 2026-08-12 - so the price is again
        4000 * 24 * 1.5.

        Design: Corner/cross_cutting_complexity_layers/hiring_order_tie_breaks_on_seniority_then_yields_to_fewest_charged_hours
        """
        world = _two_equal_members_and_two_published_shifts(api)

        first_offer = fx.dispatch_offer(
            api, world["first_vacancies"][0]["id"], "VOLUNTARY", 24
        )
        fx.answer_offer(api, first_offer["id"], world["senior"]["id"], "ACCEPT")
        second_offer = fx.dispatch_offer(
            api, world["first_vacancies"][1]["id"], "VOLUNTARY", 4
        )
        fx.answer_offer(api, second_offer["id"], world["junior"]["id"], "ACCEPT")

        next_offer = fx.dispatch_offer(
            api, world["second_vacancies"][0]["id"], "VOLUNTARY", 24
        )
        assert next_offer["firefighter_id"] == world["junior"]["id"]
        assert next_offer["projected_cost_cents"] == 144_000

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 312_000
        assert station["budget_posture"] == "WITHIN"
