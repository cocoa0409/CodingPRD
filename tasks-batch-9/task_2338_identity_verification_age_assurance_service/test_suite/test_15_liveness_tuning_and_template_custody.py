"""Liveness threshold tuning, and the custody of the templates it produces."""
from test_helpers import (
    complete_session,
    finalize_attempt,
    list_session_audit_events,
    list_session_templates,
    open_attempt,
    read_attempt,
    read_client,
    read_session,
    run_sweep,
    set_clock,
    setup_session,
    setup_stored_biometric_template,
    setup_verified_session_with_scheduled_template,
    step_up,
    submit_liveness_check,
)


def _high_risk_session_with_two_active_liveness_captures():
    """A high-risk biometric session whose first capture is retried after a step-up."""
    env = setup_session(
        method_codes=("BIOMETRIC_COMPARISON", "DOCUMENT_SCAN"),
        client_overrides={
            "biometric_retention_mode": "RETAIN_90_DAYS",
            "granted_review_credits": 1,
        },
        policy_overrides={
            "min_assurance_score": 30,
            "pad_threshold_bps": 7500,
            "doc_authenticity_floor_bps": 8000,
            "required_min_age_years": 0,
            "step_up_max_rounds": 2,
        },
        session_overrides={
            "external_subject_ref": "subj-r2a",
            "requested_assurance_tier": "ENHANCED",
            "declared_transaction_value_cents": 150000,
            "biometric_consent": True,
        },
    )
    client_id = env["client"]["id"]
    session_id = env["session"]["id"]
    biometric_profile_id = env["profiles"]["BIOMETRIC_COMPARISON"]["id"]

    first = open_attempt(session_id, client_id, biometric_profile_id)
    env["first_check"] = submit_liveness_check(
        first["id"], client_id, capture_modality="ACTIVE", pad_score_bps=8000, match_score_bps=9200
    )
    env["first_scored"] = read_attempt(first["id"], client_id)
    env["first_attempt"] = finalize_attempt(first["id"], client_id)

    step_up(session_id, client_id)
    second = open_attempt(session_id, client_id, biometric_profile_id)
    env["second_check"] = submit_liveness_check(
        second["id"], client_id, capture_modality="ACTIVE", pad_score_bps=8250, match_score_bps=9200
    )
    env["second_attempt"] = read_attempt(second["id"], client_id)
    return env


