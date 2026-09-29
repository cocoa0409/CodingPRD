"""Account-takeover scoring, the step-up challenge axis and containment.

Containment is the widest cascade in the domain: it locks the account, force
declines every order sitting in review and closes the cases those orders own.
"""

from __future__ import annotations

from test_helpers import (
    ADMIN,
    CHECKOUT,
    AccountStatus,
    ApiClient,
    ApiErrorId,
    AssessmentState,
    AtoPosture,
    AuthOutcome,
    CHALLENGE_TTL_SECONDS,
    CLOCK_EPOCH,
    CaseState,
    ChallengeAction,
    ChallengeMethod,
    ChallengeState,
    Decision,
    DecisionReason,
    FinalDisposition,
    LARGE_ORDER_CENTS,
    LockedReason,
    MAX_CHALLENGE_ATTEMPTS,
    SMALL_ORDER_CENTS,
    assert_score,
    build_approved_assessment,
    build_scoring_env,
    build_staffed_case,
    build_step_up_event,
    challenge_payload,
    clear_ato_payload,
    contain_customer_via_third_failure,
    create_customer,
    create_device,
    drive_challenge,
    fail_challenge_then_reissue,
    lock_customer,
    parse_instant,
    plus_seconds,
    read_analyst,
    read_assessment,
    read_auth_event,
    read_case,
    read_customer,
    set_clock,
    set_clock_payload,
    unlock_customer,
    validate_error,
    validate_success,
)

#: Fifteen minutes after the epoch, which is where a step-up challenge lapses.
CHALLENGE_DEADLINE = plus_seconds(CLOCK_EPOCH, CHALLENGE_TTL_SECONDS)

#: One second short of that deadline.
ONE_SECOND_BEFORE_DEADLINE = plus_seconds(CHALLENGE_DEADLINE, -1)


class TestParallelPostureAxes:
    """``account_status`` and ``ato_posture`` move independently of each other."""

    def test_a_step_up_event_moves_the_takeover_axis_on_a_locked_account(
        self, api: ApiClient
    ) -> None:
        """An administrative lock does not stop the takeover axis reaching WATCH.

        PRD: "A customer carries **two independent posture axes on the same row**,
        and neither constrains the other's transition set."
        PRD: "A `STEP_UP_REQUIRED` event sets `challenge_method` to `OTP_SMS` and
        `challenge_expires_at` to fifteen minutes — 900 seconds — after the current
        instant, and moves the customer's `ato_posture` `CLEAR → WATCH`,
        incrementing the customer's `version`."

        Design: Difficulty/non_linear_state_machine/customer_parallel_axes_progress_independently
        """
        env = build_scoring_env(api)
        locked = lock_customer(api, env.customer_id, reason="manual review hold")
        assert locked["account_status"] == AccountStatus.LOCKED
        assert locked["ato_posture"] == AtoPosture.CLEAR, (
            "locking the account leaves the takeover axis untouched"
        )
        assert locked["locked_reason"] == "manual review hold"

        event = build_step_up_event(api, env.customer_id, env.device_id)
        assert_score(event["ato_score"], 70.00, "ato_score")
        assert event["device_first_seen_for_customer"] is True
        assert event["outcome"] == AuthOutcome.STEP_UP_REQUIRED
        assert event["challenge_state"] == ChallengeState.ISSUED
        assert event["challenge_method"] == ChallengeMethod.OTP_SMS
        assert parse_instant(event["challenge_expires_at"]) == parse_instant(
            plus_seconds(CLOCK_EPOCH, CHALLENGE_TTL_SECONDS)
        ), "the challenge expires fifteen minutes after the current instant"

        customer = read_customer(api, env.customer_id)
        assert customer["account_status"] == AccountStatus.LOCKED
        assert customer["ato_posture"] == AtoPosture.WATCH

    def test_unlocking_the_account_leaves_the_takeover_axis_where_it_was(
        self, api: ApiClient
    ) -> None:
        """The account-status axis is cyclic while ``ato_posture`` stays at WATCH.

        PRD: "`LOCKED → ACTIVE` clears `locked_reason` back to null, recomputes
        `good_customer_flag`, and increments `version` — making the account-status
        axis cyclic."
        PRD: "A single cascade may move both in one request, but each axis is
        separately reachable and separately cleared."

        Design: Difficulty/non_linear_state_machine/customer_parallel_axes_progress_independently
        """
        env = build_scoring_env(api)
        lock_customer(api, env.customer_id)
        build_step_up_event(api, env.customer_id, env.device_id)

        unlocked = unlock_customer(api, env.customer_id)
        assert unlocked["account_status"] == AccountStatus.ACTIVE
        assert unlocked["locked_reason"] is None
        assert unlocked["ato_posture"] == AtoPosture.WATCH, (
            "clearing the account-status axis does not clear the takeover axis"
        )
        assert unlocked["good_customer_flag"] is False, (
            "the account has no approved orders, so the flag stays false"
        )


