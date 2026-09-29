"""Gates that read a neighbouring entity's state, and the counters that must balance."""
from test_helpers import (
    OFFICER,
    SUSPECT_CAPTURE,
    client_version,
    decide_review_case,
    draft_policy,
    finalize_attempt,
    list_profile_audits,
    list_session_attempts,
    open_attempt,
    patch_client,
    publish_policy,
    read_attempt,
    read_bias_audit,
    read_client,
    read_method_profile,
    read_policy,
    read_session,
    register_method_profile,
    restrict_profile_by_bias,
    setup_assigned_review_case,
    setup_bias_audit_with_cohorts,
    setup_finalized_document_attempt,
    setup_session,
    step_up,
    submit_document_capture,
    validate_error,
)

STANDARD_POLICY = {
    "min_assurance_score": 60,
    "doc_authenticity_floor_bps": 8000,
    "required_min_age_years": 0,
    "step_up_max_rounds": 2,
}


def _live_session_whose_client_was_then_suspended():
    """A session left in progress with one open attempt, owned by a suspended client."""
    env = setup_session(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 1},
        policy_overrides=dict(STANDARD_POLICY),
        session_overrides={"external_subject_ref": "subj-r7a"},
    )
    env["attempt"] = open_attempt(
        env["session"]["id"], env["client"]["id"], env["profiles"]["DOCUMENT_SCAN"]["id"]
    )
    patch_client(env["client"]["id"], integration_state="SUSPENDED")
    return env


class TestAttemptCreationReadsTheOwningClientState:
    def test_a_suspended_owner_blocks_the_next_attempt_on_an_untouched_session(self, api):
        """PRD §3.3: "A `ClientIntegrator` opens one against a session that is `IN_PROGRESS` and not
        lapsed, whose client is not `SUSPENDED`, and whose pinned policy is still `PUBLISHED`."
        PRD §3.2: "A client still in `SANDBOX`, or one that has been `SUSPENDED`, is rejected with
        `ERR_CLIENT_NOT_LIVE` — note that publication and attempt creation are more permissive,
        admitting `SANDBOX` and refusing only `SUSPENDED`, whereas session creation admits `LIVE`
        alone."

        Design: Difficulty/cross_entity_state_dependency/attempt_creation_blocked_by_suspended_client_state
        """
        env = _live_session_whose_client_was_then_suspended()
        validate_error(
            api.create_method_attempt(
                env["session"]["id"],
                {"method_profile_id": env["profiles"]["DOCUMENT_SCAN"]["id"]},
                env["headers"],
            ),
            "ERR_CLIENT_NOT_LIVE",
            409,
        )

    def test_the_earlier_attempt_survives_and_the_session_axis_is_untouched(self, api):
        """PRD §2.6: "`ERR_CLIENT_NOT_LIVE` (409) — the client's integration posture admits the
        operation. `POST /idv/verification-sessions`, `POST /idv/verification-policies/{id}/publish`,
        `POST /idv/verification-sessions/{id}/method-attempts`." A refused request mutates nothing,
        and per PRD §3.2 the identity axis "starts at `IN_PROGRESS`" until a transition moves it.

        Design: Difficulty/cross_entity_state_dependency/attempt_creation_blocked_by_suspended_client_state
        """
        env = _live_session_whose_client_was_then_suspended()
        validate_error(
            api.create_method_attempt(
                env["session"]["id"],
                {"method_profile_id": env["profiles"]["DOCUMENT_SCAN"]["id"]},
                env["headers"],
            ),
            "ERR_CLIENT_NOT_LIVE",
        )

        attempts, meta = list_session_attempts(env["session"]["id"])
        assert meta["total_count"] == 1
        assert attempts[0]["id"] == env["attempt"]["id"]
        assert read_session(env["session"]["id"], env["client"]["id"])["identity_state"] == (
            "IN_PROGRESS"
        )
        assert read_client(env["client"]["id"])["integration_state"] == "SUSPENDED"


