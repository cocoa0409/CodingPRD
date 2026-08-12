"""Hours-of-service availability arithmetic, daily/monthly/rest gates, gate
ordering against the state band, and the HOS optimistic-concurrency guard
(PRD §2.8, §2.9, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjust_hos,
    create_crew_member,
    create_movement,
    create_segment,
    is_valid_uuid,
    make_conductor_headers,
    setup_member_with_accumulators,
    setup_movement_with_crew,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CALLER = TEST_USERS["crew_caller_headers"]

def _movement_target():
    segment = create_segment(name="Main MP 40-44", milepost_start=40, milepost_end=44, fra_class="CLASS_3")
    return create_movement([segment["id"]], symbol="GW-501")


class TestHosAvailableMinutes:
    def test_hos_available_minutes_daily_term_governs(self, api, crew_caller_headers):
        """PRD §3.7: "A computed `hos_available_minutes`, visible on every member
        read, is the smaller of the two remaining allowances — 720 minutes minus
        the rolling accumulator, and 16,560 minutes minus the month accumulator —
        each floored at zero before the comparison."
        PRD §3.7: "A `SystemAdmin` or `CrewCaller` may correct a member's books by
        supplying any of `rolling_24h_minutes`, `month_minutes`, or
        `minutes_of_rest_completed`, which replace the corresponding
        accumulators."

        Design: Difficulty/combinatorial_formula/hos_availability_nested_min_mode_a
        """
        member = create_crew_member(name="A. Engineer", craft="ENGINEER")
        adjust_hos(member["id"], member["version"], rolling_24h_minutes=700, month_minutes=16500)
        read = validate_success(api.get_crew_member(member["id"], crew_caller_headers))
        assert read["hos_available_minutes"] == 20, (
            f"min(720-700, 16560-16500) = min(20, 60) must yield 20, got {read['hos_available_minutes']}"
        )

    def test_hos_available_minutes_monthly_term_governs(self, api, crew_caller_headers):
        """PRD §3.7: "A computed `hos_available_minutes`, visible on every member
        read, is the smaller of the two remaining allowances — 720 minutes minus
        the rolling accumulator, and 16,560 minutes minus the month accumulator —
        each floored at zero before the comparison."
        PRD §3.7: "A `SystemAdmin` or `CrewCaller` may correct a member's books by
        supplying any of `rolling_24h_minutes`, `month_minutes`, or
        `minutes_of_rest_completed`, which replace the corresponding
        accumulators."

        Design: Difficulty/combinatorial_formula/hos_availability_nested_min_mode_a
        """
        member = create_crew_member(name="A. Engineer", craft="ENGINEER")
        member = adjust_hos(member["id"], member["version"], rolling_24h_minutes=700, month_minutes=16500)
        adjust_hos(member["id"], member["version"], month_minutes=16559)
        read = validate_success(api.get_crew_member(member["id"], crew_caller_headers))
        assert read["hos_available_minutes"] == 1, (
            f"min(720-700, 16560-16559) = min(20, 1) must yield 1 — the monthly term "
            f"governs, got {read['hos_available_minutes']}"
        )

    def test_hos_available_minutes_readback(self, api, crew_caller_headers):
        """PRD §3.7: "A computed `hos_available_minutes`, visible on every member
        read, is the smaller of the two remaining allowances — 720 minutes minus
        the rolling accumulator, and 16,560 minutes minus the month accumulator —
        each floored at zero before the comparison."

        Design: Corner/calculations/hos_available_minutes_readback
        """
        member = setup_member_with_accumulators(name="O. Engineer", craft="ENGINEER",
                                                rolling_24h_minutes=719)
        read = validate_success(api.get_crew_member(member["id"], crew_caller_headers))
        assert read["hos_available_minutes"] == 1, (
            f"min(720-719, 16560-0) must yield exactly 1, got {read['hos_available_minutes']}"
        )


class TestHosDailyBoundary:
    def test_hos_daily_boundary_719_callable(self, api, crew_caller_headers):
        """PRD §3.7: "Creation runs its eligibility gates in band order: the
        member's `status` must be `AVAILABLE`, failing as
        `ERR_MEMBER_NOT_AVAILABLE`; the daily remaining allowance must be greater
        than zero — a member whose rolling accumulator has reached exactly 720 has
        none left — failing as `ERR_HOS_DAILY_LIMIT`; the monthly remaining
        allowance must likewise be greater than zero, failing as
        `ERR_HOS_MONTHLY_LIMIT`; and the member must be fully rested, meaning
        `rest_minutes_completed` unset or at least 600, failing as
        `ERR_HOS_REST_REQUIRED`."

        Design: Difficulty/boundary_precision_check/hos_daily_limit_719_vs_720
        """
        member = setup_member_with_accumulators(name="G. Conductor", rolling_24h_minutes=719)
        movement = _movement_target()
        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-03T06:00:00Z", "scheduled_end_at": "2026-05-03T18:00:00Z",
            },
            crew_caller_headers,
        )
        call = validate_success(resp, expected_status=201)
        assert is_valid_uuid(call["id"]), "719 rolling minutes leaves 1 minute of daily capacity; the call must be created"

    def test_hos_daily_boundary_720_rejected(self, api, crew_caller_headers):
        """PRD §3.7: "Creation runs its eligibility gates in band order: the
        member's `status` must be `AVAILABLE`, failing as
        `ERR_MEMBER_NOT_AVAILABLE`; the daily remaining allowance must be greater
        than zero — a member whose rolling accumulator has reached exactly 720 has
        none left — failing as `ERR_HOS_DAILY_LIMIT`; the monthly remaining
        allowance must likewise be greater than zero, failing as
        `ERR_HOS_MONTHLY_LIMIT`; and the member must be fully rested, meaning
        `rest_minutes_completed` unset or at least 600, failing as
        `ERR_HOS_REST_REQUIRED`."

        Design: Difficulty/boundary_precision_check/hos_daily_limit_719_vs_720
        """
        member = setup_member_with_accumulators(name="H. Conductor", rolling_24h_minutes=720)
        movement = _movement_target()
        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-03T06:00:00Z", "scheduled_end_at": "2026-05-03T18:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HOS_DAILY_LIMIT)


class TestGateOrdering:
    def test_crew_call_dual_failure_state_beats_hos(self, api, crew_caller_headers):
        """PRD §2.9: "Requests are evaluated against a fixed pipeline of
        validation bands, and the band order is part of the contract — a request
        that violates several rules always surfaces the error from the earliest
        band."
        PRD §2.9: "Fourth, state legality: the target resource must be in a state
        from which the requested transition is defined, failing as
        `ERR_INVALID_STATE` (HTTP 409) — or the more specific state errors
        `ERR_ORDER_NOT_AMENDABLE` and `ERR_MEMBER_NOT_AVAILABLE` where §3 names
        them. Fifth, business safety gates: hours-of-service limits, siding
        agreement activity, segment-in-service requirements, and FRA filing
        prerequisites."

        Design: Difficulty/priority_pair_validation_conflict/crew_call_state_error_beats_hos_safety_error
        """
        ctx = setup_movement_with_crew(symbol="GW-401", fra_class="CLASS_2")
        member = ctx["member"]
        # Drive the member ON_DUTY, then load the rolling accumulator to the cap.
        validate_success(api.report_crew_call_on_duty(ctx["call"]["id"], make_conductor_headers(member["id"])))
        current = validate_success(api.get_crew_member(member["id"], crew_caller_headers))
        assert current["status"] == "ON_DUTY"
        adjust_hos(member["id"], current["version"], rolling_24h_minutes=720)

        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": ctx["movement"]["id"],
                "scheduled_start_at": "2026-05-04T06:00:00Z", "scheduled_end_at": "2026-05-04T18:00:00Z",
            },
            crew_caller_headers,
        )
        err = validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_AVAILABLE)
        assert err["error_id"] == "ERR_MEMBER_NOT_AVAILABLE", (
            f"the state band (ON_DUTY member) precedes the safety band (720 rolling minutes); "
            f"got {err['error_id']}"
        )

    def test_crew_call_hos_daily_error_when_member_available(self, api, crew_caller_headers):
        """PRD §3.7: "Creation runs its eligibility gates in band order: the
        member's `status` must be `AVAILABLE`, failing as
        `ERR_MEMBER_NOT_AVAILABLE`; the daily remaining allowance must be greater
        than zero — a member whose rolling accumulator has reached exactly 720 has
        none left — failing as `ERR_HOS_DAILY_LIMIT`; the monthly remaining
        allowance must likewise be greater than zero, failing as
        `ERR_HOS_MONTHLY_LIMIT`; and the member must be fully rested, meaning
        `rest_minutes_completed` unset or at least 600, failing as
        `ERR_HOS_REST_REQUIRED`."

        Design: Difficulty/priority_pair_validation_conflict/crew_call_state_error_beats_hos_safety_error
        """
        member = setup_member_with_accumulators(name="F2. Engineer", craft="ENGINEER",
                                                rolling_24h_minutes=720)
        movement = _movement_target()
        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-04T06:00:00Z", "scheduled_end_at": "2026-05-04T18:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HOS_DAILY_LIMIT)


class TestHosMonthlyAndRest:
    def test_hos_monthly_limit_enforced(self, api, crew_caller_headers):
        """PRD §3.7: "the monthly remaining allowance must likewise be greater
        than zero, failing as `ERR_HOS_MONTHLY_LIMIT`"
        PRD §3.7: "Federal hours-of-service law caps a crew member at 720 minutes
        — twelve hours — on duty in any trailing 24-hour window, and at 16,560
        minutes — 276 hours — in the calendar month, and requires 600 minutes —
        ten hours — of completed rest before a new call."

        Design: Corner/validations/hos_monthly_limit_enforced
        """
        member = setup_member_with_accumulators(name="R. Conductor", month_minutes=16560)
        movement = _movement_target()
        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-03T06:00:00Z", "scheduled_end_at": "2026-05-03T12:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HOS_MONTHLY_LIMIT)

    def test_hos_rest_required_enforced(self, api, crew_caller_headers):
        """PRD §3.7: "and the member must be fully rested, meaning
        `rest_minutes_completed` unset or at least 600, failing as
        `ERR_HOS_REST_REQUIRED`."

        Design: Corner/validations/hos_rest_required_enforced
        """
        member = setup_member_with_accumulators(name="Q. Engineer", craft="ENGINEER",
                                                minutes_of_rest_completed=300)
        movement = _movement_target()
        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-03T06:00:00Z", "scheduled_end_at": "2026-05-03T12:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_HOS_REST_REQUIRED)


class TestHosOcc:
    def test_occ_adjust_hos_stale_version(self, api, crew_caller_headers):
        """PRD §2.8: "Correcting a crew member's hours-of-service accumulators
        through `POST /rail/crew-members/{id}/adjust-hos` requires the request to
        carry `expected_crew_member_version`, holding the member's `version` as
        the client last observed it. If the member's current `version` has
        advanced since — duty transitions in the interim legitimately changed the
        accumulators and the correction baseline is stale — the correction is
        rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_adjust_hos_stale_version
        """
        member = create_crew_member(name="W. Engineer", craft="ENGINEER")
        stale_version = member["version"]
        corrected = adjust_hos(member["id"], stale_version, rolling_24h_minutes=100)

        stale = api.adjust_crew_member_hos(
            member["id"],
            {"rolling_24h_minutes": 200, "expected_crew_member_version": stale_version},
            crew_caller_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh = adjust_hos(member["id"], corrected["version"], rolling_24h_minutes=200)
        assert fresh["on_duty_minutes_rolling_24h"] == 200, (
            f"the fresh-version correction must apply, got {fresh['on_duty_minutes_rolling_24h']}"
        )
        assert fresh["version"] == corrected["version"] + 1, (
            f"a successful correction increments the version: {corrected['version']} -> {fresh['version']}"
        )
