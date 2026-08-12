"""Crew call lifecycle: duty/rest cycle with the clock sweep, member-state
gating, half-open window overlap, target shape, and caller identity
(PRD §2.1, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_crew_call_for_movement,
    create_crew_member,
    create_movement,
    create_segment,
    is_valid_uuid,
    make_conductor_headers,
    set_clock,
    setup_movement_with_crew,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CALLER = TEST_USERS["crew_caller_headers"]


def _duty_cycle_to_relieve(api, member, call, caller_headers):
    """Report at 06:00, relieve at 16:00: a 600-minute duty (PRD §3.7)."""
    set_clock("2026-05-01T06:00:00Z")
    validate_success(api.report_crew_call_on_duty(call["id"], make_conductor_headers(member["id"])))
    set_clock("2026-05-01T16:00:00Z")
    return validate_success(api.relieve_crew_call(call["id"], caller_headers))


class TestDutyRestCycle:
    def test_crew_duty_relieve_posts_minutes_and_rest(self, api, crew_caller_headers):
        """PRD §3.7: "Relief is a `CrewCaller` action on an `ON_DUTY` call:
        `off_duty_at` is stamped, `actual_on_duty_minutes` is computed as the
        whole minutes between `on_duty_at` and `off_duty_at` with any partial
        minute discarded, the call reaches the terminal `RELIEVED`, and the
        member moves from `ON_DUTY` to `RESTING` — both accumulators increased by
        the call's `actual_on_duty_minutes`, `rest_minutes_completed` set to zero,
        and `rest_start_at` stamped from the clock."

        Design: Difficulty/non_linear_state_machine/crew_member_duty_rest_cycle
        """
        ctx = setup_movement_with_crew(
            symbol="GW-201", start="2026-05-01T06:00:00Z", end="2026-05-01T16:00:00Z"
        )
        call = _duty_cycle_to_relieve(api, ctx["member"], ctx["call"], crew_caller_headers)
        assert call["actual_on_duty_minutes"] == 600, (
            f"06:00 -> 16:00 must compute 600 whole minutes, got {call['actual_on_duty_minutes']}"
        )
        assert call["status"] == "RELIEVED"
        member = validate_success(api.get_crew_member(ctx["member"]["id"], crew_caller_headers))
        assert member["status"] == "RESTING", (
            f"relief must move the member ON_DUTY -> RESTING, got {member['status']}"
        )
        assert member["rest_start_at"] is not None, "rest_start_at must be stamped from the clock at relieve"

    def test_crew_rest_sweep_returns_member_available(self, api, crew_caller_headers):
        """PRD §3.7: "Rest completes by the clock: on every clock advance, the
        rest sweep returns each `RESTING` member whose `rest_start_at` lies at
        least 600 minutes in the past to `AVAILABLE`, unsetting both rest fields."
        PRD §3.7: "A computed `hos_available_minutes`, visible on every member
        read, is the smaller of the two remaining allowances — 720 minutes minus
        the rolling accumulator, and 16,560 minutes minus the month accumulator —
        each floored at zero before the comparison."

        Design: Difficulty/non_linear_state_machine/crew_member_duty_rest_cycle
        """
        ctx = setup_movement_with_crew(
            symbol="GW-201", start="2026-05-01T06:00:00Z", end="2026-05-01T16:00:00Z"
        )
        _duty_cycle_to_relieve(api, ctx["member"], ctx["call"], crew_caller_headers)

        set_clock("2026-05-02T02:00:00Z")  # exactly 600 minutes after the 16:00 relieve
        member = validate_success(api.get_crew_member(ctx["member"]["id"], crew_caller_headers))
        assert member["status"] == "AVAILABLE", (
            f"after exactly 600 rest minutes the sweep must return the member to AVAILABLE, "
            f"got {member['status']}"
        )
        assert member["rest_minutes_completed"] is None, "the sweep must unset rest_minutes_completed"
        assert member["hos_available_minutes"] == 120, (
            f"min(720-600, 16560-600) must yield 120 after a 600-minute duty, "
            f"got {member['hos_available_minutes']}"
        )


class TestMemberStateGate:
    def test_crew_call_rejected_when_member_resting(self, api, crew_caller_headers):
        """PRD §3.7: "Creation runs its eligibility gates in band order: the
        member's `status` must be `AVAILABLE`, failing as
        `ERR_MEMBER_NOT_AVAILABLE`; the daily remaining allowance must be greater
        than zero — a member whose rolling accumulator has reached exactly 720 has
        none left — failing as `ERR_HOS_DAILY_LIMIT`; the monthly remaining
        allowance must likewise be greater than zero, failing as
        `ERR_HOS_MONTHLY_LIMIT`; and the member must be fully rested, meaning
        `rest_minutes_completed` unset or at least 600, failing as
        `ERR_HOS_REST_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/crew_call_requires_available_member
        """
        ctx = setup_movement_with_crew(
            symbol="GW-601", start="2026-05-02T06:00:00Z", end="2026-05-02T12:00:00Z"
        )
        member = ctx["member"]
        validate_success(api.report_crew_call_on_duty(ctx["call"]["id"], make_conductor_headers(member["id"])))
        validate_success(api.relieve_crew_call(ctx["call"]["id"], crew_caller_headers))

        resting = validate_success(api.get_crew_member(member["id"], crew_caller_headers))
        assert resting["status"] == "RESTING", f"member must be RESTING after a full duty, got {resting['status']}"

        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": ctx["movement"]["id"],
                "scheduled_start_at": "2026-05-05T06:00:00Z", "scheduled_end_at": "2026-05-05T12:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_AVAILABLE)

    def test_crew_call_rejected_when_member_on_duty(self, api, crew_caller_headers):
        """PRD §3.7: "Creation runs its eligibility gates in band order: the
        member's `status` must be `AVAILABLE`, failing as
        `ERR_MEMBER_NOT_AVAILABLE`; the daily remaining allowance must be greater
        than zero — a member whose rolling accumulator has reached exactly 720 has
        none left — failing as `ERR_HOS_DAILY_LIMIT`; the monthly remaining
        allowance must likewise be greater than zero, failing as
        `ERR_HOS_MONTHLY_LIMIT`; and the member must be fully rested, meaning
        `rest_minutes_completed` unset or at least 600, failing as
        `ERR_HOS_REST_REQUIRED`."

        Design: Difficulty/cross_entity_state_dependency/crew_call_requires_available_member
        """
        ctx = setup_movement_with_crew(
            symbol="GW-602", start="2026-05-02T06:00:00Z", end="2026-05-02T12:00:00Z"
        )
        member = ctx["member"]
        validate_success(api.report_crew_call_on_duty(ctx["call"]["id"], make_conductor_headers(member["id"])))
        on_duty = validate_success(api.get_crew_member(member["id"], crew_caller_headers))
        assert on_duty["status"] == "ON_DUTY"

        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": ctx["movement"]["id"],
                "scheduled_start_at": "2026-05-05T06:00:00Z", "scheduled_end_at": "2026-05-05T12:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MEMBER_NOT_AVAILABLE)


class TestCallWindowOverlap:
    def test_crew_call_adjacent_window_allowed(self, api, crew_caller_headers):
        """PRD §3.7: "After the safety gates, the window rule: the half-open
        window from `scheduled_start_at` up to but not including
        `scheduled_end_at` must not overlap any existing call of the same member
        in `CALLED`, `ACCEPTED`, or `ON_DUTY`; mere adjacency — a new call
        starting exactly when an existing one ends — is permitted. An overlap is
        rejected with `ERR_CALL_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_call_half_open_window_overlap
        """
        ctx = setup_movement_with_crew(
            symbol="GW-801", start="2026-05-02T06:00:00Z", end="2026-05-02T18:00:00Z", respond=False
        )
        member, movement = ctx["member"], ctx["movement"]
        assert ctx["call"]["status"] == "CALLED"

        adjacent = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-02T18:00:00Z", "scheduled_end_at": "2026-05-03T06:00:00Z",
            },
            crew_caller_headers,
        )
        call2 = validate_success(adjacent, expected_status=201)
        assert is_valid_uuid(call2["id"]), (
            "a call starting exactly when the existing one ends is adjacency, not overlap"
        )

    def test_crew_call_overlapping_window_rejected(self, api, crew_caller_headers):
        """PRD §3.7: "After the safety gates, the window rule: the half-open
        window from `scheduled_start_at` up to but not including
        `scheduled_end_at` must not overlap any existing call of the same member
        in `CALLED`, `ACCEPTED`, or `ON_DUTY`; mere adjacency — a new call
        starting exactly when an existing one ends — is permitted. An overlap is
        rejected with `ERR_CALL_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/crew_call_half_open_window_overlap
        """
        ctx = setup_movement_with_crew(
            symbol="GW-801", start="2026-05-02T06:00:00Z", end="2026-05-02T18:00:00Z", respond=False
        )
        member, movement = ctx["member"], ctx["movement"]

        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-02T17:00:00Z", "scheduled_end_at": "2026-05-03T05:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CALL_WINDOW_OVERLAP)


class TestCallTargetAndIdentity:
    def test_crew_call_target_required(self, api, crew_caller_headers):
        """PRD §3.7: "A `CrewCaller` creates a **CrewCall** naming the
        `crew_member_id`, a planned duty window from `scheduled_start_at` to
        `scheduled_end_at` with the end strictly later than the start, and exactly
        one duty target: a `movement_id` for a train or a `switch_job_id` for a
        switching job. Supplying both targets, or neither, is refused with
        `ERR_CALL_TARGET_REQUIRED`."

        Design: Corner/validations/crew_call_target_required
        """
        member = create_crew_member(name="P. Conductor")
        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"],
                "scheduled_start_at": "2026-05-03T06:00:00Z", "scheduled_end_at": "2026-05-03T12:00:00Z",
            },
            crew_caller_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CALL_TARGET_REQUIRED)

    def test_conductor_cannot_create_crew_calls(self, api):
        """PRD §2.1: "Authorization is per-endpoint: a caller whose role is not in
        the endpoint's authorized list, or whose entity-backed identity does not
        match the targeted resource, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP
        403)."
        PRD §4: "| POST | `/rail/crew-calls` | Call a crew member for duty | CrewCaller |"

        Design: Corner/rbac/conductor_cannot_create_crew_calls
        """
        member = create_crew_member(name="T. Conductor")
        segment = create_segment(name="Main MP 63-64", milepost_start=63, milepost_end=64)
        movement = create_movement([segment["id"]], symbol="GW-908")
        resp = api.create_crew_call(
            {
                "crew_member_id": member["id"], "movement_id": movement["id"],
                "scheduled_start_at": "2026-05-03T06:00:00Z", "scheduled_end_at": "2026-05-03T12:00:00Z",
            },
            make_conductor_headers(member["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_wrong_conductor_cannot_respond_to_call(self, api, dispatcher_headers):
        """PRD §3.7: "Answering a call belongs to the called crew member alone,
        acting under the `Conductor` role with the identity check of §2.1 — the
        call's `crew_member_id` must equal the caller's `X-User-ID`, else
        `ERR_FORBIDDEN_ROLE`."
        PRD §2.1: "When `X-User-Role` is `Conductor`, `X-User-ID` is the `id` of
        the acting `CrewMember`; ownership checks on a crew call compare the
        call's `crew_member_id` to `X-User-ID`, so a conductor may answer or
        report on duty only for their own calls."

        Design: Corner/rbac/wrong_conductor_cannot_respond_to_call
        """
        member_a = create_crew_member(name="U. Conductor")
        member_b = create_crew_member(name="V. Conductor")
        segment = create_segment(name="Main MP 65-66", milepost_start=65, milepost_end=66)
        movement = create_movement([segment["id"]], symbol="GW-909")
        call = create_crew_call_for_movement(member_a["id"], movement["id"],
                                             start="2026-05-03T06:00:00Z", end="2026-05-03T12:00:00Z")

        resp = api.respond_crew_call(call["id"], {"response": "ACCEPTED"}, make_conductor_headers(member_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        reread = validate_success(api.get_crew_call(call["id"], dispatcher_headers))
        assert reread["status"] == "CALLED", (
            f"a forbidden respond must leave the call CALLED, got {reread['status']}"
        )
