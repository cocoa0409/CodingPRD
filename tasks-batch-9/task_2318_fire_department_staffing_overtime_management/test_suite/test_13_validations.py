"""The seat gauntlet, the trade window, the hour cap, the fiscal gate and the
closure preconditions, exercised one refusal at a time and in precedence order.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    PAYROLL_ANALYST,
    STAFFING_OFFICER,
    ApiErrorId,
    fixtures as fx,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Kelly day: which seat types are exempt
# ---------------------------------------------------------------------------
def _member_on_a_kelly_day_for_the_tour(api):
    """A platoon C member whose Kelly slot falls on the 2026-08-11 tour."""
    station = fx.create_station(
        api,
        name="Station 104",
        battalion_code="E8",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-104",
        minimum_crew_size=2,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="W Wyatt",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=8,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="X Xu",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=5000,
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    return {
        "station": station,
        "engine": engine,
        "member": member,
        "officer": officer,
        "shift": shift,
    }


def _seat_payload(world, assignment_type, version, **overrides):
    payload = {
        "duty_shift_id": world["shift"]["id"],
        "firefighter_id": world["member"]["id"],
        "apparatus_id": world["engine"]["id"],
        "assignment_type": assignment_type,
        "seat_certification": "NONE",
        "scheduled_hours": 24,
        "expected_duty_shift_version": version,
    }
    payload.update(overrides)
    return payload


class TestKellyDayExemptSeatTypes:
    """The Kelly check binds a regular seat and spares a Kelly relief seat."""

    def test_a_regular_seat_on_a_members_kelly_day_is_refused(self, api):
        """The rotation band reports the Kelly clash, not a platoon mismatch.

        PRD 3.3: "And for every assignment type **other than** `KELLY_RELIEF` and
        `CALLBACK`, the member must not be on a Kelly day for that date, else
        `ERR_KELLY_DAY_CONFLICT` — the two excepted types exist precisely to seat
        somebody on their day off."

        Design: Corner/validations/kelly_day_blocks_a_regular_seat_but_not_a_kelly_relief_seat
        """
        world = _member_on_a_kelly_day_for_the_tour(api)
        version = world["shift"]["version"]

        response = api.create_shift_assignment(
            _seat_payload(world, "REGULAR", version),
            fx.make_company_officer_headers(world["officer"]["id"]),
        )

        error = validate_error(response, ApiErrorId.KELLY_DAY_CONFLICT.value, 422)
        # His platoon is the platoon on duty for 2026-08-11, so the earlier
        # rotation rule is satisfied and cannot be the reported failure.
        assert error["error_id"] != ApiErrorId.PLATOON_ROTATION_VIOLATION.value

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["assigned_headcount"] == 0
        assert shift["version"] == version
        assert shift["open_vacancy_count"] == 2

    def test_the_identical_request_as_kelly_relief_is_accepted(self, api):
        """The excepted seat type seats the same member on the same day.

        PRD 3.3: "Its `projected_premium_cents` is zero for `REGULAR`,
        `KELLY_RELIEF` and `TRADE` seats — those carry no overtime premium — and
        for overtime-derived seats is set as described in §3.7."

        Design: Corner/validations/kelly_day_blocks_a_regular_seat_but_not_a_kelly_relief_seat
        """
        world = _member_on_a_kelly_day_for_the_tour(api)
        version = world["shift"]["version"]
        officer_headers = fx.make_company_officer_headers(world["officer"]["id"])

        refused = api.create_shift_assignment(
            _seat_payload(world, "REGULAR", version), officer_headers
        )
        validate_error(refused, ApiErrorId.KELLY_DAY_CONFLICT.value, 422)

        # The refusal wrote nothing, so the same shift version is still current.
        relief = validate_success(
            api.create_shift_assignment(
                _seat_payload(world, "KELLY_RELIEF", version), officer_headers
            ),
            201,
        )
        assert relief["assignment_type"] == "KELLY_RELIEF"
        assert relief["status"] == "SCHEDULED"
        assert relief["projected_premium_cents"] == 0

        shift = fx.read_shift(api, world["shift"]["id"])
        assert shift["assigned_headcount"] == 1
        assert shift["open_vacancy_count"] == 1
        assert shift["staffing_gap"] == 1
        assert shift["staffing_posture"] == "SHORT"


# ---------------------------------------------------------------------------
# Rest-period ceiling: the third consecutive tour
# ---------------------------------------------------------------------------
def _member_holding_two_back_to_back_tours(api):
    """Two adjacent 24-hour seats, with a third tour published and open."""
    station = fx.create_station(
        api,
        name="Station 105",
        battalion_code="E9",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-105",
        minimum_crew_size=3,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="Y Yates",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="Z Zeller",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=5000,
    )

    first = fx.published_shift(api, station["id"], "2026-08-10", "B")
    first_seat = fx.seat_member(
        api,
        first["id"],
        member["id"],
        engine["id"],
        officer["id"],
        assignment_type="CALLBACK",
    )
    second = fx.published_shift(api, station["id"], "2026-08-11", "C")
    second_seat = fx.seat_member(
        api, second["id"], member["id"], engine["id"], officer["id"]
    )
    third = fx.published_shift(api, station["id"], "2026-08-12", "D")

    return {
        "station": station,
        "engine": engine,
        "member": member,
        "officer": officer,
        "first_seat": first_seat,
        "second_seat": second_seat,
        "third_shift": fx.read_shift(api, third["id"]),
    }


class TestRestPeriodCeiling:
    """Forty-eight continuous hours is allowed; seventy-two is not."""

    def test_a_third_consecutive_tour_is_refused_and_leaves_the_block_at_48(self, api):
        """Merging a third adjacent tour breaches the continuous-duty ceiling.

        PRD 3.3: "Two consecutive twenty-four-hour tours therefore merge into a
        single forty-eight-hour block: the fatigue premium applies because 48
        exceeds 24, and the seat is allowed because 48 does not exceed 48. Adding
        a third consecutive tour reaches seventy-two hours and is refused."

        Design: Corner/validations/third_consecutive_tour_breaches_the_rest_period_ceiling
        """
        world = _member_holding_two_back_to_back_tours(api)
        version = world["third_shift"]["version"]

        response = api.create_shift_assignment(
            {
                "duty_shift_id": world["third_shift"]["id"],
                "firefighter_id": world["member"]["id"],
                "apparatus_id": world["engine"]["id"],
                "assignment_type": "OVERTIME",
                "seat_certification": "NONE",
                "scheduled_hours": 24,
                "expected_duty_shift_version": version,
            },
            fx.make_company_officer_headers(world["officer"]["id"]),
        )

        error = validate_error(response, ApiErrorId.REST_PERIOD_VIOLATION.value, 422)
        # Adjacency at the shared 08:00 instant is not an overlap.
        assert error["error_id"] != ApiErrorId.DOUBLE_BOOKED_SHIFT.value

        assert fx.read_assignment(api, world["first_seat"]["id"])["status"] == "SCHEDULED"
        assert (
            fx.read_assignment(api, world["second_seat"]["id"])["status"] == "SCHEDULED"
        )

        shift = fx.read_shift(api, world["third_shift"]["id"])
        assert shift["assigned_headcount"] == 0
        assert shift["version"] == version

        period = fx.work_period_of(api, world["member"]["id"])
        assert period["scheduled_hours"] == 48


# ---------------------------------------------------------------------------
# Trade lead time: an inclusive deadline
# ---------------------------------------------------------------------------
def _two_proposed_trades_on_one_tour(api):
    """Two givers holding seats, each with a live proposal to an idle colleague."""
    station = fx.create_station(
        api,
        name="Station 106",
        battalion_code="F1",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-106",
        minimum_crew_size=4,
        required_certifications=[],
        closure_priority=10,
    )
    crew = {}
    for key, name, seniority, kelly, rank in (
        ("a", "A Abbot", 1, 1, "FIREFIGHTER"),
        ("b", "B Braun", 2, 2, "FIREFIGHTER"),
        ("c", "C Cadiz", 3, 3, "FIREFIGHTER"),
        ("d", "D Dunne", 4, 4, "FIREFIGHTER"),
        ("officer", "E Eaves", 9, 5, "CAPTAIN"),
    ):
        crew[key] = fx.create_firefighter(
            api,
            station["id"],
            full_name=name,
            rank=rank,
            platoon="C",
            seniority_rank=seniority,
            kelly_day_cycle_position=kelly,
            certifications=[],
            hourly_rate_cents=5000 if rank == "CAPTAIN" else 4000,
        )

    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    seat_a = fx.seat_member(
        api, shift["id"], crew["a"]["id"], engine["id"], crew["officer"]["id"]
    )
    seat_c = fx.seat_member(
        api, shift["id"], crew["c"]["id"], engine["id"], crew["officer"]["id"]
    )

    trade_a = fx.propose_trade(api, crew["a"]["id"], crew["b"]["id"], shift["id"])
    trade_c = fx.propose_trade(api, crew["c"]["id"], crew["d"]["id"], shift["id"])

    return {
        "station": station,
        "crew": crew,
        "shift": shift,
        "seat_a": seat_a,
        "seat_c": seat_c,
        "trade_a": trade_a,
        "trade_c": trade_c,
    }


class TestTradeLeadTimeWindow:
    """The countersignature deadline is inclusive to the second."""

    def test_a_countersignature_exactly_forty_eight_hours_out_is_inside_the_window(
        self, api
    ):
        """The instant of the deadline itself still admits the countersignature.

        PRD 3.5: "Both the proposal and the countersignature are gated by lead
        time: the trade must be transacted at least 48 hours — two full days —
        before the duty period begins at 08:00:00 UTC on the shift date, measured
        against the logical clock of §2.5. Exactly forty-eight hours out is still
        inside the window; anything later is refused with
        `ERR_TRADE_WINDOW_CLOSED`."

        Design: Corner/validations/trade_countersign_window_closes_one_second_after_the_lead_time_deadline
        """
        world = _two_proposed_trades_on_one_tour(api)

        fx.set_clock(api, "2026-08-09T08:00:00Z")
        countersigned = validate_success(
            api.countersign_trade_request(
                world["trade_a"]["id"],
                fx.make_firefighter_headers(world["crew"]["b"]["id"]),
            ),
            200,
        )

        assert countersigned["status"] == "COUNTERSIGNED"
        # A countersignature is still only a proposal: no seat has moved.
        seat = fx.read_assignment(api, world["seat_a"]["id"])
        assert seat["firefighter_id"] == world["crew"]["a"]["id"]
        assert seat["status"] == "SCHEDULED"

    def test_a_countersignature_one_second_later_is_refused(self, api):
        """One second past the deadline closes the window.

        PRD 3.5: "The lead-time window must still be open, else
        `ERR_TRADE_WINDOW_CLOSED`."

        Design: Corner/validations/trade_countersign_window_closes_one_second_after_the_lead_time_deadline
        """
        world = _two_proposed_trades_on_one_tour(api)

        fx.set_clock(api, "2026-08-09T08:00:01Z")
        response = api.countersign_trade_request(
            world["trade_c"]["id"],
            fx.make_firefighter_headers(world["crew"]["d"]["id"]),
        )

        validate_error(response, ApiErrorId.TRADE_WINDOW_CLOSED.value, 422)

        trade = fx.read_trade(api, world["trade_c"]["id"])
        assert trade["status"] == "PROPOSED"
        assert trade["revision_count"] == 0
        assert trade["traded_assignment_id"] is None

        assert (
            fx.read_assignment(api, world["seat_c"]["id"])["firefighter_id"]
            == world["crew"]["c"]["id"]
        )


# ---------------------------------------------------------------------------
# Staffing floor: the single-seat path raises
# ---------------------------------------------------------------------------
class TestStaffingFloorOnCancellation:
    """Un-seating is the one path where the floor is an error, not a denial."""

    def test_releasing_the_last_seat_above_the_floor_is_refused(self, api):
        """The crew sits exactly on the floor, so no body may be released.

        PRD 3.3: "It is admissible only on a seat still in `SCHEDULED` (else
        `ERR_ASSIGNMENT_NOT_SCHEDULED`) belonging to a shift in `HIRING` or
        `STAFFED` (else `ERR_SHIFT_NOT_HIRING`), and it is refused with
        `ERR_STAFFING_FLOOR_BREACH` when removing the body would drop
        `assigned_headcount` below the shift's `leave_floor_headcount`."

        Design: Corner/validations/cancelling_the_last_seat_above_the_floor_is_refused
        """
        station = fx.create_station(
            api,
            name="Station 107",
            battalion_code="F1",
            minimum_staffing_floor=2,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-107",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        first = fx.create_firefighter(
            api,
            station["id"],
            full_name="F Finch",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        second = fx.create_firefighter(
            api,
            station["id"],
            full_name="G Gale",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="H Hines",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=3,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        first_seat = fx.seat_member(
            api, shift["id"], first["id"], engine["id"], officer["id"]
        )
        second_seat = fx.seat_member(
            api, shift["id"], second["id"], engine["id"], officer["id"]
        )

        staffed = fx.read_shift(api, shift["id"])
        # The larger of the contractual floor of two and required staffing less
        # the negotiated slack of two bodies.
        assert staffed["leave_floor_headcount"] == 2

        response = api.cancel_shift_assignment(
            second_seat["id"],
            {"reason": "requested release"},
            fx.make_company_officer_headers(officer["id"]),
        )

        validate_error(response, ApiErrorId.STAFFING_FLOOR_BREACH.value, 422)

        assert fx.read_assignment(api, first_seat["id"])["status"] == "SCHEDULED"
        assert fx.read_assignment(api, second_seat["id"])["status"] == "SCHEDULED"

        after = fx.read_shift(api, shift["id"])
        assert after["assigned_headcount"] == 2
        assert after["status"] == "STAFFED"
        assert after["staffing_posture"] == "FULLY_STAFFED"

        period = fx.work_period_of(api, second["id"])
        assert period["scheduled_hours"] == 24
        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 0


# ---------------------------------------------------------------------------
# Precedence: cross-entity coherence over rotation
# ---------------------------------------------------------------------------
class TestCertificationOutranksKellyDay:
    """A referential failure is reported ahead of a temporal one."""

    def test_the_missing_specialty_is_reported_and_not_the_kelly_clash(self, api):
        """One request breaks both bands; the higher band names the error.

        PRD 2.6: "9. **Cross-entity coherence** (422): the references resolved at
        step 4 exist but do not fit together — `ERR_STATION_SCOPE_MISMATCH`,
        `ERR_CERTIFICATION_NOT_HELD`, `ERR_LEAVE_ALREADY_BACKFILLED`,
        `ERR_ROSTER_NOT_CONFIGURED`. This band sits strictly above the temporal
        rules, so a member from another station seated on the wrong platoon
        returns `ERR_STATION_SCOPE_MISMATCH` rather than a rotation error."

        Design: Corner/validations/certification_check_outranks_the_kelly_day_check_on_the_same_seat
        """
        station = fx.create_station(
            api,
            name="Station 108",
            battalion_code="F2",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        medic = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="MEDIC-108",
            apparatus_type="MEDIC",
            minimum_crew_size=2,
            required_certifications=["PARAMEDIC"],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="I Innis",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=8,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="J Jonas",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        version = shift["version"]

        # Both failures are genuinely present: no certifications at all, and
        # 2026-08-11 is his Kelly day.
        assert member["certifications"] == []

        response = api.create_shift_assignment(
            {
                "duty_shift_id": shift["id"],
                "firefighter_id": member["id"],
                "apparatus_id": medic["id"],
                "assignment_type": "REGULAR",
                "seat_certification": "PARAMEDIC",
                "scheduled_hours": 24,
                "expected_duty_shift_version": version,
            },
            fx.make_company_officer_headers(officer["id"]),
        )

        error = validate_error(response, ApiErrorId.CERTIFICATION_NOT_HELD.value, 422)
        assert error["error_id"] != ApiErrorId.KELLY_DAY_CONFLICT.value

        after = fx.read_shift(api, shift["id"])
        assert after["assigned_headcount"] == 0
        assert after["certification_gap_count"] == 1
        assert after["version"] == version


# ---------------------------------------------------------------------------
# Precedence: double booking over the aggregate seat ceiling
# ---------------------------------------------------------------------------
class TestDoubleBookingOutranksSeatCapacity:
    """The individual overlap is reported ahead of the collective ceiling."""

    def test_the_overlap_error_wins_over_the_full_company(self, api):
        """A seated member asking for a second seat on a full company.

        PRD 2.6: "11. **Double booking** — `ERR_DOUBLE_BOOKED_SHIFT` (422)."

        Design: Corner/validations/double_booking_check_outranks_the_seat_capacity_check
        """
        station = fx.create_station(
            api,
            name="Station 109",
            battalion_code="F2",
            minimum_staffing_floor=0,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-109",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        first = fx.create_firefighter(
            api,
            station["id"],
            full_name="K Kraus",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        second = fx.create_firefighter(
            api,
            station["id"],
            full_name="L Loera",
            platoon="C",
            seniority_rank=2,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="M Mata",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=3,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        fx.seat_member(api, shift["id"], first["id"], engine["id"], officer["id"])
        fx.seat_member(api, shift["id"], second["id"], engine["id"], officer["id"])

        loaded = fx.read_shift(api, shift["id"])
        # One rider above the minimum crew of one, so the company is now full.
        assert loaded["assigned_headcount"] == 2
        version = loaded["version"]

        response = api.create_shift_assignment(
            {
                "duty_shift_id": shift["id"],
                "firefighter_id": first["id"],
                "apparatus_id": engine["id"],
                "assignment_type": "OVERTIME",
                "seat_certification": "NONE",
                "scheduled_hours": 24,
                "expected_duty_shift_version": version,
            },
            fx.make_company_officer_headers(officer["id"]),
        )

        error = validate_error(response, ApiErrorId.DOUBLE_BOOKED_SHIFT.value, 422)
        assert error["error_id"] != ApiErrorId.APPARATUS_SEAT_CAPACITY_EXCEEDED.value

        after = fx.read_shift(api, shift["id"])
        assert after["assigned_headcount"] == 2
        assert after["version"] == version


# ---------------------------------------------------------------------------
# The clean path through the whole gauntlet
# ---------------------------------------------------------------------------
class TestCleanSeatRequest:
    """A request that breaks nothing moves every derived field at once."""

    def test_a_seat_that_passes_every_gate_staffs_the_shift_and_books_the_hours(
        self, api
    ):
        """One accepted seat fills the vacancy, staffs the shift and books 24 hours.

        PRD 3.3: "If the new seat matches an `OPEN` vacancy on the same company
        with the same required certification, that vacancy moves to `FILLED` and
        its `filled_by_assignment_id` is set to the new seat. The covering work
        period's scheduled hours increase by the seat's `scheduled_hours` and the
        projection is re-priced on the scheduled basis."

        Design: Corner/validations/clean_regular_seat_passes_every_gate_and_updates_all_derived_state
        """
        station = fx.create_station(
            api,
            name="Station 110",
            battalion_code="F3",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        engine = fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-110",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="N Nagel",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        officer = fx.create_firefighter(
            api,
            station["id"],
            full_name="O Obrien",
            rank="CAPTAIN",
            platoon="C",
            seniority_rank=9,
            kelly_day_cycle_position=2,
            certifications=[],
            hourly_rate_cents=5000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")
        period = fx.work_period_of(api, member["id"])

        seat = validate_success(
            api.create_shift_assignment(
                {
                    "duty_shift_id": shift["id"],
                    "firefighter_id": member["id"],
                    "apparatus_id": engine["id"],
                    "assignment_type": "REGULAR",
                    "seat_certification": "NONE",
                    "scheduled_hours": 24,
                    "expected_duty_shift_version": shift["version"],
                },
                fx.make_company_officer_headers(officer["id"]),
            ),
            201,
        )

        assert seat["status"] == "SCHEDULED"
        assert seat["actual_hours"] is None
        assert seat["source_offer_id"] is None
        assert seat["relieved_by_leave_request_id"] is None
        assert seat["projected_premium_cents"] == 0

        filled = fx.read_vacancy(api, vacancy["id"])
        assert filled["status"] == "FILLED"
        assert filled["filled_by_assignment_id"] == seat["id"]

        after = fx.read_shift(api, shift["id"])
        assert after["status"] == "STAFFED"
        assert after["assigned_headcount"] == 1
        assert after["staffing_gap"] == 0
        assert after["open_vacancy_count"] == 0
        assert after["staffing_posture"] == "FULLY_STAFFED"
        assert after["version"] == shift["version"] + 1

        booked = fx.read_work_period(api, period["id"])
        assert booked["scheduled_hours"] == 24
        assert booked["adjusted_scheduled_hours"] == 0
        assert booked["projected_flsa_overtime_hours"] == 0
        assert booked["flsa_premium_cents"] == 0

        # A regular seat carries no overtime, so no money is encumbered.
        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 0


# ---------------------------------------------------------------------------
# The 288-hour work-period cap, inclusive
# ---------------------------------------------------------------------------
def _period_carrying_two_hundred_and_sixty_four_imported_hours(api):
    """A member whose period already holds 264 adjusted scheduled hours."""
    station = fx.create_station(
        api,
        name="Station 111",
        battalion_code="F3",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=500_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    engine = fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-111",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="P Pruitt",
        platoon="C",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    officer = fx.create_firefighter(
        api,
        station["id"],
        full_name="Q Quade",
        rank="CAPTAIN",
        platoon="C",
        seniority_rank=9,
        kelly_day_cycle_position=2,
        certifications=[],
        hourly_rate_cents=5000,
    )
    period = fx.work_period_of(api, member["id"])
    fx.adjust_hours(
        api, period["id"], 264, "SCHEDULED", reason="hours imported from the prior period"
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")

    return {
        "station": station,
        "engine": engine,
        "member": member,
        "officer": officer,
        "period": period,
        "shift": shift,
    }


class TestWorkPeriodHourCap:
    """Two hundred and eighty-eight hours exactly is allowed; 289 is not."""

    def test_the_seat_that_lands_exactly_on_the_cap_is_accepted(self, api):
        """264 imported hours plus a 24-hour tour is exactly at the ceiling.

        PRD 3.9: "Independently of the threshold, no operation may push a
        period's scheduled hours above **288**; any that would is refused with
        `ERR_FLSA_WORK_PERIOD_CAP_EXCEEDED`, and 288 exactly is allowed while 289
        is not."

        Design: Corner/validations/flsa_cap_allows_exactly_288_hours_and_refuses_289
        """
        world = _period_carrying_two_hundred_and_sixty_four_imported_hours(api)

        seat = fx.seat_member(
            api,
            world["shift"]["id"],
            world["member"]["id"],
            world["engine"]["id"],
            world["officer"]["id"],
        )
        assert seat["status"] == "SCHEDULED"

        period = fx.read_work_period(api, world["period"]["id"])
        assert period["adjusted_scheduled_hours"] == 264
        assert period["scheduled_hours"] == 288
        # 288 less the 204-hour threshold, priced at half of 4000 cents.
        assert period["projected_flsa_overtime_hours"] == 84
        assert period["flsa_premium_cents"] == 168_000

    def test_the_two_hundred_and_eighty_ninth_hour_is_refused(self, api):
        """One more adjustment hour on top of the cap is rejected.

        PRD 3.9: "An adjustment that would push the period's scheduled hours
        above 288 is refused with `ERR_FLSA_WORK_PERIOD_CAP_EXCEEDED`."

        Design: Corner/validations/flsa_cap_allows_exactly_288_hours_and_refuses_289
        """
        world = _period_carrying_two_hundred_and_sixty_four_imported_hours(api)
        seat = fx.seat_member(
            api,
            world["shift"]["id"],
            world["member"]["id"],
            world["engine"]["id"],
            world["officer"]["id"],
        )

        response = api.hour_adjustment(
            world["period"]["id"],
            {
                "adjustment_hours": 1,
                "adjustment_basis": "SCHEDULED",
                "reason": "one more drill hour",
            },
            PAYROLL_ANALYST,
        )

        validate_error(response, ApiErrorId.FLSA_WORK_PERIOD_CAP_EXCEEDED.value, 422)

        period = fx.read_work_period(api, world["period"]["id"])
        assert period["scheduled_hours"] == 288
        assert period["adjusted_scheduled_hours"] == 264
        assert period["flsa_premium_cents"] == 168_000
        assert fx.read_assignment(api, seat["id"])["status"] == "SCHEDULED"


class TestOfferAcceptanceRechecksTheHourCap:
    """The cap is re-evaluated at response time, not only at selection time."""

    def test_hours_imported_after_dispatch_block_the_acceptance(self, api):
        """A legally dispatched offer becomes unacceptable once the period fills.

        PRD 3.7: "and their covering work period's scheduled hours plus the
        offer's payable hours must not exceed 288, else
        `ERR_FLSA_WORK_PERIOD_CAP_EXCEEDED`."

        Design: Corner/validations/offer_acceptance_rechecks_the_flsa_cap_against_hours_added_after_dispatch
        """
        station = fx.create_station(
            api,
            name="Station 112",
            battalion_code="F4",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-112",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="R Ruiz",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        fx.create_hiring_roster(api, station["id"], "VOLUNTARY_OT", "NONE")
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")

        offer = fx.dispatch_offer(api, vacancy["id"], "VOLUNTARY", 24)
        assert offer["projected_cost_cents"] == 144_000

        period = fx.work_period_of(api, member["id"])
        fx.adjust_hours(
            api,
            period["id"],
            270,
            "SCHEDULED",
            reason="late import of another station's hours",
        )

        response = api.respond_to_offer(
            offer["id"], {"response": "ACCEPT"}, fx.make_firefighter_headers(member["id"])
        )

        validate_error(response, ApiErrorId.FLSA_WORK_PERIOD_CAP_EXCEEDED.value, 422)

        assert fx.read_offer(api, offer["id"])["status"] == "OFFERED"
        assert fx.read_vacancy(api, vacancy["id"])["status"] == "OFFERING"

        _, meta = validate_paginated(
            api.list_shift_assignments(STAFFING_OFFICER, source_offer_id=offer["id"])
        )
        assert meta["total_count"] == 0

        after = fx.read_work_period(api, period["id"])
        assert after["adjusted_scheduled_hours"] == 270
        assert after["scheduled_hours"] == 270

        # The encumbrance from the still-open offer is untouched.
        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 144_000

        held = fx.read_firefighter(api, member["id"])
        assert held["pending_offer_count"] == 1
        assert held["ot_pass_count"] == 0


# ---------------------------------------------------------------------------
# Existence before referential coherence
# ---------------------------------------------------------------------------
class TestExistenceBeforeRosterResolution:
    """A missing vacancy is a 404 before the roster is ever looked for."""

    def test_an_unknown_vacancy_is_not_found_while_a_real_one_lacks_a_roster(self, api):
        """The same payload yields a 404 on a fake id and a 422 on a real one.

        PRD 3.6: "If neither exists the request is refused with
        `ERR_ROSTER_NOT_CONFIGURED`. The roster that was used is recorded on the
        resulting offer as `roster_id`, and its `dispatch_count` increases by
        one."

        Design: Corner/validations/existence_check_runs_before_the_roster_configuration_check
        """
        station = fx.create_station(
            api,
            name="Station 113",
            battalion_code="F4",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=900_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-113",
            minimum_crew_size=1,
            required_certifications=[],
            closure_priority=10,
        )
        member = fx.create_firefighter(
            api,
            station["id"],
            full_name="S Sisto",
            platoon="C",
            seniority_rank=1,
            kelly_day_cycle_position=1,
            certifications=[],
            hourly_rate_cents=4000,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")

        payload = {"hiring_mode": "VOLUNTARY", "offer_hours": 24}

        unknown = api.offer_vacancy(NON_EXISTENT_UUID, payload, STAFFING_OFFICER)
        validate_error(unknown, ApiErrorId.VACANCY_NOT_FOUND.value, 404)

        real = api.offer_vacancy(vacancy["id"], payload, STAFFING_OFFICER)
        validate_error(real, ApiErrorId.ROSTER_NOT_CONFIGURED.value, 422)

        assert fx.read_vacancy(api, vacancy["id"])["status"] == "OPEN"

        _, meta = validate_paginated(
            api.list_overtime_offers(STAFFING_OFFICER, vacancy_id=vacancy["id"])
        )
        assert meta["total_count"] == 0

        assert fx.read_station(api, station["id"])["ot_committed_cents"] == 0
        assert fx.read_firefighter(api, member["id"])["pending_offer_count"] == 0


# ---------------------------------------------------------------------------
# The fiscal gate, and the mode that skips it
# ---------------------------------------------------------------------------
def _station_whose_budget_cannot_afford_one_tour(api):
    """A 100,000-cent budget, one holdover-eligible member and both rosters."""
    station = fx.create_station(
        api,
        name="Station 114",
        battalion_code="F5",
        minimum_staffing_floor=1,
        fiscal_ot_budget_cents=100_000,
        fiscal_period_start_date="2026-08-01",
        fiscal_period_end_date="2026-08-31",
    )
    fx.create_apparatus(
        api,
        station["id"],
        unit_designation="ENGINE-114",
        minimum_crew_size=1,
        required_certifications=[],
        closure_priority=10,
    )
    # Platoon B rides the 2026-08-10 tour, the day before the target shift, so
    # he is eligible for a holdover as well as for voluntary overtime.
    member = fx.create_firefighter(
        api,
        station["id"],
        full_name="T Tovar",
        platoon="B",
        seniority_rank=1,
        kelly_day_cycle_position=1,
        certifications=[],
        hourly_rate_cents=4000,
    )
    voluntary_roster = fx.create_hiring_roster(
        api, station["id"], "VOLUNTARY_OT", "NONE"
    )
    holdover_roster = fx.create_hiring_roster(
        api, station["id"], "MANDATORY_HOLDOVER", "NONE"
    )
    shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
    vacancy = fx.first_vacancy(api, duty_shift_id=shift["id"], status="OPEN")

    return {
        "station": station,
        "member": member,
        "voluntary_roster": voluntary_roster,
        "holdover_roster": holdover_roster,
        "shift": shift,
        "vacancy": vacancy,
    }


class TestFiscalGateIsConditionalOnHiringMode:
    """Money is checked last, and mandatory holdover does not consult it."""

    def test_the_voluntary_hire_over_budget_is_refused_and_writes_nothing(self, api):
        """A 144,000-cent hire against a 100,000-cent budget is refused.

        PRD 3.6: "Step two compares the prospective total — the station's
        `ot_actual_cents` plus its `ot_committed_cents` plus the priced cost —
        against `fiscal_ot_budget_cents`, and refuses the dispatch with
        `ERR_OT_BUDGET_WOULD_EXCEED` if that total is **strictly greater** than
        the budget; a hire landing exactly on the budget is allowed, and a refusal
        writes nothing at all."

        Design: Corner/validations/budget_gate_applies_to_voluntary_hiring_and_is_bypassed_by_mandatory_holdover
        """
        world = _station_whose_budget_cannot_afford_one_tour(api)

        response = api.offer_vacancy(
            world["vacancy"]["id"],
            {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
            STAFFING_OFFICER,
        )

        validate_error(response, ApiErrorId.OT_BUDGET_WOULD_EXCEED.value, 422)

        assert fx.read_vacancy(api, world["vacancy"]["id"])["status"] == "OPEN"

        station = fx.read_station(api, world["station"]["id"])
        assert station["ot_committed_cents"] == 0
        assert station["budget_posture"] == "WITHIN"

        assert fx.read_firefighter(api, world["member"]["id"])["pending_offer_count"] == 0

        roster = get_success_data(
            api.get_hiring_roster(world["voluntary_roster"]["id"], STAFFING_OFFICER)
        )
        assert roster["dispatch_count"] == 0

    def test_the_same_hire_as_a_mandatory_holdover_is_dispatched_over_budget(self, api):
        """The compelled seat is filled even though it busts the budget.

        PRD 3.6: "**Mandatory holdover skips step two entirely**: the labor
        agreement compels the seat to be filled, so a holdover is dispatched even
        when the encumbrance pushes the station's `budget_posture` to `OVER`."

        Design: Corner/validations/budget_gate_applies_to_voluntary_hiring_and_is_bypassed_by_mandatory_holdover
        """
        world = _station_whose_budget_cannot_afford_one_tour(api)

        refused = api.offer_vacancy(
            world["vacancy"]["id"],
            {"hiring_mode": "VOLUNTARY", "offer_hours": 24},
            STAFFING_OFFICER,
        )
        validate_error(refused, ApiErrorId.OT_BUDGET_WOULD_EXCEED.value, 422)

        mandated = validate_success(
            api.offer_vacancy(
                world["vacancy"]["id"],
                {"hiring_mode": "MANDATORY_HOLDOVER", "offer_hours": 24},
                STAFFING_OFFICER,
            ),
            201,
        )

        assert mandated["status"] == "MANDATED"
        assert mandated["projected_cost_cents"] == 144_000
        assert mandated["roster_id"] == world["holdover_roster"]["id"]

        station = fx.read_station(api, world["station"]["id"])
        # The gate was skipped, not satisfied.
        assert station["ot_committed_cents"] == 144_000
        assert station["budget_posture"] == "OVER"

        assert fx.read_vacancy(api, world["vacancy"]["id"])["status"] == "FILLED"
        assert fx.read_shift(api, world["shift"]["id"])["status"] == "STAFFED"


# ---------------------------------------------------------------------------
# Closure preconditions: justification before the pool
# ---------------------------------------------------------------------------
class TestClosurePreconditions:
    """A closure needs a critical posture first and an eligible company second."""

    def test_a_merely_short_shift_cannot_close_a_company(self, api):
        """The justification test runs before any candidate company is sought.

        PRD 3.8: "Closure is admissible on a shift in `HIRING` or `STAFFED`, else
        `ERR_SHIFT_NOT_HIRING`, and it is permitted **only** when the shift's
        `staffing_posture` is `CRITICAL`; a merely `SHORT` shift is refused with
        `ERR_CLOSURE_NOT_JUSTIFIED`, and that justification test is evaluated
        before any candidate company is looked for."

        Design: Corner/validations/closure_requires_a_critical_posture_and_a_non_exempt_company
        """
        station = fx.create_station(
            api,
            name="Station 115",
            battalion_code="F5",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-115",
            minimum_crew_size=2,
            required_certifications=[],
            closure_priority=10,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        assert shift["staffing_posture"] == "SHORT"

        response = api.company_closure(
            shift["id"],
            {
                "expected_duty_shift_version": shift["version"],
                "justification": "short two riders",
            },
            STAFFING_OFFICER,
        )

        error = validate_error(response, ApiErrorId.CLOSURE_NOT_JUSTIFIED.value, 422)
        # An eligible, non-exempt company does exist; the posture is the problem.
        assert error["error_id"] != ApiErrorId.NO_CLOSURE_ELIGIBLE_COMPANY.value

        after = fx.read_shift(api, shift["id"])
        assert after["staffing_posture"] == "SHORT"
        assert after["closed_apparatus_ids"] == []
        assert after["required_staffing"] == 2
        assert after["version"] == shift["version"]

    def test_a_critical_shift_with_only_an_exempt_company_has_no_eligible_pool(
        self, api
    ):
        """An exempt first-due company leaves the closure pool empty.

        PRD 3.8: "The candidate pool is the station's apparatus that are
        `IN_SERVICE`, are not `closure_exempt`, and do not already appear in the
        shift's `closed_apparatus_ids`. If that pool is empty the request is
        refused with `ERR_NO_CLOSURE_ELIGIBLE_COMPANY`."

        Design: Corner/validations/closure_requires_a_critical_posture_and_a_non_exempt_company
        """
        station = fx.create_station(
            api,
            name="Station 116",
            battalion_code="F5",
            minimum_staffing_floor=1,
            fiscal_ot_budget_cents=500_000,
            fiscal_period_start_date="2026-08-01",
            fiscal_period_end_date="2026-08-31",
        )
        fx.create_apparatus(
            api,
            station["id"],
            unit_designation="ENGINE-116",
            minimum_crew_size=4,
            required_certifications=[],
            closure_priority=10,
            closure_exempt=True,
        )
        shift = fx.published_shift(api, station["id"], "2026-08-11", "C")
        # A gap of four bodies is beyond the two-body SHORT band.
        assert shift["staffing_posture"] == "CRITICAL"

        response = api.company_closure(
            shift["id"],
            {
                "expected_duty_shift_version": shift["version"],
                "justification": "nobody available at all",
            },
            STAFFING_OFFICER,
        )

        error = validate_error(
            response, ApiErrorId.NO_CLOSURE_ELIGIBLE_COMPANY.value, 422
        )
        assert error["error_id"] != ApiErrorId.CLOSURE_NOT_JUSTIFIED.value

        after = fx.read_shift(api, shift["id"])
        assert after["staffing_posture"] == "CRITICAL"
        assert after["closed_apparatus_ids"] == []
        assert after["required_staffing"] == 4
        assert after["version"] == shift["version"]