class TestLivenessThresholdComposesEveryTuningTerm:
    def test_the_threshold_adds_the_risk_and_retry_bumps_and_subtracts_the_active_relief(self):
        """PRD §3.5: "Start from the pinned policy's `pad_threshold_bps`. Add a risk bump: nothing
        for a `LOW`-risk session, 300 basis points for `MEDIUM`, 800 basis points for `HIGH`. Add
        200 basis points for each prior attempt of the same method on this session, that is, 200
        multiplied by the attempt's `retry_index`. Then subtract a relief of 250 basis points when
        `capture_modality` is `ACTIVE`, and nothing when it is `PASSIVE`."

        Design: Difficulty/combinatorial_formula/liveness_effective_threshold_composes_policy_risk_retry_and_modality
        """
        env = _high_risk_session_with_two_active_liveness_captures()

        assert env["session"]["risk_score"] == 70
        assert env["session"]["risk_level"] == "HIGH"
        assert env["first_check"]["retry_index"] == 0
        assert env["first_check"]["effective_threshold_bps"] == 8050
        assert env["second_check"]["retry_index"] == 1
        assert env["second_check"]["effective_threshold_bps"] == 8250

    def test_the_same_pad_score_lands_inconclusive_then_passing_as_the_bar_moves(self):
        """PRD §3.5: "`PASS` when `pad_score_bps` is at or above `effective_threshold_bps`,
        `INCONCLUSIVE` when `pad_score_bps` is at least 300 basis points below that threshold but
        still short of it, and `FAIL` otherwise. A score exactly equal to the threshold passes; a
        score exactly 300 basis points below it is inconclusive."

        Design: Difficulty/combinatorial_formula/liveness_effective_threshold_composes_policy_risk_retry_and_modality
        """
        env = _high_risk_session_with_two_active_liveness_captures()

        assert env["first_check"]["decision"] == "INCONCLUSIVE"
        assert env["second_check"]["decision"] == "PASS"

    def test_the_inconclusive_capture_is_halved_while_the_passing_one_is_recorded_whole(self):
        """PRD §3.5: "Evidence quality blends the two scores sixty-forty in favour of the
        comparison: six thousand multiplied by `match_score_bps`, plus four thousand multiplied by
        `pad_score_bps`, divided by ten thousand, truncated toward zero. A `PASS` records that
        blended figure as `evidence_quality_bps`. An `INCONCLUSIVE` records the blended figure
        halved and truncated toward zero."

        Design: Difficulty/combinatorial_formula/liveness_effective_threshold_composes_policy_risk_retry_and_modality
        """
        env = _high_risk_session_with_two_active_liveness_captures()

        assert env["first_scored"]["evidence_quality_bps"] == 4360
        assert env["first_scored"]["contribution_points"] == 15
        assert env["first_scored"]["match_score_bps"] == 9200
        assert env["second_attempt"]["state"] == "SCORED"
        assert env["second_attempt"]["evidence_quality_bps"] == 8820
        assert env["second_attempt"]["contribution_points"] == 30

    def test_the_halved_quality_falls_below_the_vendor_floor_and_parks_the_session(self):
        """PRD §3.6: "A `SCORED` attempt whose `evidence_quality_bps` is at or above the resolved
        profile's `acceptance_floor_bps` advances `SCORED → ACCEPTED`; one below the floor advances
        `SCORED → REJECTED`." "A biometric-comparison attempt records `LIVENESS_FAILED`, a database
        check records `DATA_MISMATCH`, and a knowledge-based attempt records `KBA_FAILED`."

        Design: Difficulty/combinatorial_formula/liveness_effective_threshold_composes_policy_risk_retry_and_modality
        """
        env = _high_risk_session_with_two_active_liveness_captures()

        assert env["first_attempt"]["state"] == "REJECTED"
        assert env["first_attempt"]["rejection_reason"] == "LIVENESS_FAILED"
        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["step_up_round"] == 1
        assert session["assurance_score_provisional"] == 30


def _stored_template_on_a_delete_on_complete_client():
    """One STORED template held by a client that keeps nothing past completion."""
    set_clock("2026-08-10T09:00:00Z")
    return setup_stored_biometric_template(
        client_overrides={
            "biometric_retention_mode": "DELETE_ON_COMPLETE",
            "granted_review_credits": 1,
        },
        session_overrides={"external_subject_ref": "subj-r9b", "biometric_consent": True},
    )


class TestBiometricCustodyCountIsConserved:
    def test_storing_a_template_raises_the_custody_count_to_one(self):
        """PRD §3.5: "a **BiometricTemplate** is created against the owning `session_id` in the
        `STORED` state with `source_method_code` recorded as `BIOMETRIC_COMPARISON`, and the
        client's `stored_template_count` increases by one."

        Design: Difficulty/compensating_invariant/biometric_custody_count_conserved_across_store_and_immediate_deletion
        """
        env = _stored_template_on_a_delete_on_complete_client()

        assert read_client(env["client"]["id"])["stored_template_count"] == 1
        stored, meta = list_session_templates(env["session"]["id"], state="STORED")
        assert meta["total_count"] == 1
        assert stored[0]["source_method_code"] == "BIOMETRIC_COMPARISON"
        assert stored[0]["retention_expires_at"] is None
        assert stored[0]["deleted_at"] is None
        assert stored[0]["deletion_reason"] is None

    def test_immediate_deletion_at_completion_returns_the_count_to_zero_exactly_once(self):
        """PRD §3.10: "if the client's `biometric_retention_mode` is `DELETE_ON_COMPLETE`, the
        template is deleted immediately with `deletion_reason` of `POLICY_IMMEDIATE`." "Whether a
        template is deleted at once or merely scheduled for purge, the client's
        `stored_template_count` decrements exactly once, at the moment the template leaves
        `STORED`."

        Design: Difficulty/compensating_invariant/biometric_custody_count_conserved_across_store_and_immediate_deletion
        """
        env = _stored_template_on_a_delete_on_complete_client()
        session = complete_session(env["session"]["id"], env["client"]["id"])

        assert session["identity_state"] == "VERIFIED"
        assert session["assurance_score_final"] == 31

        templates, meta = list_session_templates(env["session"]["id"])
        assert meta["total_count"] == 1
        assert templates[0]["state"] == "DELETED"
        assert templates[0]["deletion_reason"] == "POLICY_IMMEDIATE"
        assert templates[0]["deleted_at"].startswith("2026-08-10T09:00:00")
        assert templates[0]["retention_expires_at"] is None
        assert read_client(env["client"]["id"])["stored_template_count"] == 0

        _, event_meta = list_session_audit_events(
            env["session"]["id"], event_type="TEMPLATE_DELETED"
        )
        assert event_meta["total_count"] == 1


