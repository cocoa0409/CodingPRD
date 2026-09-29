"""Initial states, illegal transitions, terminal lockdown and exhaustion."""

import pytest

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_instant, assert_version_is, assert_whole_minutes


class TestDeclaredInitialStates:
    def test_a_new_call_a_new_window_and_a_future_shift_all_start_at_their_first_state(
        self, world
    ):
        """PRD §3.3: "A call that survives both checks is created at `status` `INTAKE`,
        with `requires_warm_transfer` false, `billable_minutes` at 0, `advice_fee_cents`
        at 0, `reopen_count` at 0, `deferred_assignment_count` at 0, and every
        identification, consent, assignment, transfer and closure field still absent."

        Design: Corner/state_machines/every_aggregate_root_starts_in_its_declared_initial_state
        """
        world.set_clock("2026-08-03T14:30:00Z")
        world.create_practice()
        world.create_nurse("nurse_a")

        call = world.open_call(reason_text="sore throat")

        assert call["status"] == "INTAKE"
        assert call["patient_id"] is None
        assert call["is_after_hours"] is False
        assert call["deferred_assignment_count"] == 0
        assert_version_is(call, 1)

    def test_a_drafted_window_and_a_scheduled_shift_carry_their_declared_openings(
        self, world
    ):
        """PRD §3.2: "A drafted window is created with `status` `DRAFT` and
        `suspend_reason` absent."

        Design: Corner/state_machines/every_aggregate_root_starts_in_its_declared_initial_state
        """
        world.set_clock("2026-08-03T14:30:00Z")
        world.create_practice()
        world.create_nurse("nurse_a")

        window = world.create_coverage_window(
            start_utc="2026-08-08T00:00:00Z",
            end_utc="2026-08-09T00:00:00Z",
            coverage_kind="WEEKEND",
        )
        shift = world.add_shift(
            "nurse_a", start_utc="2026-08-04T12:00:00Z", end_utc="2026-08-04T20:00:00Z"
        )
        protocol = world.create_protocol()

        assert window["status"] == "DRAFT"
        assert window["suspend_reason"] is None
        assert shift["status"] == "SCHEDULED", "the clock is strictly before its start"
        assert_whole_minutes(shift["scheduled_minutes"], 480, "scheduled_minutes")
        assert protocol["status"] == "ACTIVE"


@pytest.fixture
def call_at_intake(world):
    """One in-hours call sitting at INTAKE with a matchable chart on file."""
    world.bootstrap(clock="2026-08-03T14:30:00Z", nurse_keys=())
    call = world.open_call(reason_text="sore throat")
    return call


class TestConsentOnlyFromIdentified:
    def test_consent_before_the_chart_is_bound_is_an_invalid_state(
        self, world, call_at_intake
    ):
        """PRD §3.3: "Consent is captured next, advancing
        `IDENTIFIED → CONSENTED`."

        Design: Corner/state_machines/consent_before_patient_match_and_a_second_consent_are_both_invalid_state
        """
        call = call_at_intake

        response = world.api.record_consent(
            call["id"], f.consent_payload(), world.intake
        )

        validate_error(response, ApiErrorId.ERR_CALL_INVALID_STATE, 409)
        assert world.call(call["id"])["status"] == "INTAKE"

    def test_a_second_consent_on_a_consented_call_is_also_an_invalid_state(
        self, world, call_at_intake
    ):
        """PRD §2.12: "17. `ERR_CALL_INVALID_STATE` — the call's `status` is not in
        the from-set of the requested transition."

        Design: Corner/state_machines/consent_before_patient_match_and_a_second_consent_are_both_invalid_state
        """
        call = call_at_intake
        world.match_patient(call["id"], world.patients["patient"]["id"])
        world.record_consent(call["id"])

        response = world.api.record_consent(
            call["id"],
            f.consent_payload(consent_type="GUARDIAN", consent_given_by="Someone Else"),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_CALL_INVALID_STATE, 409)

    def test_neither_rejection_disturbs_the_recorded_consent(
        self, world, call_at_intake
    ):
        """PRD §3.3: "On success the call records `consent_type`,
        `consent_given_by` and `recording_reference`, stamps `consent_recorded_at`
        with the current logical-clock instant, moves to `CONSENTED`, and increases
        `version` by one."

        Design: Corner/state_machines/consent_before_patient_match_and_a_second_consent_are_both_invalid_state
        """
        call = call_at_intake
        world.api.record_consent(call["id"], f.consent_payload(), world.intake)
        world.match_patient(call["id"], world.patients["patient"]["id"])
        world.record_consent(call["id"])
        world.api.record_consent(
            call["id"],
            f.consent_payload(consent_type="GUARDIAN", consent_given_by="Someone Else"),
            world.intake,
        )

        after = world.call(call["id"])
        assert after["status"] == "CONSENTED"
        assert after["consent_type"] == "PATIENT_SELF"
        assert after["consent_given_by"] == "Dana Reyes"
        assert_instant(
            after["consent_recorded_at"], "2026-08-03T14:30:00Z", "consent_recorded_at"
        )
        assert after["recording_reference"] is None


