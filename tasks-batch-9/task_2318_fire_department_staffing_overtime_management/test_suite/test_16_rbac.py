"""Role-based access control: each role's own operations succeed, the same
operations are refused to every other role, the two analytics reads are shared
by the two office roles alone, and a trade decision turns on identity.
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
# Every role performs its own exclusive operation
# ---------------------------------------------------------------------------
def _station_with_a_draft_shift(api):
    """One single-seat company, a member, an officer, and an unpublished shift."""
    station = fx.create_station(
        api,
        name="Station 126",
        battalion_code="G2",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-126",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="I Ivers",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="J Jessup",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.create_duty_shift(
        api, station["id"], shift_date="2026-08-11", platoon="C"
    )
    return {
        "station": station,
        "engine": engine,
        "member": member,
        "officer": officer,
        "shift": shift,
        "work_period": fx.work_period_of(api, member["id"]),
    }


class TestEachRolesOwnOperations:
    def test_the_staffing_officer_publishes_and_the_company_officer_seats(self, api):
        """PRD 2.1: "The `StaffingOfficer` is the battalion staffing office: it
        owns all master data, opens and publishes shifts ... The
        `CompanyOfficer` is the officer on duty: it seats and un-seats members".
        PRD 3.2: "if `open_vacancy_count` came out greater than zero the shift
        moves `DRAFT -> HIRING`".  PRD 2.4: "Whenever any mutation leaves a shift
        in `HIRING` with `open_vacancy_count` at zero, the shift moves to
        `STAFFED`", which the single seat below achieves.

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operation
        """
        world = _station_with_a_draft_shift(api)

        published = validate_success(
            api.publish_duty_shift(world["shift"]["id"], STAFFING_OFFICER), 200
        )
        assert published["status"] == "HIRING"
        assert published["open_vacancy_count"] == 1

        seated = validate_success(
            api.create_shift_assignment(
                {
                    "duty_shift_id": world["shift"]["id"],
                    "firefighter_id": world["member"]["id"],
                    "apparatus_id": world["engine"]["id"],
                    "assignment_type": "REGULAR",
                    "seat_certification": "NONE",
                    "scheduled_hours": 24,
                    "expected_duty_shift_version": published["version"],
                },
                fx.make_company_officer_headers(world["officer"]["id"]),
            ),
            201,
        )
        assert seated["status"] == "SCHEDULED"
        assert fx.read_shift(api, world["shift"]["id"])["status"] == "STAFFED"

    def test_the_member_files_their_own_leave_and_the_analyst_adjusts_the_hours(
        self, api
    ):
        """PRD 2.1: "The `Firefighter` is a line member acting only on their own
        records: their own leave requests ... The `PayrollAnalyst` closes out
        elapsed shifts, records hour adjustments".  PRD 3.4: "Filing decides
        nothing: the request lands in `QUEUED` with `decision_order_index` and
        `denial_reason` both null".  PRD 3.9: "A `SCHEDULED` basis adds the hours
        to `adjusted_scheduled_hours`", and `scheduled_hours` is "the sum of
        `scheduled_hours` over the member's assignments in `SCHEDULED` or
        `WORKED` status whose shift date falls inside the window, plus the
        period's `adjusted_scheduled_hours`" - so the 24-hour seat plus a
        ten-hour drill adjustment reads 34 against an adjustment of 10.

        Design: Corner/rbac/each_role_can_perform_its_own_exclusive_operation
        """
        world = _station_with_a_draft_shift(api)
        published = fx.publish_shift(api, world["shift"]["id"])
        fx.seat_member(
            api,
            world["shift"]["id"],
            world["member"]["id"],
            world["engine"]["id"],
            world["officer"]["id"],
            expected_duty_shift_version=published["version"],
        )

        leave = validate_success(
            api.create_leave_request(
                {
                    "firefighter_id": world["member"]["id"],
                    "duty_shift_id": world["shift"]["id"],
                    "leave_type": "VACATION",
                    "requested_hours": 24,
                },
                fx.make_firefighter_headers(world["member"]["id"]),
            ),
            201,
        )
        assert leave["status"] == "QUEUED"
        assert leave["decision_order_index"] is None
        assert leave["denial_reason"] is None

        adjusted = validate_success(
            api.hour_adjustment(
                world["work_period"]["id"],
                {
                    "adjustment_hours": 10,
                    "adjustment_basis": "SCHEDULED",
                    "reason": "drill hours",
                },
                PAYROLL_ANALYST,
            ),
            200,
        )
        assert adjusted["adjusted_scheduled_hours"] == 10
        assert adjusted["scheduled_hours"] == 34


# ---------------------------------------------------------------------------
# The same operations attempted by the wrong role
# ---------------------------------------------------------------------------
def _station_with_a_published_shift_and_an_open_vacancy(api):
    station = fx.create_station(
        api,
        name="Station 127",
        battalion_code="G2",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=900_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-127",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="K Kelso",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="L Lyman",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
    return {
        "station": station,
        "engine": engine,
        "member": member,
        "officer": officer,
        "shift": shift,
        "vacancy": vacancy,
    }


class TestCrossRoleDenial:
    def test_the_analyst_cannot_register_a_company_and_the_officer_cannot_seat(
        self, api
    ):
        """PRD 2.1 gives master data to the `StaffingOfficer` and seating to the
        `CompanyOfficer`, and says of the staffing office that "it may not seat a
        member" while the analyst "has no staffing authority of any kind"; the
        endpoint table authorises `POST /fire-ops/apparatus` for
        `StaffingOfficer` and `POST /fire-ops/shift-assignments` for
        `CompanyOfficer`.  Authorisation is therefore per endpoint, not a
        blanket writer role, and PRD 2.6 makes the 403 precede every other
        check, so neither refusal writes anything.

        Design: Corner/rbac/each_exclusive_operation_is_forbidden_to_the_other_roles
        """
        world = _station_with_a_published_shift_and_an_open_vacancy(api)

        validate_error(
            api.create_apparatus(
                {
                    "station_id": world["station"]["id"],
                    "unit_designation": "SPARE-127",
                    "apparatus_type": "ENGINE",
                    "minimum_crew_size": 1,
                    "required_certifications": [],
                    "closure_priority": 40,
                },
                PAYROLL_ANALYST,
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.create_shift_assignment(
                {
                    "duty_shift_id": world["shift"]["id"],
                    "firefighter_id": world["member"]["id"],
                    "apparatus_id": world["engine"]["id"],
                    "assignment_type": "REGULAR",
                    "seat_certification": "NONE",
                    "scheduled_hours": 24,
                    "expected_duty_shift_version": world["shift"]["version"],
                },
                STAFFING_OFFICER,
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )

        _, meta = validate_paginated(
            api.list_apparatus(STAFFING_OFFICER, station_id=world["station"]["id"])
        )
        assert meta["total_count"] == 1
        after = fx.read_shift(api, world["shift"]["id"])
        assert after["assigned_headcount"] == 0
        assert after["version"] == world["shift"]["version"]

    def test_leave_close_out_and_hiring_are_each_refused_to_the_wrong_role(self, api):
        """PRD 2.1: the `CompanyOfficer` "adjudicates the leave queue" but the
        `Firefighter` owns "their own leave requests"; the `StaffingOfficer`
        "may not ... close out a shift for payroll"; and the `PayrollAnalyst`
        and line member alike hold no hiring authority - the endpoint table
        reserves `POST /fire-ops/leave-requests` to `Firefighter`, `POST
        /fire-ops/duty-shifts/{duty_shift_id}/complete` to `PayrollAnalyst` and
        `POST /fire-ops/vacancies/{vacancy_id}/offer` to `StaffingOfficer`.

        Design: Corner/rbac/each_exclusive_operation_is_forbidden_to_the_other_roles
        """
        world = _station_with_a_published_shift_and_an_open_vacancy(api)

        validate_error(
            api.create_leave_request(
                {
                    "firefighter_id": world["member"]["id"],
                    "duty_shift_id": world["shift"]["id"],
                    "leave_type": "VACATION",
                    "requested_hours": 24,
                },
                fx.make_company_officer_headers(world["officer"]["id"]),
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.complete_duty_shift(world["shift"]["id"], STAFFING_OFFICER),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.offer_vacancy(
                world["vacancy"]["id"],
                {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
                fx.make_firefighter_headers(world["member"]["id"]),
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )

        _, meta = validate_paginated(
            api.list_leave_requests(STAFFING_OFFICER, duty_shift_id=world["shift"]["id"])
        )
        assert meta["total_count"] == 0
        assert fx.read_vacancy(api, world["vacancy"]["id"])["status"] == "OPEN"
        after = fx.read_shift(api, world["shift"]["id"])
        assert after["status"] == "HIRING"
        assert after["version"] == world["shift"]["version"]


# ---------------------------------------------------------------------------
# The two analytics reads are shared by the two office roles only
# ---------------------------------------------------------------------------
def _station_with_one_open_vacancy_and_one_member(api):
    station = fx.create_station(
        api,
        name="Station 128",
        battalion_code="G3",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-128",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="M Mercer",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    return {"station": station, "member": member, "shift": shift}


class TestAnalyticsReadAuthorisation:
    def test_the_forecast_and_the_hiring_signal_answer_both_office_roles(self, api):
        """The endpoint table authorises both computed reads for
        `StaffingOfficer, PayrollAnalyst`.  PRD 3.10 fixes the numbers: the
        forecast pool is the station's one member so `avg_rate_cents` is 4000
        and `shift_base_cents` is "`avg_rate_cents` multiplied by a
        twenty-four-hour tour and by the voluntary time-and-a-half multiplier",
        144000, carried by the single in-horizon `OPEN` vacancy with
        `required_certification` `NONE`.  For the signal, "`raw_need` is
        `open_vacancy_seats` plus twice `injury_headcount`" and
        "`recommended_recruit_count` converts that need into bodies by dividing
        by the four-platoon coverage factor and **rounding up** to a whole
        recruit - one position must be covered on every platoon, and a raw need
        of one already recommends one recruit", banded as "anything from one
        through eight inclusive is `MONITOR`".

        Design: Corner/rbac/analytics_reads_are_shared_by_officer_and_analyst_and_forbidden_to_line_roles
        """
        world = _station_with_one_open_vacancy_and_one_member(api)

        forecast = validate_success(
            api.get_overtime_forecast(world["station"]["id"], STAFFING_OFFICER), 200
        )
        assert forecast["horizon_vacancy_count"] == 1
        assert forecast["forecast_cents"] == 144_000

        signal = validate_success(
            api.get_academy_hiring_signal(world["station"]["id"], PAYROLL_ANALYST), 200
        )
        assert signal["open_vacancy_seats"] == 1
        assert signal["injury_headcount"] == 0
        assert signal["raw_need"] == 1
        assert signal["recommended_recruit_count"] == 1
        assert signal["signal_tier"] == "MONITOR"

    def test_the_line_roles_are_refused_the_analytics_but_keep_the_shift_read(
        self, api
    ):
        """The endpoint table authorises the two station analytics for
        `StaffingOfficer, PayrollAnalyst` alone, while `GET
        /fire-ops/duty-shifts/{duty_shift_id}` is open to "All roles"; PRD 2.1
        adds that a request "whose role is one of the four but is not among the
        roles authorised for the endpoint being called is rejected with
        `ERR_FORBIDDEN_ROLE` (403)".  The denial is therefore specific to the
        analytics reads and not a general read restriction on line members.

        Design: Corner/rbac/analytics_reads_are_shared_by_officer_and_analyst_and_forbidden_to_line_roles
        """
        world = _station_with_one_open_vacancy_and_one_member(api)
        member_id = world["member"]["id"]

        validate_error(
            api.get_overtime_forecast(
                world["station"]["id"], fx.make_company_officer_headers(member_id)
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )
        validate_error(
            api.get_academy_hiring_signal(
                world["station"]["id"], fx.make_firefighter_headers(member_id)
            ),
            ApiErrorId.FORBIDDEN_ROLE.value,
            403,
        )

        readable = validate_success(
            api.get_duty_shift(
                world["shift"]["id"], fx.make_firefighter_headers(member_id)
            ),
            200,
        )
        assert readable["id"] == world["shift"]["id"]


# ---------------------------------------------------------------------------
# Segregation of duties on a trade decision
# ---------------------------------------------------------------------------
def _countersigned_trade_with_an_uninvolved_officer(api):
    station = fx.create_station(
        api,
        name="Station 129",
        battalion_code="G3",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-129",
        apparatus_type="ENGINE",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    giver = fx.create_firefighter(
        api,
        station["id"],
        full_name="N Nyland",
        rank="FIREFIGHTER",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    taker = fx.create_firefighter(
        api,
        station["id"],
        full_name="O Oakes",
        rank="LIEUTENANT",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4500,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="P Paulk",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], shift_date="2026-08-11", platoon="C")
    seat = fx.seat_member(
        api,
        shift["id"],
        giver["id"],
        engine["id"],
        officer["id"],
        expected_duty_shift_version=shift["version"],
    )
    trade = fx.propose_trade(api, giver["id"], taker["id"], shift["id"])
    fx.countersign_trade(api, trade["id"], taker["id"])
    return {
        "giver": giver,
        "taker": taker,
        "officer": officer,
        "shift": shift,
        "seat": seat,
        "trade": trade,
    }


class TestTradeDecisionSegregationOfDuties:
    def test_neither_party_to_the_trade_may_decide_it(self, api):
        """PRD 2.2: "an officer whose `X-User-ID` equals either the
        `requesting_firefighter_id` or the `counterparty_firefighter_id` of the
        trade they are deciding is rejected with `ERR_SEGREGATION_OF_DUTIES`
        (403)".  PRD 2.6 ranks it sixth: "**Segregation of duties on a trade
        decision** - `ERR_SEGREGATION_OF_DUTIES` (403). An officer who is a
        party to the trade cannot decide it, even when the trade is properly
        countersigned and the role header is valid."  Both callers below carry
        the authorised `CompanyOfficer` role, so only identity can explain the
        refusal, and the trade stays undecided.

        Design: Corner/rbac/trade_decision_by_either_party_violates_segregation_of_duties
        """
        world = _countersigned_trade_with_an_uninvolved_officer(api)
        trade_id = world["trade"]["id"]

        validate_error(
            api.decide_trade_request(
                trade_id,
                {"decision": "APPROVE"},
                fx.make_company_officer_headers(world["giver"]["id"]),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )
        validate_error(
            api.decide_trade_request(
                trade_id,
                {"decision": "APPROVE"},
                fx.make_company_officer_headers(world["taker"]["id"]),
            ),
            ApiErrorId.SEGREGATION_OF_DUTIES.value,
            403,
        )

        after = fx.read_trade(api, trade_id)
        assert after["status"] == "COUNTERSIGNED"
        assert after["decided_by_user_id"] is None
        assert after["traded_assignment_id"] is None

    def test_an_uninvolved_officer_rejects_the_same_trade_and_moves_no_seat(self, api):
        """PRD 3.8: "The decision is taken by a `CompanyOfficer` who is neither
        party ... All three decisions record the officer's `X-User-ID` in
        `decided_by_user_id`", and "A decision of `REJECT` moves the trade
        `COUNTERSIGNED -> REJECTED` and records `decided_by_user_id`. Nothing
        else changes - no seat, no ledger, no work period."  The captain is a
        party to neither side, so the identical call the two parties were
        refused now succeeds.

        Design: Corner/rbac/trade_decision_by_either_party_violates_segregation_of_duties
        """
        world = _countersigned_trade_with_an_uninvolved_officer(api)

        decided = validate_success(
            api.decide_trade_request(
                world["trade"]["id"],
                {"decision": "REJECT", "note": "crew balance on the ladder"},
                fx.make_company_officer_headers(world["officer"]["id"]),
            ),
            200,
        )
        assert decided["status"] == "REJECTED"
        assert decided["decided_by_user_id"] == world["officer"]["id"]
        assert decided["traded_assignment_id"] is None

        seat = fx.read_assignment(api, world["seat"]["id"])
        assert seat["firefighter_id"] == world["giver"]["id"]
        assert seat["assignment_type"] == "REGULAR"
        assert seat["status"] == "SCHEDULED"
