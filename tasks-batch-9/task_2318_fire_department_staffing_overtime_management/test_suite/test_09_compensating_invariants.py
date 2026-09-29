"""Round trips that must return a conserved quantity to its starting value: the
money encumbrance ledger, and the FLSA labour-hour ledger.
"""

from test_helpers import fixtures as fx


# ---------------------------------------------------------------------------
# Money: hire then cancel
# ---------------------------------------------------------------------------
def _station_with_one_hired_overtime_seat(api):
    """A shift staffed by one regular seat and one accepted overtime hire."""
    station = fx.create_station(
        api,
        name="Station 58",
        battalion_code="C2",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-58",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    hire = fx.create_firefighter(
        api,
        station["id"],
        full_name="K Kaur",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4237,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="L Lund",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=4,
        certifications=[],
        hourly_rate_cents=5000,
    )
    fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")

    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    fx.seat_member(api, shift["id"], officer["id"], engine["id"], officer["id"])
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")

    hired = fx.hire_into_vacancy(api, vacancy["id"], hire["id"], "VOLUNTARY", 24)

    return {
        "station": station,
        "hire": hire,
        "officer": officer,
        "shift": shift,
        "vacancy": vacancy,
        "offer": hired["offer"],
        "overtime_seat": fx.assignment_from_offer(api, hired["offer"]["id"]),
        "period": fx.work_period_of(api, hire["id"]),
    }


class TestEncumbranceLedgerRoundTrip:
    """Cancelling the hired seat credits back exactly what the hire debited."""

    def test_cancelling_the_hired_seat_returns_the_ledger_to_zero(self, api):
        """The credit equals the original encumbrance to the cent.

        PRD 2.10: "Every path that promises overtime debits the ledger, and every
        path that withdraws the promise credits back **exactly** the amount it
        debited: dispatching an offer, accepting one, declining one, letting one
        expire, rescinding one, mandating a holdover, cancelling a seat,
        approving a trade, closing a company and closing out a shift all move the
        ledger, and an accept-then-cancel or offer-then-expire round trip returns
        it to its starting value with no drift."

        Design: Difficulty/compensating_invariant/station_committed_ledger_restored_by_cancelling_hired_overtime_seat
        """
        world = _station_with_one_hired_overtime_seat(api)

        before = fx.read_station(api, world["station"]["id"])
        # 4237 cents at time and a half over 24 hours, with no uplift.
        assert before["ot_committed_cents"] == 152532

        cancelled = fx.cancel_seat(
            api, world["overtime_seat"]["id"], world["officer"]["id"]
        )
        assert cancelled["status"] == "CANCELLED"
        # The historical record is preserved; only the ledger is credited.
        assert cancelled["projected_premium_cents"] == 152532

        after = fx.read_station(api, world["station"]["id"])
        assert after["ot_committed_cents"] == 0
        assert after["ot_actual_cents"] == 0
        assert after["budget_posture"] == "WITHIN"

    def test_cancellation_reopens_the_seat_but_keeps_the_charged_hours(self, api):
        """The vacancy re-opens, the accepted offer is not rewritten.

        PRD 3.3: "any vacancy whose `filled_by_assignment_id` is this seat moves
        `FILLED → OPEN` with `filled_by_assignment_id` cleared to null; and the
        shift recomputes its derived staffing fields, falling back `STAFFED →
        HIRING` if a vacancy re-opened, with its `version` incremented."

        Design: Difficulty/compensating_invariant/station_committed_ledger_restored_by_cancelling_hired_overtime_seat
        """
        world = _station_with_one_hired_overtime_seat(api)

        fx.cancel_seat(api, world["overtime_seat"]["id"], world["officer"]["id"])

        vacancy = fx.read_vacancy(api, world["vacancy"]["id"])
        assert vacancy["status"] == "OPEN"
        assert vacancy["filled_by_assignment_id"] is None

        offer = fx.read_offer(api, world["offer"]["id"])
        assert offer["status"] == "ACCEPTED"

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "HIRING"
        assert shift["assigned_headcount"] == 1
        assert shift["open_vacancy_count"] == 1
        assert shift["staffing_gap"] == 1
        assert shift["staffing_posture"] == "SHORT"

        period = fx.read_work_period(api, world["period"]["id"])
        assert period["scheduled_hours"] == 0
        assert period["adjusted_scheduled_hours"] == 0
        assert period["projected_flsa_overtime_hours"] == 0
        assert period["flsa_premium_cents"] == 0

        member = fx.read_firefighter(api, world["hire"]["id"])
        assert member["pending_offer_count"] == 0
        # The hiring-order ledger is not credited back by a cancellation.
        assert member["voluntary_ot_hours_charged"] == 24