def _restricted_profile_carrying_a_second_healthy_audit():
    """A restricted vendor whose next measurement window is perfectly well formed."""
    profile = register_method_profile("DOCUMENT_SCAN")
    first = restrict_profile_by_bias(
        profile["id"],
        window_start="2026-06-01T00:00:00Z",
        window_end="2026-07-01T00:00:00Z",
    )
    second = setup_bias_audit_with_cohorts(
        profile["id"],
        cohorts=(("AGE_18_24", 1000, 40), ("AGE_25_44", 1000, 41), ("AGE_45_64", 1000, 39)),
        window_start="2026-07-01T00:00:00Z",
        window_end="2026-08-01T00:00:00Z",
    )
    return profile, first, second


class TestEvaluationReadsTheAuditedProfileState:
    def test_a_restricted_vendor_blocks_the_evaluation_of_its_next_audit(self, api):
        """PRD §3.9: "Evaluation requires the audit to be `COLLECTING` and requires the audited
        profile not to already be `RESTRICTED`, otherwise `ERR_METHOD_RESTRICTED_BY_BIAS`."

        Design: Difficulty/cross_entity_state_dependency/bias_evaluation_blocked_by_restricted_profile_state_on_second_audit
        """
        _, _, second = _restricted_profile_carrying_a_second_healthy_audit()
        validate_error(
            api.evaluate_bias_audit(second["id"], OFFICER),
            "ERR_METHOD_RESTRICTED_BY_BIAS",
            409,
        )

    def test_the_blocked_audit_keeps_its_collecting_state_and_writes_no_disparity_figure(self, api):
        """PRD §3.9: "Evaluation requires the audit to be `COLLECTING` and requires the audited
        profile not to already be `RESTRICTED`, otherwise `ERR_METHOD_RESTRICTED_BY_BIAS`." A new
        audit "opens in `COLLECTING` ... with `remediation_round` at 0,
        `remediated_at` null, `evaluated_by_user_id` and `remediated_by_user_id` null,
        `included_cohort_count` and `excluded_cohort_count` at 0, `insufficient_sample` false, and
        `max_frr_bps`, `min_frr_bps`, `pooled_frr_bps`, `disparity_ratio_max_to_min_bps`,
        `disparity_ratio_max_to_pooled_bps` and `worst_cohort_code` all null."

        Design: Difficulty/cross_entity_state_dependency/bias_evaluation_blocked_by_restricted_profile_state_on_second_audit
        """
        profile, first, second = _restricted_profile_carrying_a_second_healthy_audit()
        validate_error(
            api.evaluate_bias_audit(second["id"], OFFICER), "ERR_METHOD_RESTRICTED_BY_BIAS"
        )

        blocked = read_bias_audit(second["id"])
        assert blocked["state"] == "COLLECTING"
        assert blocked["disparity_ratio_max_to_pooled_bps"] is None
        assert blocked["evaluated_by_user_id"] is None

        assert read_bias_audit(first["id"])["state"] == "REMEDIATION_REQUIRED"
        assert read_method_profile(profile["id"])["bias_state"] == "RESTRICTED"
        _, meta = list_profile_audits(profile["id"])
        assert meta["total_count"] == 2


def _session_pinned_to_a_policy_that_was_then_superseded():
    """A session still in progress whose pinned policy was retired by a newer publication."""
    env = setup_session(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 1},
        policy_overrides=dict(STANDARD_POLICY),
        session_overrides={"external_subject_ref": "subj-r7c"},
    )
    successor = draft_policy(
        env["client"]["id"],
        policy_version=2,
        allowed_method_codes=["DOCUMENT_SCAN"],
        **STANDARD_POLICY,
    )
    env["successor"] = publish_policy(successor["id"], client_version(env["client"]["id"]))
    return env


