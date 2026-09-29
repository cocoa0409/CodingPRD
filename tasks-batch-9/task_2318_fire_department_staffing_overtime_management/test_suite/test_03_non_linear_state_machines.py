"""Cycles rather than ladders: the trade revision loop and the offer/decline loop
that walks a vacancy down the hiring order.
"""

from test_helpers import STAFFING_OFFICER, fixtures as fx
from test_helpers import validate_success


# ---------------------------------------------------------------------------
# Trade revision cycle
# ---------------------------------------------------------------------------
def _trade_returned_for_revision_once(api):
    """A countersigned trade that an officer has already sent back once."""
    station = fx.create_station(
        api,
        name="Station 45",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-45",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    giver = fx.create_firefighter(
        api,
        station["id"],
        full_name="L Larkin",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    taker = fx.create_firefighter(
        api,
        station["id"],
        full_name="M Mbeki",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="N Nagel",
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
    fx.decide_trade(api, trade["id"], officer["id"], "RETURN_FOR_REVISION")

    return {
        "station": station,
        "engine": engine,
        "giver": giver,
        "taker": taker,
        "officer": officer,
        "shift": shift,
        "seat": seat,
        "trade": fx.read_trade(api, trade["id"]),
    }


class TestTradeRevisionCycle:
    """A returned trade re-enters PROPOSED and can be returned again."""

    def test_second_return_for_revision_increments_the_counter_again(self, api):
        """Each return sends the trade back to PROPOSED and bumps the counter.

        PRD 3.5: "A decision of `RETURN_FOR_REVISION` moves the trade
        `COUNTERSIGNED → PROPOSED`, increments its `revision_count` by one, and
        records `decided_by_user_id`. The counterparty must countersign again
        before another decision is possible. This loop may repeat without bound,
        incrementing `revision_count` each time round."

        Design: Difficulty/non_linear_state_machine/trade_request_revision_cycle_increments_revision_count_twice
        """
        world = _trade_returned_for_revision_once(api)
        assert world["trade"]["status"] == "PROPOSED"
        assert world["trade"]["revision_count"] == 1

        recountersigned = validate_success(
            api.countersign_trade_request(
                world["trade"]["id"],
                fx.make_firefighter_headers(world["taker"]["id"]),
            ),
            200,
        )
        assert recountersigned["status"] == "COUNTERSIGNED"
        assert recountersigned["revision_count"] == 1

        returned_again = validate_success(
            api.decide_trade_request(
                world["trade"]["id"],
                {"decision": "RETURN_FOR_REVISION"},
                fx.make_company_officer_headers(world["officer"]["id"]),
            ),
            200,
        )
        assert returned_again["status"] == "PROPOSED"
        assert returned_again["revision_count"] == 2
        assert returned_again["decided_by_user_id"] == world["officer"]["id"]

    def test_the_revision_loop_moves_no_seat_and_no_staffing_field(self, api):
        """Countersigning and returning change nothing but the trade itself.

        PRD 3.5: "A successful countersignature moves the trade `PROPOSED →
        COUNTERSIGNED` and changes nothing else: no staffing field, no ledger
        entry, no work-period hour moves, because a trade is still only a
        proposal until an officer decides it."

        Design: Difficulty/non_linear_state_machine/trade_request_revision_cycle_increments_revision_count_twice
        """
        world = _trade_returned_for_revision_once(api)

        fx.countersign_trade(api, world["trade"]["id"], world["taker"]["id"])
        fx.decide_trade(api, world["trade"]["id"], world["officer"]["id"], "RETURN_FOR_REVISION")

        trade = fx.read_trade(api, world["trade"]["id"])
        assert trade["traded_assignment_id"] is None

        seat = fx.read_assignment(api, world["seat"]["id"])
        assert seat["firefighter_id"] == world["giver"]["id"]
        assert seat["assignment_type"] == "REGULAR"
        assert seat["status"] == "SCHEDULED"
        assert seat["projected_premium_cents"] == 0

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["assigned_headcount"] == 1

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Vacancy OFFERING -> OPEN -> OFFERING cycle
# ---------------------------------------------------------------------------
def _vacancy_declined_by_the_most_senior_member(api):
    """A single open seat whose first offer has already been declined."""
    station = fx.create_station(
        api,
        name="Station 46",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-46",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    first = fx.create_firefighter(
        api,
        station["id"],
        full_name="O Ortega",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    second = fx.create_firefighter(
        api,
        station["id"],
        full_name="P Petrov",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")

    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")

    first_offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)
    assert first_offer["firefighter_id"] == first["id"]
    fx.answer_offer(api, first_offer["id"], first["id"], "DECLINE")

    return {
        "station": station,
        "engine": engine,
        "first": first,
        "second": second,
        "shift": shift,
        "vacancy": vacancy,
        "first_offer": first_offer,
    }


class TestVacancyReofferCycle:
    """Declining returns the vacancy to OPEN so the next member can be asked."""

    def test_decline_returns_the_vacancy_to_open_and_charges_the_pass(self, api):
        """A pass is charged as though the hours had been worked.

        PRD 3.7: "The labor agreement, however, charges the pass: the member's
        `voluntary_ot_hours_charged` increases by the offer's payable
        `offer_hours` **exactly as if the hours had been worked**, their
        `ot_pass_count` increases by one, and their `pending_offer_count`
        decreases by one."

        Design: Difficulty/non_linear_state_machine/vacancy_offering_open_cycle_reoffers_to_next_member_in_order
        """
        world = _vacancy_declined_by_the_most_senior_member(api)

        offer = fx.read_offer(api, world["first_offer"]["id"])
        assert offer["status"] == "DECLINED"
        assert offer["projected_cost_cents"] == 144000

        passer = fx.read_firefighter(api, world["first"]["id"])
        assert passer["voluntary_ot_hours_charged"] == 24
        assert passer["ot_pass_count"] == 1
        assert passer["pending_offer_count"] == 0
        assert passer["roster_standing"] == "AVAILABLE"

        vacancy = fx.read_vacancy(api, world["vacancy"]["id"])
        assert vacancy["status"] == "OPEN"
        assert vacancy["filled_by_assignment_id"] is None

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0

    def test_reoffer_walks_down_to_the_next_member_who_then_fills_the_seat(self, api):
        """The charged pass pushes the passer behind the untouched member.

        PRD 3.6: "They are ranked by `voluntary_ot_hours_charged` ascending —
        the member who has been charged the fewest overtime hours is owed the
        next opportunity — then by `seniority_rank` ascending so the most senior
        of equals goes first, then by `created_at` ascending."

        Design: Difficulty/non_linear_state_machine/vacancy_offering_open_cycle_reoffers_to_next_member_in_order
        """
        world = _vacancy_declined_by_the_most_senior_member(api)

        second_offer = validate_success(
            api.offer_vacancy(
                world["vacancy"]["id"],
                {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
                STAFFING_OFFICER,
            ),
            201,
        )
        assert second_offer["firefighter_id"] == world["second"]["id"]
        assert second_offer["projected_cost_cents"] == 144000

        accepted = fx.answer_offer(api, second_offer["id"], world["second"]["id"], "ACCEPT")
        assert accepted["status"] == "ACCEPTED"

        vacancy = fx.read_vacancy(api, world["vacancy"]["id"])
        assert vacancy["status"] == "FILLED"
        assert vacancy["filled_by_assignment_id"] is not None

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "STAFFED"
        assert shift["open_vacancy_count"] == 0
        assert shift["assigned_headcount"] == 1

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 144000

        taker = fx.read_firefighter(api, world["second"]["id"])
        assert taker["voluntary_ot_hours_charged"] == 24
        assert taker["ot_pass_count"] == 0
        assert taker["pending_offer_count"] == 0