@pytest.fixture
def abandoned_call(world):
    """An assigned call that was then abandoned, releasing the nurse."""
    world.bootstrap(clock="2026-08-03T14:30:00Z", protocol={"base_severity": 20})
    call = world.call_through_assignment("nurse_a", reason_text="sore throat")
    world.abandon_call(call["id"], abandon_reason="Caller disconnected.")
    return call


class TestAbandonedIsTerminal:
    def test_the_abandoned_call_refuses_a_further_assignment(self, world, abandoned_call):
        """PRD §3.3: "An abandoned call is final; nothing reopens it."

        Design: Corner/state_machines/an_abandoned_call_is_terminal_and_refuses_every_further_transition
        """
        call = abandoned_call

        response = world.api.assign_nurse(
            call["id"],
            f.assign_nurse_payload(world.nurse_id("nurse_a")),
            world.charge_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_CALL_INVALID_STATE, 409)

    def test_the_abandoned_call_refuses_a_further_assessment(
        self, world, abandoned_call
    ):
        """PRD §3.5: "Requesting an assessment while the call is in any other state is
        refused with `ERR_CALL_INVALID_STATE`."

        Design: Corner/state_machines/an_abandoned_call_is_terminal_and_refuses_every_further_transition
        """
        call = abandoned_call

        response = world.api.create_assessment(
            call["id"],
            f.assessment_payload(world.protocols["protocol"]["id"], red_flag_count=0),
            world.nurse_headers("nurse_a"),
        )

        validate_error(response, ApiErrorId.ERR_CALL_INVALID_STATE, 409)
        _, meta = validate_paginated(
            world.api.list_assessments(world.admin, {"call_id": call["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_second_abandon_is_refused_and_the_released_load_stays_released(
        self, world, abandoned_call
    ):
        """PRD §3.3: "Abandoning a call in any other state — one already `CLOSED` or
        already `ABANDONED` — is refused with `ERR_CALL_INVALID_STATE`."

        Design: Corner/state_machines/an_abandoned_call_is_terminal_and_refuses_every_further_transition
        """
        call = abandoned_call

        response = world.api.abandon_call(
            call["id"],
            f.abandon_payload(abandon_reason="Trying to abandon twice."),
            world.intake,
        )

        validate_error(response, ApiErrorId.ERR_CALL_INVALID_STATE, 409)
        after = world.call(call["id"])
        assert after["status"] == "ABANDONED"
        assert after["abandon_reason"] == "Caller disconnected."
        assert world.nurse("nurse_a")["active_call_load"] == 0


class TestCoverageActivationIsNotIdempotent:
    def test_the_second_activation_is_refused_and_bumps_no_version(self, world):
        """PRD §3.2: "If the window is not in `DRAFT` — already `ACTIVE`, lazily
        `EXPIRED`, or `BLOCKED` — the answer is
        `ERR_COVERAGE_WINDOW_INVALID_STATE`."

        Design: Corner/state_machines/activating_an_already_active_coverage_window_is_rejected
        """
        world.set_clock("2026-07-30T12:00:00Z")
        world.create_practice()
        window = world.create_coverage_window(as_liaison=True)
        activated = world.activate_coverage_window(
            window["id"], as_liaison_for=world.practice_id
        )
        assert_version_is(activated, 2, "version after the first activation")

        response = world.api.activate_coverage_window(
            window["id"], {}, world.liaison_headers()
        )

        validate_error(response, ApiErrorId.ERR_COVERAGE_WINDOW_INVALID_STATE, 409)
        after = world.coverage_window(window["id"])
        assert_version_is(after, 2, "version after the refused activation")
        assert after["status"] == "ACTIVE"


@pytest.fixture
def high_risk_task_with_three_attempts(world):
    """A HIGH_RISK callback on an ED_NOW disposition, nothing dialled yet."""
    world.bootstrap(
        clock="2026-08-03T14:30:00Z",
        nurse_keys=("nurse_a", "nurse_c"),
        practice={"variance_review_threshold": 1},
        protocol={"base_severity": 62},
    )
    call, assessment, disposition = world.dispositioned_call(
        "ED_NOW", "nurse_a", red_flag_count=1
    )
    task = world.callback_for(disposition["id"])
    return disposition, task


class TestHighRiskCallbackExhaustion:
    def test_the_first_two_failed_attempts_are_a_genuine_self_loop(
        self, world, high_risk_task_with_three_attempts
    ):
        """PRD §3.8: "the second failed attempt on a `HIGH_RISK` task, which permits
        three, leaves the status reading `ATTEMPTED` while the counter advances from
        one to two."

        Design: Corner/state_machines/high_risk_callback_exhausting_its_attempts_expires_and_escalates_the_disposition
        """
        _, task = high_risk_task_with_three_attempts
        assert task["max_attempts"] == 3
        assert_instant(task["due_by_utc"], "2026-08-03T16:30:00Z", "due_by_utc")

        first = world.record_attempt(task["id"], "nurse_a", "NO_ANSWER")
        second = world.record_attempt(task["id"], "nurse_a", "BUSY")

        assert first["status"] == "ATTEMPTED"
        assert first["attempt_count"] == 1
        assert second["status"] == "ATTEMPTED"
        assert second["attempt_count"] == 2

    def test_the_third_failure_expires_the_task(
        self, world, high_risk_task_with_three_attempts
    ):
        """PRD §3.8: "A failed attempt where `attempt_count` plus one reaches or
        exceeds `max_attempts` instead exhausts the task. It increases
        `attempt_count` by one, records `last_attempt_outcome`, moves the status to
        the terminal `EXPIRED`, decreases the practice's `open_callback_count` by
        one, and increases the task's `version` by one."

        Design: Corner/state_machines/high_risk_callback_exhausting_its_attempts_expires_and_escalates_the_disposition
        """
        _, task = high_risk_task_with_three_attempts
        world.record_attempt(task["id"], "nurse_a", "NO_ANSWER")
        world.record_attempt(task["id"], "nurse_a", "BUSY")

        third = world.record_attempt(task["id"], "nurse_a", "NO_ANSWER")

        assert third["status"] == "EXPIRED"
        assert third["attempt_count"] == 3
        assert third["last_attempt_outcome"] == "NO_ANSWER"
        assert third["patient_condition"] is None
        assert world.practice()["open_callback_count"] == 0

    def test_the_unreachable_high_risk_caller_escalates_the_audit_dimension(
        self, world, high_risk_task_with_three_attempts
    ):
        """PRD §3.8: "when that expired task's `risk_class` is `HIGH_RISK`, it also
        drives the parent disposition's audit dimension
        `AWAITING_OUTCOME → VARIANCE_ESCALATED` together with the full practice
        variance cascade described below — an unreachable high-risk caller is itself a
        compliance variance, not merely an administrative loose end."

        Design: Corner/state_machines/high_risk_callback_exhausting_its_attempts_expires_and_escalates_the_disposition
        """
        disposition, task = high_risk_task_with_three_attempts
        for outcome in ("NO_ANSWER", "BUSY", "NO_ANSWER"):
            world.record_attempt(task["id"], "nurse_a", outcome)

        after = world.disposition(disposition["id"])
        practice = world.practice()

        assert after["audit_status"] == "VARIANCE_ESCALATED"
        assert after["advice_status"] == "AUTHORIZED"
        assert practice["open_variance_count"] == 1
        assert practice["compliance_posture"] == "UNDER_REVIEW"
        assert practice["escalated_callback_count"] == 0, (
            "expiry is not a worsened verification, so the escalation ledger is quiet"
        )


class TestCallbackVerifyOnlyFromReached:
    def test_verifying_a_pending_task_is_an_invalid_state(
        self, world, high_risk_task_with_three_attempts
    ):
        """PRD §3.8: "Verification is only possible from `REACHED`".

        Design: Corner/state_machines/verify_before_reached_and_attempt_after_verified_are_both_invalid_state
        """
        _, task = high_risk_task_with_three_attempts

        response = world.api.verify_callback(
            task["id"],
            f.verify_payload("IMPROVED", True),
            world.nurse_headers("nurse_c"),
        )

        validate_error(response, ApiErrorId.ERR_CALLBACK_INVALID_STATE, 409)

    def test_an_attempt_after_verification_is_an_invalid_state(
        self, world, high_risk_task_with_three_attempts
    ):
        """PRD §3.8: "Recording an attempt against a task that is `REACHED`,
        `VERIFIED`, `ESCALATED`, `EXPIRED` or `CANCELLED` is refused with
        `ERR_CALLBACK_INVALID_STATE`."

        Design: Corner/state_machines/verify_before_reached_and_attempt_after_verified_are_both_invalid_state
        """
        _, task = high_risk_task_with_three_attempts
        world.record_attempt(task["id"], "nurse_a", "REACHED")
        world.verify_callback(task["id"], "nurse_c", "IMPROVED", True)

        response = world.api.create_callback_attempt(
            task["id"], f.attempt_payload("NO_ANSWER"), world.nurse_headers("nurse_a")
        )

        validate_error(response, ApiErrorId.ERR_CALLBACK_INVALID_STATE, 409)

    def test_a_reached_then_verified_task_never_counts_an_attempt(
        self, world, high_risk_task_with_three_attempts
    ):
        """PRD §3.8: "An `outcome` of `REACHED` moves the task from `PENDING` or
        `ATTEMPTED` to `REACHED`, records `last_attempt_outcome` as `REACHED`, increases
        the task's `version` by one, and pointedly leaves `attempt_count` **unchanged**
        — a call that was answered is not a failed attempt, so a task reached on the
        second dial still shows one prior failed attempt rather than two."

        Design: Corner/state_machines/verify_before_reached_and_attempt_after_verified_are_both_invalid_state
        """
        disposition, task = high_risk_task_with_three_attempts
        world.record_attempt(task["id"], "nurse_a", "REACHED")
        world.verify_callback(task["id"], "nurse_c", "IMPROVED", True)

        verified = world.callback(task["id"])
        assert verified["status"] == "VERIFIED"
        assert verified["attempt_count"] == 0
        assert verified["verified_by_nurse_id"] == world.nurse_id("nurse_c")
        assert_instant(verified["verified_at"], "2026-08-03T14:30:00Z", "verified_at")
        assert_instant(
            world.disposition(disposition["id"])["callback_verified_at"],
            "2026-08-03T14:30:00Z",
            "callback_verified_at",
        )
        assert world.practice()["open_callback_count"] == 0