# ---------------------------------------------------------------------------
# Hours: approve leave then revoke it
# ---------------------------------------------------------------------------
def _approved_leave_on_a_period_carrying_carry_in_hours(api):
    """An approved vacation on a member whose period is already past 204 hours."""
    station = fx.create_station(
        api,
        name="Station 59",
        battalion_code="C2",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=9_000_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-09-30",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-59",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    leaver = fx.create_firefighter(
        api,
        station["id"],
        full_name="M Meier",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4237,
    )
    stayer = fx.create_firefighter(
        api,
        station["id"],
        full_name="N Novak",
        platoon="C",
        seniority_rank=2,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="O Osei",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=3,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    leaver_seat = fx.seat_member(
        api, shift["id"], leaver["id"], engine["id"], officer["id"]
    )
    stayer_seat = fx.seat_member(
        api, shift["id"], stayer["id"], engine["id"], officer["id"]
    )

    period = fx.work_period_of(api, leaver["id"])
    fx.adjust_hours(api, period["id"], 204, "SCHEDULED")

    leave = fx.file_leave(api, leaver["id"], shift["id"], "VACATION", 24)
    fx.adjudicate_leave(api, shift["id"], officer["id"])
    backfill = fx.first_vacancy(
        api, duty_shift_id=shift["id"], driver="LEAVE", status="OPEN"
    )

    return {
        "station": station,
        "leaver": leaver,
        "officer": officer,
        "shift": shift,
        "leaver_seat": leaver_seat,
        "stayer_seat": stayer_seat,
        "leave": leave,
        "backfill": backfill,
        "period": period,
    }


class TestHourLedgerRoundTrip:
    """Revocation runs the approval cascade backwards, hour for hour."""

    def test_revoking_leave_restores_the_hours_and_the_premium_exactly(self, api):
        """Every hour the approval moved out is moved back and re-priced.

        PRD 3.4: "**Hop two**, caused by hop one: the covering work period's
        scheduled hours are increased by the seat's `scheduled_hours` and both the
        projected overtime hours and the premium are recomputed, restoring the
        hour ledger of §3.9 exactly; the work period's leave hours are reduced by
        the request's `requested_hours`."

        Design: Difficulty/compensating_invariant/work_period_scheduled_hours_restored_by_leave_revoke
        """
        world = _approved_leave_on_a_period_carrying_carry_in_hours(api)

        relieved_period = fx.read_work_period(api, world["period"]["id"])
        assert relieved_period["scheduled_hours"] == 204
        assert relieved_period["leave_hours"] == 24
        assert relieved_period["projected_flsa_overtime_hours"] == 0
        assert relieved_period["flsa_premium_cents"] == 0

        fx.revoke_leave(api, world["leave"]["id"], world["leaver"]["id"])

        restored = fx.read_work_period(api, world["period"]["id"])
        assert restored["adjusted_scheduled_hours"] == 204
        assert restored["scheduled_hours"] == 228
        assert restored["leave_hours"] == 0
        assert restored["projected_flsa_overtime_hours"] == 24
        # 24 hours at half of 4237 cents.
        assert restored["flsa_premium_cents"] == 50844

    def test_revocation_cancels_the_backfill_and_re_seats_the_member(self, api):
        """Hop one re-seats the member and hop three cancels the backfill.

        PRD 3.4: "**Hop one:** the `RELIEVED` seat carrying this request's id in
        `relieved_by_leave_request_id` moves `RELIEVED → SCHEDULED` and that field
        is cleared to null."

        Design: Difficulty/compensating_invariant/work_period_scheduled_hours_restored_by_leave_revoke
        """
        world = _approved_leave_on_a_period_carrying_carry_in_hours(api)

        revoked = fx.revoke_leave(api, world["leave"]["id"], world["leaver"]["id"])
        assert revoked["status"] == "REVOKED"
        assert revoked["backfill_vacancy_id"] == world["backfill"]["id"]

        seat = fx.read_assignment(api, world["leaver_seat"]["id"])
        assert seat["status"] == "SCHEDULED"
        assert seat["relieved_by_leave_request_id"] is None

        backfill = fx.read_vacancy(api, world["backfill"]["id"])
        assert backfill["status"] == "CANCELLED"

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["status"] == "STAFFED"
        assert shift["assigned_headcount"] == 2
        assert shift["open_vacancy_count"] == 0
        assert shift["staffing_gap"] == 0
        assert shift["staffing_posture"] == "FULLY_STAFFED"

        untouched = fx.read_assignment(api, world["stayer_seat"]["id"])
        assert untouched["status"] == "SCHEDULED"

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0
