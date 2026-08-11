"""Lessons: negotiation cycle, coach gates, buffered-interval rule, fees."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_coach,
    get_lesson,
    get_member,
    make_coach_headers,
    make_member_headers,
    register_ready_member,
    request_lesson,
    set_clock,
    setup_requested_lesson,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestLessonCounterNegotiationCycle:
    def test_counter_cycle_status_and_proposed_start(self, api):
        """PRD §3.7: "The assigned coach may counter with a new
        `proposed_start_at`, moving the lesson to `COUNTERED`; the student may
        then counter back with their own `proposed_start_at`, returning it to
        `REQUESTED`; each counter overwrites `proposed_start_at`".
        PRD §3.7: "Two paths end the negotiation in `CONFIRMED`: the assigned
        coach confirms a `REQUESTED` lesson, or the student accepts a
        `COUNTERED` lesson at its currently proposed time."

        Design: Difficulty/non_linear_state_machine/lesson_counter_negotiation_cycle
        """
        set_clock("2026-05-01T08:00:00Z")
        coach, member, lesson = setup_requested_lesson(
            email="stu@x.com", proposed_start_at="2026-05-02T10:00:00Z"
        )

        countered = validate_success(
            api.counter_lesson(
                lesson["id"], {"proposed_start_at": "2026-05-02T14:00:00Z"},
                make_coach_headers(coach["id"]),
            ),
            200,
        )
        assert countered["status"] == "COUNTERED"
        assert countered["proposed_start_at"].startswith("2026-05-02T14:00:00")

        re_requested = validate_success(
            api.counter_lesson(
                lesson["id"], {"proposed_start_at": "2026-05-02T16:00:00Z"},
                make_member_headers(member["id"]),
            ),
            200,
        )
        assert re_requested["status"] == "REQUESTED", (
            "member re-counter cycles the lesson back to REQUESTED"
        )
        assert re_requested["proposed_start_at"].startswith("2026-05-02T16:00:00")

        confirmed = validate_success(
            api.confirm_lesson(lesson["id"], make_coach_headers(coach["id"])), 200
        )
        assert confirmed["status"] == "CONFIRMED"

    def test_counter_cycle_debits_fee_once_and_versions_increment(self, api):
        """PRD §3.7: "Both paths enforce the full gate set — the coach must be
        `ACTIVE`, the schedule must be clear under the buffered-interval rule
        below, and the member's `wallet_balance_cents` must cover `fee_cents`
        (`ERR_INSUFFICIENT_FUNDS`) — and both debit `fee_cents` from the
        member's wallet on success."
        PRD §2.4: "The `version` is an integer that starts at its initial value
        on creation and increments by one on every mutation of the resource".

        Design: Difficulty/non_linear_state_machine/lesson_counter_negotiation_cycle
        """
        set_clock("2026-05-01T08:00:00Z")
        coach, member, lesson = setup_requested_lesson(
            email="stu@x.com", proposed_start_at="2026-05-02T10:00:00Z"
        )
        assert lesson["fee_cents"] == 6000, "BASIC member, one-hour lesson"
        v0 = lesson["version"]

        countered = validate_success(
            api.counter_lesson(
                lesson["id"], {"proposed_start_at": "2026-05-02T14:00:00Z"},
                make_coach_headers(coach["id"]),
            ),
            200,
        )
        assert countered["version"] == v0 + 1
        re_requested = validate_success(
            api.counter_lesson(
                lesson["id"], {"proposed_start_at": "2026-05-02T16:00:00Z"},
                make_member_headers(member["id"]),
            ),
            200,
        )
        assert re_requested["version"] == v0 + 2
        # No wallet movement during the negotiation cycle.
        assert get_member(member["id"])["wallet_balance_cents"] == 10000

        confirmed = validate_success(
            api.confirm_lesson(lesson["id"], make_coach_headers(coach["id"])), 200
        )
        assert confirmed["version"] == v0 + 3
        assert get_member(member["id"])["wallet_balance_cents"] == 4000, (
            "a single 6000 debit lands at CONFIRMED entry"
        )


class TestLessonCoachGates:
    def _setup_requested_then_deactivate(self, api):
        set_clock("2026-05-01T08:00:00Z")
        coach, member, lesson = setup_requested_lesson(
            email="lg@x.com", disciplines=("RECURVE", "COMPOUND"),
            proposed_start_at="2026-05-02T10:00:00Z",
        )
        validate_success(api.deactivate_coach(coach["id"], ADMIN), 200)
        return coach, member, lesson

    def test_lesson_confirm_blocked_while_coach_inactive(self, api):
        """PRD §3.7: "while `INACTIVE`, a coach may not confirm, counter, or
        have lessons accepted — attempts are rejected with
        `ERR_COACH_INACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/lesson_confirm_gated_by_coach_state
        """
        coach, member, lesson = self._setup_requested_then_deactivate(api)
        resp = api.confirm_lesson(lesson["id"], make_coach_headers(coach["id"]))
        validate_error(resp, ApiErrorId.ERR_COACH_INACTIVE)
        assert get_lesson(lesson["id"])["status"] == "REQUESTED"

    def test_inactive_coach_confirm_debits_no_fee(self, api):
        """PRD §3.7: "while `INACTIVE`, a coach may not confirm, counter, or
        have lessons accepted — attempts are rejected with
        `ERR_COACH_INACTIVE`."
        PRD §3.7: "both debit `fee_cents` from the member's wallet on success."

        Design: Difficulty/cross_entity_state_dependency/lesson_confirm_gated_by_coach_state
        """
        coach, member, lesson = self._setup_requested_then_deactivate(api)
        resp = api.confirm_lesson(lesson["id"], make_coach_headers(coach["id"]))
        validate_error(resp, ApiErrorId.ERR_COACH_INACTIVE)
        assert get_member(member["id"])["wallet_balance_cents"] == 10000, (
            "a rejected confirmation must not debit the fee"
        )


class TestCoachBufferedInterval:
    def _setup_confirmed_a_and_pending(self, api):
        """Coach with CONFIRMED lesson A 10:00-11:00; lesson B requested at
        11:15 (exact 15-minute gap); lesson C requested at 11:14 (14-minute
        gap)."""
        set_clock("2026-05-01T08:00:00Z")
        coach = create_coach(full_name="Coach Bo", disciplines=("RECURVE",))
        member = register_ready_member("buf@x.com", wallet_cents=20000)
        lesson_a = request_lesson(
            member["id"], coach["id"], "RECURVE", "2026-05-02T10:00:00Z"
        )
        validate_success(
            api.confirm_lesson(lesson_a["id"], make_coach_headers(coach["id"])), 200
        )
        lesson_b = request_lesson(
            member["id"], coach["id"], "RECURVE", "2026-05-02T11:15:00Z"
        )
        lesson_c = request_lesson(
            member["id"], coach["id"], "RECURVE", "2026-05-02T11:14:00Z"
        )
        return coach, member, lesson_a, lesson_b, lesson_c

    def test_exact_fifteen_minute_gap_confirms(self, api):
        """PRD §3.7: "confirming or accepting a lesson is rejected with
        `ERR_COACH_OVERLAP` if it would leave less than fifteen minutes of gap,
        on either side, to another `CONFIRMED` lesson of the same coach."

        Design: Difficulty/resource_temporal_overlap/coach_buffered_interval_exact_gap
        """
        coach, member, lesson_a, lesson_b, _ = self._setup_confirmed_a_and_pending(api)
        # Exactly fifteen minutes of gap is NOT "less than fifteen minutes".
        confirmed = validate_success(
            api.confirm_lesson(lesson_b["id"], make_coach_headers(coach["id"])), 200
        )
        assert confirmed["status"] == "CONFIRMED"

    def test_fourteen_minute_gap_rejected_coach_overlap(self, api):
        """PRD §3.7: "confirming or accepting a lesson is rejected with
        `ERR_COACH_OVERLAP` if it would leave less than fifteen minutes of gap,
        on either side, to another `CONFIRMED` lesson of the same coach."

        Design: Difficulty/resource_temporal_overlap/coach_buffered_interval_exact_gap
        """
        coach, member, lesson_a, lesson_b, lesson_c = (
            self._setup_confirmed_a_and_pending(api)
        )
        validate_success(
            api.confirm_lesson(lesson_b["id"], make_coach_headers(coach["id"])), 200
        )
        resp = api.confirm_lesson(lesson_c["id"], make_coach_headers(coach["id"]))
        validate_error(resp, ApiErrorId.ERR_COACH_OVERLAP)
        assert get_lesson(lesson_c["id"])["status"] == "REQUESTED"
        # Only lessons A and B debited 6000 each.
        assert get_member(member["id"])["wallet_balance_cents"] == 8000


class TestLessonFeeAndCompletion:
    def test_lesson_fee_elite_tier_discount(self, api):
        """PRD §3.7: "The `fee_cents` is computed at request time: 6000 cents
        per hour times the duration in hours — `duration_minutes` divided by 60
        rounded up to a whole number — times one minus the member's tier
        discount, the product rounded half up."
        PRD §3.7: "both debit `fee_cents` from the member's wallet on success."

        Design: Corner/calculations/lesson_fee_elite_tier_discount
        """
        set_clock("2026-05-01T08:00:00Z")
        coach, member, lesson = setup_requested_lesson(
            email="elite@x.com", tier="ELITE",
            proposed_start_at="2026-05-02T10:00:00Z",
        )
        # round_half_up(6000 x 1 x 0.8) = 4800.
        assert lesson["fee_cents"] == 4800

        validate_success(
            api.confirm_lesson(lesson["id"], make_coach_headers(coach["id"])), 200
        )
        assert get_member(member["id"])["wallet_balance_cents"] == 5200

    def test_lesson_complete_before_start_rejected(self, api):
        """PRD §3.7: "A `CONFIRMED` lesson is completed by its coach once the
        logical clock has reached `proposed_start_at` (completing earlier is
        `ERR_LESSON_NOT_ACTIONABLE`), moving to terminal `COMPLETED`."

        Design: Corner/state_machines/lesson_complete_before_start_rejected
        """
        set_clock("2026-05-01T08:00:00Z")
        coach, member, lesson = setup_requested_lesson(
            email="early@x.com", disciplines=("COMPOUND",), discipline="COMPOUND",
            proposed_start_at="2026-05-02T10:00:00Z",
        )
        validate_success(
            api.confirm_lesson(lesson["id"], make_coach_headers(coach["id"])), 200
        )
        # Clock is still 2026-05-01, before the 2026-05-02 proposed start.
        resp = api.complete_lesson(lesson["id"], make_coach_headers(coach["id"]))
        validate_error(resp, ApiErrorId.ERR_LESSON_NOT_ACTIONABLE)
        assert get_lesson(lesson["id"])["status"] == "CONFIRMED"


class TestCoachOwnership:
    def test_coach_cannot_confirm_others_lesson(self, api):
        """PRD §2.1: "lesson actions that are reserved to the assigned coach
        compare `X-User-ID` to the lesson's `coach_id`, and a mismatch is
        likewise `ERR_UNAUTHORIZED`."
        PRD §3.7: "only the lesson's own coach (identity equal to `coach_id`) or
        its own student may play their side (`ERR_UNAUTHORIZED` otherwise,
        `ERR_COACH_INACTIVE` while the coach is inactive)".

        Design: Corner/rbac/coach_cannot_confirm_others_lesson
        """
        set_clock("2026-05-01T08:00:00Z")
        coach1 = create_coach(full_name="Coach One", disciplines=("RECURVE",))
        coach2 = create_coach(full_name="Coach Two", disciplines=("RECURVE",))
        member = register_ready_member("rbac2@x.com", wallet_cents=10000)
        lesson = request_lesson(
            member["id"], coach1["id"], "RECURVE", "2026-05-02T10:00:00Z"
        )

        resp = api.confirm_lesson(lesson["id"], make_coach_headers(coach2["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert get_lesson(lesson["id"])["status"] == "REQUESTED"
        assert get_member(member["id"])["wallet_balance_cents"] == 10000
