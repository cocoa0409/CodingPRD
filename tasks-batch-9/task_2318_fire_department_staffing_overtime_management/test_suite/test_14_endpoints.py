"""Endpoint surface: the apparatus registry, the three action endpoints that
rewrite staffing in place, and the pure computed read that plans the money.
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
# Apparatus registry: create, read, filtered list
# ---------------------------------------------------------------------------
def _station_with_an_engine_and_a_ladder(api):
    """Two companies of different types at one station, plus a reading officer."""
    station = fx.create_station(
        api,
        name="Station 117",
        battalion_code="F6",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = validate_success(
        api.create_apparatus(
            {
                "station_id": station["id"],
                "unit_designation": "ENGINE-117",
                "apparatus_type": "ENGINE",
                "minimum_crew_size": 3,
                "required_certifications": ["PARAMEDIC"],
                "closure_priority": 10,
            },
            STAFFING_OFFICER,
        ),
        201,
    )
    ladder = validate_success(
        api.create_apparatus(
            {
                "station_id": station["id"],
                "unit_designation": "LADDER-117",
                "apparatus_type": "LADDER",
                "minimum_crew_size": 4,
                "required_certifications": [],
                "closure_priority": 30,
            },
            STAFFING_OFFICER,
        ),
        201,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="T Traynor",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=5000,
    )
    return {
        "station": station,
        "engine": engine,
        "ladder": ladder,
        "officer": officer,
    }


class TestApparatusRegistry:
    """A registered company reads back as stored and lists behind its filters."""

    def test_a_registered_company_is_readable_by_id(self, api):
        """The read echoes every stored field and both defaults.

        PRD 3.1: "A unit may be marked `closure_exempt`, defaulting to false; a
        true value marks a first-due company that may never be taken out of
        service by a closure action. A unit's `status` is `IN_SERVICE` on
        registration and may otherwise read `OUT_OF_SERVICE`, in which case the
        unit stops contributing to the staffing requirement altogether."

        Design: Corner/endpoints/apparatus_crud_create_read_and_filtered_list
        """
        world = _station_with_an_engine_and_a_ladder(api)

        response = api.get_apparatus(
            world["engine"]["id"], fx.make_company_officer_headers(world["officer"]["id"])
        )
        company = validate_success(response, 200)

        assert company["id"] == world["engine"]["id"]
        assert company["station_id"] == world["station"]["id"]
        assert company["unit_designation"] == "ENGINE-117"
        assert company["apparatus_type"] == "ENGINE"
        assert company["minimum_crew_size"] == 3
        assert company["required_certifications"] == ["PARAMEDIC"]
        assert company["closure_priority"] == 10
        assert company["status"] == "IN_SERVICE"
        assert company["closure_exempt"] is False

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

    def test_the_company_list_narrows_to_the_station_and_type_filter(self, api):
        """The engine filter excludes the ladder and reports one row.

        PRD 2.3: "Every list response carries `limit`, `offset`, `total_count` and
        `has_more` inside the `meta` object of the envelope."

        Design: Corner/endpoints/apparatus_crud_create_read_and_filtered_list
        """
        world = _station_with_an_engine_and_a_ladder(api)

        response = api.list_apparatus(
            fx.make_company_officer_headers(world["officer"]["id"]),
            station_id=world["station"]["id"],
            apparatus_type="ENGINE",
        )
        rows, meta = validate_paginated(response)

        assert response.json()["response_type"] == "array"
        assert meta["total_count"] == 1
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0

        assert [row["id"] for row in rows] == [world["engine"]["id"]]
        assert world["ladder"]["id"] not in {row["id"] for row in rows}


# ---------------------------------------------------------------------------
# Trade approval: the seat is rewritten in place
# ---------------------------------------------------------------------------
def _countersigned_trade_on_a_single_seat_shift(api):
    """One seated giver, one idle taker, and an uninvolved deciding officer."""
    station = fx.create_station(
        api,
        name="Station 118",
        battalion_code="F6",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-118",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    giver = fx.create_firefighter(
        api,
        station["id"],
        full_name="U Udall",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    taker = fx.create_firefighter(
        api,
        station["id"],
        full_name="V Voss",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="W Wolfe",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    seat = fx.seat_member(api, shift["id"], giver["id"], engine["id"], officer["id"])

    trade = fx.propose_trade(api, giver["id"], taker["id"], shift["id"])
    fx.countersign_trade(api, trade["id"], taker["id"])

    return {
        "station": station,
        "giver": giver,
        "taker": taker,
        "officer": officer,
        "shift": shift,
        "seat": seat,
        "trade": trade,
        "giver_period": fx.work_period_of(api, giver["id"]),
        "taker_period": fx.work_period_of(api, taker["id"]),
    }


class TestTradeApproval:
    """Approval re-badges the existing seat rather than minting a new one."""

    def test_approval_hands_the_same_seat_to_the_counterparty(self, api):
        """The seat keeps its id and changes occupant and type.

        PRD 3.5: "On approval the trade's `traded_assignment_id` is set to that
        seat, the seat's `firefighter_id` becomes the counterparty and its
        `assignment_type` becomes `TRADE`."

        Design: Corner/endpoints/trade_approval_transfers_the_seat_and_moves_the_hours_between_members
        """
        world = _countersigned_trade_on_a_single_seat_shift(api)

        decided = fx.decide_trade(
            api,
            world["trade"]["id"],
            world["officer"]["id"],
            "APPROVE",
            note="even swap, both qualified",
        )

        assert decided["status"] == "APPROVED"
        assert decided["traded_assignment_id"] == world["seat"]["id"]
        assert decided["decided_by_user_id"] == world["officer"]["id"]
        assert decided["revision_count"] == 0

        seat = fx.read_assignment(api, world["seat"]["id"])
        assert seat["firefighter_id"] == world["taker"]["id"]
        assert seat["assignment_type"] == "TRADE"
        assert seat["status"] == "SCHEDULED"
        assert seat["scheduled_hours"] == 24
        assert seat["projected_premium_cents"] == 0

    def test_approval_moves_the_hours_across_and_leaves_the_headcount_alone(self, api):
        """Twenty-four hours leave one period and arrive in the other.

        PRD 3.5: "The requester's covering work period loses the seat's
        `scheduled_hours` and is re-priced; the counterparty's covering work period
        gains the same hours and is re-priced."

        Design: Corner/endpoints/trade_approval_transfers_the_seat_and_moves_the_hours_between_members
        """
        world = _countersigned_trade_on_a_single_seat_shift(api)
        assert fx.read_work_period(api, world["giver_period"]["id"])["scheduled_hours"] == 24

        fx.decide_trade(
            api,
            world["trade"]["id"],
            world["officer"]["id"],
            "APPROVE",
            note="even swap, both qualified",
        )

        giver_period = fx.read_work_period(api, world["giver_period"]["id"])
        assert giver_period["scheduled_hours"] == 0
        assert giver_period["flsa_premium_cents"] == 0

        taker_period = fx.read_work_period(api, world["taker_period"]["id"])
        assert taker_period["scheduled_hours"] == 24
        assert taker_period["flsa_premium_cents"] == 0

        shift = fx.read_shift(api, world["shift"]["id"])
        # One body simply replaced another.
        assert shift["assigned_headcount"] == 1
        assert shift["staffing_gap"] == 0
        assert shift["certification_gap_count"] == 0
        assert shift["status"] == "STAFFED"
        assert shift["staffing_posture"] == "FULLY_STAFFED"

        # A trade is cost-neutral.
        assert fx.read_station(api, world["station"]["id"])["ot_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Leave adjudication: a batch with a mixed outcome
# ---------------------------------------------------------------------------
class TestLeaveAdjudicationBatch:
    """A denial inside the batch does not undo the approval that preceded it."""

    def test_one_batch_approves_the_senior_and_denies_the_junior(self, api):
        """The summary reports both outcomes and the approval already stands.

        PRD 3.4: "The adjudication response summarises the batch rather than
        returning a shift: it reports the `duty_shift_id` adjudicated, the
        `leave_floor_headcount` the batch was measured against, a
        `considered_count` of requests walked, `approved_count` and
        `denied_count`, the `approved_leave_request_ids` and
        `denied_leave_request_ids` in decision order, the
        `resulting_assigned_headcount` and `resulting_staffing_posture`, and the
        `created_vacancy_count`."

        Design: Corner/endpoints/leave_adjudication_batch_returns_per_request_outcomes_without_rolling_back
        """
        station = fx.create_station(
            api,
            name="Station 119",
            battalion_code="F7",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-119",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        senior = fx.create_firefighter(
            api,
            station["id"],
            full_name="X Xenos",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        junior = fx.create_firefighter(
            api,
            station["id"],
            full_name="Y Yost",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="Z Zink",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=3,
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
        senior_leave = fx.file_leave(api, senior["id"], shift["id"], "VACATION", 24)
        junior_leave = fx.file_leave(api, junior["id"], shift["id"], "VACATION", 24)

        summary = fx.adjudicate_leave(api, shift["id"], officer["id"])

        assert summary["duty_shift_id"] == shift["id"]
        # The larger of the contractual floor of one and required staffing less
        # the negotiated slack of two bodies.
        assert summary["leave_floor_headcount"] == 1
        assert summary["considered_count"] == 2
        assert summary["approved_count"] == 1
        assert summary["denied_count"] == 1
        assert summary["approved_leave_request_ids"] == [senior_leave["id"]]
        assert summary["denied_leave_request_ids"] == [junior_leave["id"]]
        assert summary["resulting_assigned_headcount"] == 1
        assert summary["resulting_staffing_posture"] == "SHORT"
        assert summary["created_vacancy_count"] == 1

        approved = fx.read_leave(api, senior_leave["id"])
        assert approved["status"] == "APPROVED"
        assert approved["decision_order_index"] == 1
        assert approved["denial_reason"] is None

        denied = fx.read_leave(api, junior_leave["id"])
        assert denied["status"] == "DENIED"
        assert denied["decision_order_index"] == 2
        assert denied["denial_reason"] == "STAFFING_FLOOR"

        # The second item's failure did not roll the first one back.
        assert fx.read_assignment(api, senior_seat["id"])["status"] == "RELIEVED"
        assert fx.read_assignment(api, junior_seat["id"])["status"] == "SCHEDULED"


# ---------------------------------------------------------------------------
# Offer acceptance: the seat links both ways
# ---------------------------------------------------------------------------
class TestOfferAcceptanceCrossReferences:
    """The forward and reverse links between offer, seat and vacancy agree."""

    def test_the_seat_is_reachable_from_the_offer_and_from_the_vacancy(self, api):
        """One hire, two directions of reference, one row.

        PRD 3.7: "**Hop one:** a shift assignment is created in `SCHEDULED` status
        with `assignment_type` `OVERTIME` for a voluntary offer or `CALLBACK` for a
        callback offer, `source_offer_id` pointing at the offer, `scheduled_hours`
        equal to the offer's payable `offer_hours`, and `projected_premium_cents`
        set equal to the offer's `projected_cost_cents`; the vacancy's
        `filled_by_assignment_id` is set to that seat."

        Design: Corner/endpoints/offer_acceptance_links_the_seat_to_both_the_offer_and_the_vacancy
        """
        station = fx.create_station(
            api,
            name="Station 120",
            battalion_code="F7",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-120",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="A Amory",
            platoon="D",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
        offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)

        accepted = fx.answer_offer(api, offer["id"], member["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"

        rows, meta = validate_paginated(
            api.list_shift_assignments(STAFFING_OFFICER, source_offer_id=offer["id"])
        )
        assert meta["total_count"] == 1
        seat = rows[0]
        assert seat["firefighter_id"] == member["id"]
        assert seat["source_offer_id"] == offer["id"]
        assert seat["assignment_type"] == "OVERTIME"
        assert seat["status"] == "SCHEDULED"
        # 4000 cents at time and a half over twenty-four hours.
        assert seat["projected_premium_cents"] == 144_000

        filled = fx.read_vacancy(api, vacancy["id"])
        assert filled["status"] == "FILLED"
        assert filled["filled_by_assignment_id"] == seat["id"]

        after = fx.read_shift(api, shift["id"])
        assert after["status"] == "STAFFED"
        assert after["open_vacancy_count"] == 0
        assert after["assigned_headcount"] == 1

        hired = fx.read_firefighter(api, member["id"])
        assert hired["voluntary_ot_hours_charged"] == 24
        assert hired["ot_pass_count"] == 0
        assert hired["pending_offer_count"] == 0


# ---------------------------------------------------------------------------
# The overtime forecast: a pure computed read
# ---------------------------------------------------------------------------
def _station_with_one_open_and_one_offering_vacancy(api):
    """Two seats on one tour, one of which already carries a live offer."""
    station = fx.create_station(
        api,
        name="Station 121",
        battalion_code="F8",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-121",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="B Bosch",
        platoon="D",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
    shift = fx.published_shift(api, station["id"], "2026-08-12", "D")
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
    offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)

    return {"station": station, "member": member, "shift": shift, "offer": offer}


class TestOvertimeForecastComputedRead:
    """The horizon counts offered seats and the tail adds the encumbrance once."""

    def test_the_horizon_counts_the_offering_seat_alongside_the_open_one(self, api):
        """Two horizon seats project 288000 on top of 144000 already committed.

        PRD 3.9: "Its horizon is every vacancy at the station in `OPEN` or
        `OFFERING` status whose shift date is on or after the current date and on
        or before the station's `fiscal_period_end_date`; the count of those is
        reported as `horizon_vacancy_count`."

        Design: Corner/endpoints/computed_read_forecast_adds_the_committed_encumbrance_to_the_open_seat_projection
        """
        world = _station_with_one_open_and_one_offering_vacancy(api)

        forecast = validate_success(
            api.get_overtime_forecast(world["station"]["id"], PAYROLL_ANALYST), 200
        )

        # The variant defaults when the parameter is omitted.
        assert forecast["method"] == "VACANCY_DRIVEN"
        assert forecast["station_id"] == world["station"]["id"]
        assert forecast["avg_rate_cents"] == 4000
        assert forecast["shift_base_cents"] == 144_000
        assert forecast["horizon_vacancy_count"] == 2
        assert forecast["vacancy_driver_cents"] == 288_000
        assert forecast["injury_headcount"] == 0
        assert forecast["injury_driver_cents"] == 0
        assert forecast["forecast_cents"] == 288_000
        # Zero realised, 144000 encumbered, 288000 forecast.
        assert forecast["projected_period_total_cents"] == 432_000
        assert forecast["variance_cents"] == 68_000
        assert forecast["forecast_posture"] == "WITHIN"
        # Fields belonging to the method that was not selected.
        assert forecast["daily_run_rate_cents"] == 0
        assert forecast["remaining_days"] == 0

    def test_reading_the_forecast_persists_nothing(self, api):
        """The projection leaves the ledger and the live offer exactly as they were.

        PRD 3.9: "Two computed reads turn all of this into planning material, and
        both are pure: they persist nothing."

        Design: Corner/endpoints/computed_read_forecast_adds_the_committed_encumbrance_to_the_open_seat_projection
        """
        world = _station_with_one_open_and_one_offering_vacancy(api)
        before = fx.read_station(api, world["station"]["id"])
        assert before["ot_committed_cents"] == 144_000

        validate_success(
            api.get_overtime_forecast(world["station"]["id"], PAYROLL_ANALYST), 200
        )

        after = fx.read_station(api, world["station"]["id"])
        assert after["ot_committed_cents"] == 144_000
        assert after["version"] == before["version"]
        assert fx.read_offer(api, world["offer"]["id"])["status"] == "OFFERED"


# ---------------------------------------------------------------------------
# Hiring is gated on the vacancy still being biddable
# ---------------------------------------------------------------------------
class TestOfferRequiresABiddableVacancy:
    """Neither an already-offered seat nor a closed company's seat may be hired."""

    def test_a_vacancy_already_out_for_offer_cannot_be_offered_again(self, api):
        """The status gate is decided before the candidate pool is built.

        PRD 3.6: "It is admissible only against a vacancy in `OPEN` status, and
        only when the vacancy's company is not among the shift's
        `closed_apparatus_ids` — either failure is `ERR_VACANCY_NOT_OFFERABLE` —
        on a shift in `HIRING` or `STAFFED`, else `ERR_SHIFT_NOT_HIRING`."

        Design: Corner/endpoints/conditional_action_offer_requires_an_open_and_unclosed_vacancy
        """
        station = fx.create_station(
            api,
            name="Station 122",
            battalion_code="F8",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-122",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="C Coyle",
            platoon="D",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
        offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)
        assert fx.read_vacancy(api, vacancy["id"])["status"] == "OFFERING"

        response = api.offer_vacancy(
            vacancy["id"],
            {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
            STAFFING_OFFICER,
        )

        validate_error(response, ApiErrorId.VACANCY_NOT_OFFERABLE.value, 409)

        assert fx.read_offer(api, offer["id"])["status"] == "OFFERED"
        # One encumbrance, not two.
        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 144_000
        assert fx.read_firefighter(api, member["id"])["pending_offer_count"] == 1

    def test_a_vacancy_on_a_closed_company_cannot_be_offered(self, api):
        """A seat taken out of service with its company is no longer biddable.

        PRD 3.8: "**Hop two**, caused by hop one: every vacancy on this shift
        belonging to the closed company and sitting in `OPEN` or `OFFERING` moves
        to `CLOSED_BY_COMPANY_CLOSURE`."

        Design: Corner/endpoints/conditional_action_offer_requires_an_open_and_unclosed_vacancy
        """
        station = fx.create_station(
            api,
            name="Station 123",
            battalion_code="F8",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-123",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        truck = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="TRUCK-123",
            apparatus_type="LADDER",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=30,
        )
        fx.create_firefighter(
            api,
            station["id"],
            full_name="D Dozier",
            platoon="D",
            seniority_rank=2,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        assert shift["staffing_posture"] == "CRITICAL"

        closed_shift = fx.close_company(
            api,
            shift["id"],
            justification="no crew for the ladder",
            expected_duty_shift_version=shift["version"],
        )
        # The highest closure priority closes first.
        assert closed_shift["closed_apparatus_ids"] == [truck["id"]]
        assert closed_shift["required_staffing"] == 2

        closed_vacancy = fx.first_vacancy(
            api,
            duty_shift_id=shift["id"],
            apparatus_id=truck["id"],
            status="CLOSED_BY_COMPANY_CLOSURE",
        )

        response = api.offer_vacancy(
            closed_vacancy["id"],
            {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
            STAFFING_OFFICER,
        )

        validate_error(response, ApiErrorId.VACANCY_NOT_OFFERABLE.value, 409)

        assert (
            fx.read_vacancy(api, closed_vacancy["id"])["status"]
            == "CLOSED_BY_COMPANY_CLOSURE"
        )
        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 0

        _, meta = validate_paginated(
            api.list_overtime_offers(
                STAFFING_OFFICER, vacancy_id=closed_vacancy["id"]
            )
        )
        assert meta["total_count"] == 0
