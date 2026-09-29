"""Operations refused because of the state of a different record: a backfill that
has already been hired into, and a counterparty who has gone out on injury.
"""

from test_helpers import ApiErrorId, fixtures as fx
from test_helpers import validate_error


# ---------------------------------------------------------------------------
# Revocation blocked by a filled backfill
# ---------------------------------------------------------------------------
def _approved_leave_whose_backfill_has_been_hired(api):
    """An approved vacation whose hole has already been filled by overtime."""
    station = fx.create_station(
        api,
        name="Station 54",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-54",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    leaver = fx.create_firefighter(
        api,
        station["id"],
        full_name="B Belanger",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4237,
    )
    stayer = fx.create_firefighter(
        api,
        station["id"],
        full_name="C Chandra",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    taker = fx.create_firefighter(
        api,
        station["id"],
        full_name="D Dlamini",
        platoon="C",
        seniority_rank=3,
        kelly_day_cycle_position=4,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="E Ekwueme",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")

    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    leaver_seat = fx.seat_member(api, shift["id"], leaver["id"], engine["id"], officer["id"])
    fx.seat_member(api, shift["id"], stayer["id"], engine["id"], officer["id"])

    backfilled = fx.approved_leave_with_backfill(
        api, shift["id"], leaver["id"], officer["id"], "VACATION", 24
    )
    hired = fx.hire_into_vacancy(
        api, backfilled["vacancy"]["id"], taker["id"], "VOLUNTARY", 24
    )

    return {
        "station": station,
        "leaver": leaver,
        "taker": taker,
        "officer": officer,
        "shift": shift,
        "leaver_seat": leaver_seat,
        "leave": backfilled["leave"],
        "vacancy": backfilled["vacancy"],
        "offer": hired["offer"],
    }


class TestRevocationBlockedByFilledBackfill:
    """The backfill's state, not the leave's own state, is the decisive guard."""

    def test_revoking_leave_whose_hole_was_filled_is_refused(self, api):
        """A backfill that reached FILLED blocks the revocation outright.

        PRD 3.4: "The decisive guard is the backfill: if the vacancy the approval
        created has already reached `FILLED`, somebody has already been hired
        into the hole and the revocation is refused with
        `ERR_LEAVE_ALREADY_BACKFILLED`."

        Design: Difficulty/cross_entity_state_dependency/leave_revoke_blocked_by_filled_backfill_vacancy
        """
        world = _approved_leave_whose_backfill_has_been_hired(api)

        response = api.revoke_leave_request(
            world["leave"]["id"], fx.make_firefighter_headers(world["leaver"]["id"])
        )

        validate_error(response, ApiErrorId.LEAVE_ALREADY_BACKFILLED.value, 422)

    def test_the_refused_revocation_unwinds_nothing(self, api):
        """None of the four revocation hops fires when the guard refuses.

        PRD 2.6: "No side effect of any lower-precedence rule is applied, and a
        request that fails any check writes nothing at all."

        Design: Difficulty/cross_entity_state_dependency/leave_revoke_blocked_by_filled_backfill_vacancy
        """
        world = _approved_leave_whose_backfill_has_been_hired(api)

        api.revoke_leave_request(
            world["leave"]["id"], fx.make_firefighter_headers(world["leaver"]["id"])
        )

        leave = fx.read_leave(api, world["leave"]["id"])
        assert leave["status"] == "APPROVED"
        assert leave["backfill_vacancy_id"] == world["vacancy"]["id"]

        vacancy = fx.read_vacancy(api, world["vacancy"]["id"])
        assert vacancy["status"] == "FILLED"

        seat = fx.read_assignment(api, world["leaver_seat"]["id"])
        assert seat["status"] == "RELIEVED"
        assert seat["relieved_by_leave_request_id"] == leave["id"]

        offer = fx.read_offer(api, world["offer"]["id"])
        assert offer["status"] == "ACCEPTED"
        assert offer["projected_cost_cents"] == 144000

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 144000

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "STAFFED"
        assert shift["assigned_headcount"] == 2
        assert shift["open_vacancy_count"] == 0


# ---------------------------------------------------------------------------
# Countersignature blocked by the counterparty's employment status
# ---------------------------------------------------------------------------
def _proposed_trade_whose_counterparty_went_on_injury_leave(api):
    """A live proposal whose taker has since been moved to injury leave."""
    station = fx.create_station(
        api,
        name="Station 55",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-55",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    giver = fx.create_firefighter(
        api,
        station["id"],
        full_name="F Fontaine",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    taker = fx.create_firefighter(
        api,
        station["id"],
        full_name="G Gruber",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="H Halvorsen",
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

    fx.set_availability(
        api,
        taker["id"],
        effective_date="2026-08-05",
        employment_status="INJURY_LEAVE",
        roster_standing="UNAVAILABLE",
        expected_firefighter_version=taker["version"],
    )

    return {
        "station": station,
        "giver": giver,
        "taker": taker,
        "officer": officer,
        "shift": shift,
        "seat": seat,
        "trade": trade,
    }


class TestCountersignatureBlockedByInjuryLeave:
    """Vetting reads the counterparty's own record, not the trade's."""

    def test_countersigning_while_not_active_is_refused(self, api):
        """The counterparty's employment status is vetted at countersignature.

        PRD 3.5: "The counterparty's `employment_status` must be `ACTIVE`, else
        `ERR_STATION_SCOPE_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/trade_countersign_blocked_by_counterparty_injury_leave
        """
        world = _proposed_trade_whose_counterparty_went_on_injury_leave(api)

        taker = fx.read_firefighter(api, world["taker"]["id"])
        assert taker["employment_status"] == "INJURY_LEAVE"
        assert taker["roster_standing"] == "UNAVAILABLE"

        response = api.countersign_trade_request(
            world["trade"]["id"], fx.make_firefighter_headers(world["taker"]["id"])
        )

        validate_error(response, ApiErrorId.STATION_SCOPE_MISMATCH.value, 422)

    def test_the_refused_countersignature_leaves_the_trade_and_seat_untouched(self, api):
        """A refused countersignature moves neither the trade nor the seat.

        PRD 3.5: "It is created in `PROPOSED` with `revision_count` at zero,
        `traded_assignment_id` null, `decided_by_user_id` null, and no staffing
        consequence whatsoever."

        Design: Difficulty/cross_entity_state_dependency/trade_countersign_blocked_by_counterparty_injury_leave
        """
        world = _proposed_trade_whose_counterparty_went_on_injury_leave(api)

        api.countersign_trade_request(
            world["trade"]["id"], fx.make_firefighter_headers(world["taker"]["id"])
        )

        trade = fx.read_trade(api, world["trade"]["id"])
        assert trade["status"] == "PROPOSED"
        assert trade["revision_count"] == 0
        assert trade["traded_assignment_id"] is None
        assert trade["decided_by_user_id"] is None

        seat = fx.read_assignment(api, world["seat"]["id"])
        assert seat["firefighter_id"] == world["giver"]["id"]
        assert seat["assignment_type"] == "REGULAR"
        assert seat["status"] == "SCHEDULED"