class TestAttemptCreationReadsThePinnedPolicyState:
    def test_a_retired_pinned_policy_blocks_the_next_attempt(self, api):
        """PRD §3.1: "Sessions that were already pinned to the retired policy keep their pinned
        policy reference and continue to be evaluated against its thresholds, but they can no longer
        open new attempts: any such request is rejected with `ERR_PINNED_POLICY_RETIRED`."

        Design: Difficulty/cross_entity_state_dependency/attempt_creation_blocked_by_retired_pinned_policy_state
        """
        env = _session_pinned_to_a_policy_that_was_then_superseded()
        validate_error(
            api.create_method_attempt(
                env["session"]["id"],
                {"method_profile_id": env["profiles"]["DOCUMENT_SCAN"]["id"]},
                env["headers"],
            ),
            "ERR_PINNED_POLICY_RETIRED",
            409,
        )

    def test_the_publication_retired_the_pin_without_repointing_the_session(self, api):
        """PRD §3.1: "On success the policy moves `DRAFT → PUBLISHED` with `published_at` set to the
        clock, and in the same request the client's previously `PUBLISHED` policy, if any, moves
        `PUBLISHED → RETIRED` with `retired_at` set to the clock". "they can no longer open new
        attempts: any such request is rejected with `ERR_PINNED_POLICY_RETIRED`." PRD §3.2: "The pin
        survives the pinned policy's later retirement: `policy_id` continues to point at the retired
        policy and its thresholds continue to govern the session."

        Design: Difficulty/cross_entity_state_dependency/attempt_creation_blocked_by_retired_pinned_policy_state
        """
        env = _session_pinned_to_a_policy_that_was_then_superseded()
        validate_error(
            api.create_method_attempt(
                env["session"]["id"],
                {"method_profile_id": env["profiles"]["DOCUMENT_SCAN"]["id"]},
                env["headers"],
            ),
            "ERR_PINNED_POLICY_RETIRED",
        )

        assert read_policy(env["policy"]["id"])["state"] == "RETIRED"
        assert read_policy(env["successor"]["id"])["state"] == "PUBLISHED"
        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["policy_id"] == env["policy"]["id"]
        assert session["identity_state"] == "IN_PROGRESS"
        _, meta = list_session_attempts(env["session"]["id"])
        assert meta["total_count"] == 0


def _single_credit_client_with_an_assigned_case():
    """One escalation assigned against a pool of exactly one review credit."""
    return setup_assigned_review_case(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 1},
        policy_overrides=dict(STANDARD_POLICY),
        session_overrides={"external_subject_ref": "subj-r9a"},
    )


class TestReviewCreditPoolIsConserved:
    def test_assignment_moves_the_single_credit_from_available_to_reserved(self):
        """PRD §3.8: "On success the case moves `QUEUED → ASSIGNED`, `assigned_by_user_id` records
        the manager's `X-User-ID`, and one credit is reserved — meaning `reserved_review_credits`
        rises by one and `available_review_credits` falls by one, the pool invariant of §2.8 holding
        throughout."

        Design: Difficulty/compensating_invariant/review_credit_pool_conserved_across_assignment_and_decision
        """
        env = _single_credit_client_with_an_assigned_case()
        client = read_client(env["client"]["id"])

        assert client["reserved_review_credits"] == 1
        assert client["available_review_credits"] == 0
        assert client["reserved_review_credits"] + client["available_review_credits"] == (
            client["granted_review_credits"]
        )
        assert client["consumed_review_count"] == 0

    def test_the_decision_releases_the_credit_and_raises_the_lifetime_tally(self):
        """PRD §3.8: "On success the case moves `ASSIGNED → DECIDED` with `decision`,
        `decided_by_user_id` and `decided_at` written, the reserved credit is released back to
        `available_review_credits`, and the client's `consumed_review_count` rises by one."
        PRD §2.8: "`consumed_review_count` is a lifetime tally of that client's manual review cases
        that reached `DECIDED`; it only ever increases."

        Design: Difficulty/compensating_invariant/review_credit_pool_conserved_across_assignment_and_decision
        """
        env = _single_credit_client_with_an_assigned_case()
        case = decide_review_case(env["case"]["id"], "APPROVE")

        assert case["state"] == "DECIDED"
        assert case["decision"] == "APPROVE"
        assert case["decided_by_user_id"] == "mr-1"
        assert case["assigned_by_user_id"] == "rm-1"

        client = read_client(env["client"]["id"])
        assert client["reserved_review_credits"] == 0
        assert client["available_review_credits"] == 1
        assert client["reserved_review_credits"] + client["available_review_credits"] == (
            client["granted_review_credits"]
        )
        assert client["consumed_review_count"] == 1

    def test_the_approval_verdict_overrides_the_session_onto_the_verified_axis(self):
        """PRD §3.8: "`APPROVE` moves the session `MANUAL_REVIEW → VERIFIED`, sets
        `manual_override_flag` to true, sets `disposition_reason` to `MANUAL_OVERRIDE`, sets
        `completed_at` to the clock, writes `assurance_score_final`, and applies the retention
        schedule to every template still in `STORED`."

        Design: Difficulty/compensating_invariant/review_credit_pool_conserved_across_assignment_and_decision
        """
        env = _single_credit_client_with_an_assigned_case()
        decide_review_case(env["case"]["id"], "APPROVE")

        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["identity_state"] == "VERIFIED"
        assert session["manual_override_flag"] is True
        assert session["disposition_reason"] == "MANUAL_OVERRIDE"
        assert session["assurance_score_final"] == 0