class TestContainmentCascade:
    """The third challenge failure contains the account and clears its reviews."""

    def test_third_failure_contains_the_account_and_locks_it(
        self, api: ApiClient
    ) -> None:
        """Attempt three carries WATCH to CONTAINED and forces the lock.

        PRD: "`ISSUED → FAILED` increments the event's `challenge_attempts` by one
        and the customer's `failed_login_count` by one. When that increment carries
        `challenge_attempts` to 3 — the attempt budget — it is the **first link of
        the containment chain**: the customer's `ato_posture` moves
        `WATCH → CONTAINED`, firing the remaining links."
        PRD: "`account_status` is forced to `LOCKED` with `locked_reason` set to
        `ATO_CONTAINMENT`."

        Design: Difficulty/transitive_cascade/ato_containment_auto_declines_in_review_orders
        """
        env = build_scoring_env(api)
        build_approved_assessment(api, env, SMALL_ORDER_CENTS)

        event = build_step_up_event(api, env.customer_id, env.device_id)
        assert event["device_first_seen_for_customer"] is False, (
            "the earlier order already pairs this customer with this device"
        )
        assert_score(event["ato_score"], 50.00, "ato_score")
        assert event["outcome"] == AuthOutcome.STEP_UP_REQUIRED

        fail_challenge_then_reissue(api, event["id"])
        fail_challenge_then_reissue(api, event["id"])
        third = drive_challenge(api, event["id"], ChallengeAction.FAIL)

        assert third["challenge_attempts"] == MAX_CHALLENGE_ATTEMPTS
        assert third["challenge_state"] == ChallengeState.FAILED
        assert read_auth_event(api, event["id"])["outcome"] == (
            AuthOutcome.STEP_UP_REQUIRED
        ), "the event's outcome is frozen by the original score"

        customer = read_customer(api, env.customer_id)
        assert customer["failed_login_count"] == MAX_CHALLENGE_ATTEMPTS
        assert customer["ato_posture"] == AtoPosture.CONTAINED
        assert customer["account_status"] == AccountStatus.LOCKED
        assert customer["locked_reason"] == LockedReason.ATO_CONTAINMENT
        assert customer["good_customer_flag"] is False

    def test_containment_force_declines_the_orders_sitting_in_review(
        self, api: ApiClient
    ) -> None:
        """An IN_REVIEW order and its ASSIGNED case are both closed by containment.

        PRD: "Every one of that customer's assessments currently in state
        `IN_REVIEW` moves to `DECIDED_DECLINE` with `decision_reason`
        `ATO_CONTAINMENT` and `final_disposition` `DECLINED`, and the customer's
        `declined_count` rises by one **per assessment** so moved."
        PRD: "Each such assessment's review case moves to `RESOLVED_DECLINE`, and
        where that case had a non-null `assigned_analyst_id`, that analyst's
        `open_case_count` is decremented by one and their `version` incremented by
        one."

        Design: Difficulty/transitive_cascade/ato_containment_auto_declines_in_review_orders
        """
        env = build_scoring_env(api)
        staffed = build_staffed_case(api, env, LARGE_ORDER_CENTS)
        assert staffed.case["state"] == CaseState.ASSIGNED

        contain_customer_via_third_failure(api, env.customer_id, env.device_id)

        assessment = read_assessment(api, staffed.assessment["id"])
        assert assessment["state"] == AssessmentState.DECIDED_DECLINE
        assert assessment["decision_reason"] == DecisionReason.ATO_CONTAINMENT
        assert assessment["final_disposition"] == FinalDisposition.DECLINED
        assert assessment["decision"] == Decision.REVIEW, (
            "the decision set at scoring is frozen and is not rewritten here"
        )

        case = read_case(api, staffed.case_id)
        assert case["state"] == CaseState.RESOLVED_DECLINE
        assert case["resolved_at"] is not None
        assert case["resolved_late"] is False

        analyst = read_analyst(api, staffed.analyst_id)
        assert analyst["open_case_count"] == 0, (
            "the analyst who held the contained case is released"
        )
        assert analyst["resolved_case_count"] == 0, (
            "a containment close is not credited to the analyst as a resolution"
        )

        customer = read_customer(api, env.customer_id)
        assert customer["declined_count"] == 1
        assert customer["ato_posture"] == AtoPosture.CONTAINED
        assert customer["lifetime_net_approved_cents"] == 0, (
            "an order that never left review never entered the ledger"
        )