def _scheduled_template_at_its_exact_expiry_instant():
    """A purge-scheduled template with the clock parked exactly on its expiry."""
    env = setup_verified_session_with_scheduled_template(
        completion_clock="2026-08-10T09:00:00Z",
        client_overrides={
            "biometric_retention_mode": "RETAIN_90_DAYS",
            "granted_review_credits": 1,
        },
        session_overrides={"external_subject_ref": "subj-r6d", "biometric_consent": True},
    )
    set_clock("2026-11-08T09:00:00Z")
    return env


class TestPurgeAtTheExactRetentionExpiryInstant:
    def test_completion_schedules_the_purge_ninety_days_after_the_closing_instant(self):
        """PRD §3.10: "the template moves `STORED → PURGE_SCHEDULED` and its
        `retention_expires_at` is set to the session's `completed_at` plus ninety days on the
        logical clock, preserving the time of day."

        Design: Difficulty/boundary_precision_check/purge_scheduled_template_deleted_at_exact_retention_expiry_instant
        """
        env = _scheduled_template_at_its_exact_expiry_instant()

        assert env["session"]["identity_state"] == "VERIFIED"
        assert env["session"]["disposition_reason"] == "SCORE_SATISFIED"
        assert env["session"]["assurance_score_final"] == 31
        assert env["session"]["completed_at"].startswith("2026-08-10T09:00:00")
        assert env["template"]["state"] == "PURGE_SCHEDULED"
        assert env["template"]["retention_expires_at"].startswith("2026-11-08T09:00:00")

    def test_a_template_whose_deadline_equals_the_clock_is_deleted_by_the_sweep(self):
        """PRD §3.10: "Any template in `PURGE_SCHEDULED` whose `retention_expires_at` the clock has
        reached or passed moves `PURGE_SCHEDULED → DELETED` with `deleted_at` set to the clock and
        `deletion_reason` of `RETENTION_EXPIRED`, and an audit event of type `TEMPLATE_DELETED` is
        appended; a template whose deadline exactly equals the clock is deleted, the comparison
        being inclusive."

        Design: Difficulty/boundary_precision_check/purge_scheduled_template_deleted_at_exact_retention_expiry_instant
        """
        env = _scheduled_template_at_its_exact_expiry_instant()
        sweep = run_sweep()

        assert sweep["deleted_template_count"] == 1
        assert sweep["withdrawn_case_count"] == 0
        assert sweep["expired_session_count"] == 0
        assert sweep["swept_at"].startswith("2026-11-08T09:00:00")

        templates, meta = list_session_templates(env["session"]["id"])
        assert meta["total_count"] == 1
        assert templates[0]["state"] == "DELETED"
        assert templates[0]["deletion_reason"] == "RETENTION_EXPIRED"
        assert templates[0]["deleted_at"].startswith("2026-11-08T09:00:00")

        _, event_meta = list_session_audit_events(
            env["session"]["id"], event_type="TEMPLATE_DELETED"
        )
        assert event_meta["total_count"] == 1

    def test_the_second_deletion_step_does_not_move_the_custody_count_again(self):
        """PRD §3.10: "Because the count was already decremented when the template left `STORED`,
        this second step does not touch `stored_template_count` again."

        Design: Difficulty/boundary_precision_check/purge_scheduled_template_deleted_at_exact_retention_expiry_instant
        """
        env = _scheduled_template_at_its_exact_expiry_instant()

        assert read_client(env["client"]["id"])["stored_template_count"] == 0
        run_sweep()
        assert read_client(env["client"]["id"])["stored_template_count"] == 0
