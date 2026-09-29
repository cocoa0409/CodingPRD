"""Requests that break two rules at once, where the precedence order decides
which single error the client sees.
"""

from test_helpers import ApiErrorId, STAFFING_OFFICER, fixtures as fx
from test_helpers import validate_error


# ---------------------------------------------------------------------------
# Cross-entity coherence outranks rotation compatibility
# ---------------------------------------------------------------------------
def _two_stations_and_a_foreign_platoon_a_member(api):
    """A published platoon C shift at one station and a platoon A member at another."""
    home = fx.create_station(
        api,
        name="Station 49",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    away = fx.create_station(
        api,
        name="Station 50",
        battalion_code="C2",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        home["id"],
        unit_designation="ENGINE-49",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    officer = fx.create_firefighter(
        api,
        home["id"],
        full_name="U Ubaldi",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    outsider = fx.create_firefighter(
        api,
        away["id"],
        full_name="V Vargas",
        platoon="A",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    shift = fx.published_shift(api, home["id"], "2026-08-11", "C")
    return {
        "home": home,
        "away": away,
        "engine": engine,
        "officer": officer,
        "outsider": outsider,
        "shift": shift,
    }


class TestStationScopeOutranksPlatoonRotation:
    """A member from another station who is also on the wrong platoon reports scope."""

    def test_cross_station_seat_reports_scope_mismatch_not_rotation_violation(self, api):
        """The coherence band sits strictly above the rotation rules.

        PRD 2.6: "This band sits strictly above the temporal rules, so a member
        from another station seated on the wrong platoon returns
        `ERR_STATION_SCOPE_MISMATCH` rather than a rotation error."

        Design: Difficulty/priority_pair_validation_conflict/referential_scope_beats_temporal_rotation_on_cross_station_seat
        """
        world = _two_stations_and_a_foreign_platoon_a_member(api)

        response = api.create_shift_assignment(
            {
                "duty_shift_id": world["shift"]["id"],
                "firefighter_id": world["outsider"]["id"],
                "apparatus_id": world["engine"]["id"],
                "assignment_type": "REGULAR",
                "seat_certification": "NONE",
                "scheduled_hours": 24,
                "expected_duty_shift_version": world["shift"]["version"],
            },
            fx.make_company_officer_headers(world["officer"]["id"]),
        )

        error = validate_error(
            response, ApiErrorId.STATION_SCOPE_MISMATCH.value, 422
        )
        assert error["error_id"] != ApiErrorId.PLATOON_ROTATION_VIOLATION.value

    def test_the_refused_seat_writes_nothing_at_all(self, api):
        """A request that fails any check writes nothing at all.

        PRD 2.6: "No side effect of any lower-precedence rule is applied, and a
        request that fails any check writes nothing at all."

        Design: Difficulty/priority_pair_validation_conflict/referential_scope_beats_temporal_rotation_on_cross_station_seat
        """
        world = _two_stations_and_a_foreign_platoon_a_member(api)

        api.create_shift_assignment(
            {
                "duty_shift_id": world["shift"]["id"],
                "firefighter_id": world["outsider"]["id"],
                "apparatus_id": world["engine"]["id"],
                "assignment_type": "REGULAR",
                "seat_certification": "NONE",
                "scheduled_hours": 24,
                "expected_duty_shift_version": world["shift"]["version"],
            },
            fx.make_company_officer_headers(world["officer"]["id"]),
        )

        assert fx.list_assignments(api, duty_shift_id=world["shift"]["id"]) == []

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["assigned_headcount"] == 0
        assert shift["open_vacancy_count"] == 2
        assert shift["version"] == world["shift"]["version"]


# ---------------------------------------------------------------------------
# Seat capacity outranks the fiscal gate
# ---------------------------------------------------------------------------
def _company_at_capacity_with_a_budget_too_small_to_hire(api):
    """A company already carrying its overstaff rider, at a station with no money."""
    station = fx.create_station(
        api,
        name="Station 51",
        battalion_code="C1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=1000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-51",
        minimum_crew_size=1,
        required_certifications=["PARAMEDIC"],
        closure_priority=10,
    )
    rider_one = fx.create_firefighter(
        api,
        station["id"],
        full_name="W Wachter",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    rider_two = fx.create_firefighter(
        api,
        station["id"],
        full_name="X Xiong",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    paramedic = fx.create_firefighter(
        api,
        station["id"],
        full_name="Y Yilmaz",
        platoon="C",
        seniority_rank=3,
        kelly_day_cycle_position=3,
        certifications=["PARAMEDIC"],
        hourly_rate_cents=4237,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "PARAMEDIC")

    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    fx.seat_member(api, shift["id"], rider_one["id"], engine["id"], rider_one["id"])
    fx.seat_member(api, shift["id"], rider_two["id"], engine["id"], rider_one["id"])
    vacancy = fx.first_vacancy(
        api,
        duty_shift_id=shift["id"],
        status="OPEN",
        required_certification="PARAMEDIC",
    )
    return {
        "station": station,
        "engine": engine,
        "paramedic": paramedic,
        "shift": shift,
        "vacancy": vacancy,
    }


class TestSeatCapacityOutranksTheFiscalGate:
    """A company with no free seat is refused before the money is even consulted."""

    def test_full_company_reports_seat_capacity_not_the_budget_gate(self, api):
        """Money is checked last of all, after every safety rule has passed.

        PRD 2.6: "**The fiscal gate** — `ERR_OT_BUDGET_WOULD_EXCEED` (422).
        Money is checked last of all, because the check needs a priced offer and
        a priced offer needs a selected candidate: every safety and eligibility
        rule must already have passed before the budget is consulted."

        Design: Difficulty/priority_pair_validation_conflict/seat_capacity_safety_beats_fiscal_budget_gate_on_overtime_offer
        """
        world = _company_at_capacity_with_a_budget_too_small_to_hire(api)

        response = api.offer_vacancy(
            world["vacancy"]["id"],
            {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
            STAFFING_OFFICER,
        )

        error = validate_error(
            response, ApiErrorId.APPARATUS_SEAT_CAPACITY_EXCEEDED.value, 422
        )
        assert error["error_id"] != ApiErrorId.OT_BUDGET_WOULD_EXCEED.value

    def test_the_refused_dispatch_leaves_the_ledger_and_the_vacancy_alone(self, api):
        """A refusal writes nothing at all, so no encumbrance is taken.

        PRD 3.6: "Step two compares the prospective total — the station's
        `ot_actual_cents` plus its `ot_committed_cents` plus the priced cost —
        against `fiscal_ot_budget_cents`, and refuses the dispatch with
        `ERR_OT_BUDGET_WOULD_EXCEED` if that total is **strictly greater** than
        the budget; a hire landing exactly on the budget is allowed, and a
        refusal writes nothing at all."

        Design: Difficulty/priority_pair_validation_conflict/seat_capacity_safety_beats_fiscal_budget_gate_on_overtime_offer
        """
        world = _company_at_capacity_with_a_budget_too_small_to_hire(api)

        api.offer_vacancy(
            world["vacancy"]["id"],
            {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
            STAFFING_OFFICER,
        )

        assert fx.list_offers(api, vacancy_id=world["vacancy"]["id"]) == []

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0
        assert station["budget_posture"] == "WITHIN"

        vacancy = fx.read_vacancy(api, world["vacancy"]["id"])
        assert vacancy["status"] == "OPEN"

        member = fx.read_firefighter(api, world["paramedic"]["id"])
        assert member["pending_offer_count"] == 0