class TestPostureClearIsGuardedByTheCurrentPosture:
    """Clearing the takeover axis requires the axis to be CONTAINED first."""

    def test_clearing_a_posture_that_is_already_clear_is_refused(
        self, api: ApiClient
    ) -> None:
        """CLEAR on a CLEAR account is not a declared transition, so nothing is reset.

        PRD: "Four transitions are declared, and any other requested pair is rejected
        with `ERR_CUSTOMER_POSTURE_INVALID`; in particular nothing leaves `CLOSED`, and
        asking for `ato_posture` `CLEAR` on an account already `CLEAR` is not a declared
        transition."
        PRD: "`CONTAINED → CLEAR` sets `failed_login_count` back to zero and increments
        `version`."

        Design: Corner/state_machines/posture_clear_to_clear_precondition_rejected
        """
        set_clock(api)
        customer = create_customer(api, email="posture@example.com", home_country="US")
        assert customer["ato_posture"] == AtoPosture.CLEAR
        assert customer["failed_login_count"] == 0
        assert int(customer["version"]) == 1

        response = api.set_customer_posture(
            customer["id"], clear_ato_payload(), ADMIN
        )
        validate_error(response, ApiErrorId.ERR_CUSTOMER_POSTURE_INVALID, 409)

        unchanged = read_customer(api, customer["id"])
        assert unchanged["ato_posture"] == AtoPosture.CLEAR
        assert int(unchanged["version"]) == 1, (
            "a refused posture request is not a mutation"
        )
        assert unchanged["account_status"] == AccountStatus.ACTIVE