def _two_suspect_rejections_with_a_step_up_between_them():
    """A session parked twice on weak documents, with one step-up already spent."""
    env = setup_finalized_document_attempt(
        capture_overrides=dict(SUSPECT_CAPTURE),
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 1},
        policy_overrides=dict(STANDARD_POLICY),
        session_overrides={"external_subject_ref": "subj-r9c"},
    )
    client_id = env["client"]["id"]
    session_id = env["session"]["id"]

    env["first_parked_count"] = read_client(client_id)["pending_stepup_count"]
    env["first_step_up"] = step_up(session_id, client_id)
    env["after_first_step_up_count"] = read_client(client_id)["pending_stepup_count"]

    second = open_attempt(session_id, client_id, env["profiles"]["DOCUMENT_SCAN"]["id"])
    submit_document_capture(second["id"], client_id, **dict(SUSPECT_CAPTURE))
    env["second_attempt"] = finalize_attempt(second["id"], client_id)
    env["second_parked_count"] = read_client(client_id)["pending_stepup_count"]
    return env


class TestPendingStepUpCounterNeverDrifts:
    def test_the_counter_rises_on_each_parking_and_falls_on_each_step_up(self):
        """PRD §2.8: "`pending_stepup_count` is the number of that client's sessions whose identity
        axis sits at `AWAITING_EVIDENCE`." PRD §3.6: "the client's `pending_stepup_count` increases
        by one" on a non-tamper rejection, and on step-up "`step_up_round` increases by one, the
        client's `pending_stepup_count` decreases by one".

        Design: Difficulty/compensating_invariant/pending_stepup_counter_conserved_across_two_step_up_cycles
        """
        env = _two_suspect_rejections_with_a_step_up_between_them()

        assert env["first_parked_count"] == 1
        assert env["after_first_step_up_count"] == 0
        assert env["first_step_up"]["step_up_round"] == 1
        assert env["second_parked_count"] == 1

    def test_the_second_step_up_returns_the_counter_to_zero_with_the_budget_spent(self):
        """PRD §3.6: "On success the session moves `AWAITING_EVIDENCE → IN_PROGRESS`,
        `step_up_round` increases by one, the client's `pending_stepup_count` decreases by one, and
        an audit event of type `STEP_UP_TRIGGERED` is appended."

        Design: Difficulty/compensating_invariant/pending_stepup_counter_conserved_across_two_step_up_cycles
        """
        env = _two_suspect_rejections_with_a_step_up_between_them()
        session = step_up(env["session"]["id"], env["client"]["id"])

        assert session["identity_state"] == "IN_PROGRESS"
        assert session["step_up_round"] == 2
        assert read_client(env["client"]["id"])["pending_stepup_count"] == 0

    def test_both_weak_documents_are_rejected_without_contributing_anything(self):
        """PRD §3.3: "Its `retry_index` is the number of attempts that already exist on the same
        session with the same `method_code`, so the first document scan of a session has index 0 and
        a second has index 1". PRD §3.8: "attempts sitting in `REQUIRES_RESCORE`, `REJECTED` or
        `EXPIRED` contribute nothing to either figure."

        Design: Difficulty/compensating_invariant/pending_stepup_counter_conserved_across_two_step_up_cycles
        """
        env = _two_suspect_rejections_with_a_step_up_between_them()
        client_id = env["client"]["id"]

        first = read_attempt(env["attempt"]["id"], client_id)
        second = read_attempt(env["second_attempt"]["id"], client_id)
        assert first["retry_index"] == 0
        assert second["retry_index"] == 1
        for attempt in (first, second):
            assert attempt["state"] == "REJECTED"
            assert attempt["rejection_reason"] == "DOCUMENT_SUSPECT"
            assert attempt["evidence_quality_bps"] == 7400
        assert read_session(env["session"]["id"], client_id)["assurance_score_provisional"] == 0