class TestChallengeGatesRunInTheirDeclaredOrder:
    """The state gate is read before the deadline gate, and the deadline is inclusive."""

    @staticmethod
    def _issue_step_up(api: ApiClient) -> tuple:
        """A fresh customer on a fresh device, holding one ISSUED step-up challenge."""
        set_clock(api, CLOCK_EPOCH)
        customer = create_customer(api, email="challenge@example.com", home_country="US")
        device = create_device(api, tz_offset_minutes=0)
        event = build_step_up_event(api, customer["id"], device["id"])

        assert_score(event["ato_score"], 70.00, "ato_score")
        assert event["outcome"] == AuthOutcome.STEP_UP_REQUIRED
        assert event["challenge_state"] == ChallengeState.ISSUED
        assert event["challenge_method"] == ChallengeMethod.OTP_SMS
        assert parse_instant(event["challenge_expires_at"]) == parse_instant(
            CHALLENGE_DEADLINE
        )
        assert read_customer(api, customer["id"])["ato_posture"] == AtoPosture.WATCH
        return customer, event

    def test_expiring_one_second_early_is_refused_but_the_deadline_itself_is_not(
        self, api: ApiClient
    ) -> None:
        """EXPIRE is inclusive at the deadline and leaves the WATCH posture in place.

        PRD: "for `EXPIRE`, the clock must be at or after `challenge_expires_at`,
        otherwise `ERR_CHALLENGE_NOT_EXPIRED`"
        PRD: "`ISSUED → EXPIRED` has no customer-side effect at all: `ato_posture` stays
        at `WATCH` and `failed_login_count` is unchanged."

        Design: Corner/errors/challenge_expire_before_ttl_rejected_but_allowed_at_the_boundary
        """
        customer, event = self._issue_step_up(api)

        set_clock(api, ONE_SECOND_BEFORE_DEADLINE)
        early = api.challenge(
            event["id"], challenge_payload(ChallengeAction.EXPIRE), CHECKOUT
        )
        validate_error(early, ApiErrorId.ERR_CHALLENGE_NOT_EXPIRED, 409)
        assert read_auth_event(api, event["id"])["challenge_state"] == (
            ChallengeState.ISSUED
        ), "a refused EXPIRE does not advance the challenge"

        validate_success(
            api.set_clock(set_clock_payload(CHALLENGE_DEADLINE), ADMIN), 200
        )
        lapsed = validate_success(
            api.challenge(
                event["id"], challenge_payload(ChallengeAction.EXPIRE), CHECKOUT
            ),
            200,
        )
        assert lapsed["challenge_state"] == ChallengeState.EXPIRED, (
            "the deadline instant itself is at or after challenge_expires_at"
        )
        after = read_customer(api, customer["id"])
        assert after["ato_posture"] == AtoPosture.WATCH, (
            "letting the challenge lapse does not clear the takeover axis"
        )
        assert after["failed_login_count"] == 0

    def test_passing_a_challenge_that_already_failed_reports_the_state_not_the_clock(
        self, api: ApiClient
    ) -> None:
        """Inside a live TTL the FAILED state is what refuses the PASS.

        PRD: "the current `challenge_state` must permit the action — `PASS`, `FAIL` and
        `EXPIRE` all require `ISSUED` and `REISSUE` requires `FAILED`, otherwise
        `ERR_CHALLENGE_STATE_INVALID`"
        PRD: "`ISSUED → FAILED` increments the event's `challenge_attempts` by one and
        the customer's `failed_login_count` by one."

        Design: Corner/errors/challenge_pass_from_failed_state_rejected
        """
        customer, event = self._issue_step_up(api)

        failed = drive_challenge(api, event["id"], ChallengeAction.FAIL)
        assert failed["challenge_state"] == ChallengeState.FAILED
        assert failed["challenge_attempts"] == 1
        assert read_customer(api, customer["id"])["failed_login_count"] == 1

        response = api.challenge(
            event["id"], challenge_payload(ChallengeAction.PASS), CHECKOUT
        )
        validate_error(response, ApiErrorId.ERR_CHALLENGE_STATE_INVALID, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.ERR_CHALLENGE_EXPIRED, (
            "the clock is still well before the deadline, so the state gate answers"
        )

        unchanged = read_auth_event(api, event["id"])
        assert unchanged["challenge_state"] == ChallengeState.FAILED
        assert unchanged["challenge_attempts"] == 1, (
            "a refused PASS neither advances nor rolls back the attempt count"
        )

        after = read_customer(api, customer["id"])
        assert after["failed_login_count"] == 1, (
            "the count earned by the FAIL is not rolled back"
        )
        assert after["ato_posture"] == AtoPosture.WATCH
        assert after["account_status"] == AccountStatus.ACTIVE, (
            "one failure is short of the attempt budget, so nothing is contained"
        )

    def test_passing_at_the_deadline_is_refused_and_the_posture_stays_at_watch(
        self, api: ApiClient
    ) -> None:
        """A lapsed step-up can never be retro-satisfied, even while still ISSUED.

        PRD: "for `PASS`, `FAIL` and `REISSUE`, the clock must still be strictly before
        `challenge_expires_at`, otherwise `ERR_CHALLENGE_EXPIRED`"
        PRD: "`ISSUED → PASSED` sets the customer's `failed_login_count` back to 0 and
        moves `ato_posture` `WATCH → CLEAR`, incrementing the customer's `version`."

        Design: Corner/errors/challenge_pass_after_ttl_expiry_rejected
        """
        customer, event = self._issue_step_up(api)
        before = read_customer(api, customer["id"])

        validate_success(
            api.set_clock(set_clock_payload(CHALLENGE_DEADLINE), ADMIN), 200
        )
        response = api.challenge(
            event["id"], challenge_payload(ChallengeAction.PASS), CHECKOUT
        )
        validate_error(response, ApiErrorId.ERR_CHALLENGE_EXPIRED, 409)

        stalled = read_auth_event(api, event["id"])
        assert stalled["challenge_state"] == ChallengeState.ISSUED, (
            "the refused PASS does not advance the challenge"
        )

        after = read_customer(api, customer["id"])
        assert after["ato_posture"] == AtoPosture.WATCH, (
            "the WATCH posture is not cleared by a PASS that arrived too late"
        )
        assert after["failed_login_count"] == 0
        assert int(after["version"]) == int(before["version"]), (
            "no customer-side effect follows a refused PASS"
        )
