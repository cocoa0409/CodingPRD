"""State, precondition and coverage rejections.

Each scenario reaches a state the addressed operation does not admit — a
terminal pathway, an evaluated audit, an unconsented biometric capture, a
policy that was never published, a method outside the pinned ladder, an
exhausted step-up budget, an outstanding inclusion pathway, an unanswered age
axis, or an audit with too few cohort rows — and pins both the error and the
untouched state left behind.
"""
from test_helpers import (
    COMPLIANCE_OFFICER_USER_ID,
    DEFAULT_CLOCK,
    INCLUSION_REVIEWER_USER_ID,
    TEST_USERS,
    ApiErrorId,
    create_liveness_check_payload,
    create_live_client,
    create_cohort_metric_payload,
    decide_pathway,
    decide_review_case,
    draft_policy,
    create_verification_session_payload,
    evaluate_audit,
    finalize_attempt,
    list_session_attempts,
    list_session_audit_events,
    make_client_integrator_headers,
    make_compliance_officer_headers,
    make_inclusion_reviewer_headers,
    open_attempt,
    pathway_decision_payload,
    read_bias_audit,
    read_client,
    read_method_profile,
    read_policy,
    read_session,
    register_method_profile,
    set_clock,
    setup_age_gated_session,
    setup_assigned_review_case,
    setup_bias_audit_with_cohorts,
    setup_pending_pathway,
    setup_session,
    submit_document_capture,
    validate_error,
    validate_paginated,
)

ADMIN = TEST_USERS["platform_admin_headers"]

# Three balanced cohorts whose per-cohort false-reject rate is 500 basis points
# each, so the pooled rate is 500 and both disparity ratios come out at 10000.
BALANCED_COHORTS = [
    ("AGE_18_24", 100, 5),
    ("AGE_25_44", 200, 10),
    ("AGE_65_PLUS", 300, 15),
]

# A clean passport: every required security feature validated, no tamper signal
# and a valid machine-readable zone.
CLEAN_PASSPORT = {
    "document_type": "PASSPORT",
    "required_feature_count": 10,
    "passed_feature_count": 10,
    "tamper_signal_count": 0,
    "mrz_checksum_valid": True,
}


class TestTerminalStateRejections:
    def test_second_decision_on_an_approved_pathway_is_rejected_for_state(self, api):
        """PRD §2.6: "`ERR_PATHWAY_STATE_INVALID` (409) — the pathway is `VOUCH_PENDING`
        or `ATTESTATION_PENDING`. `POST /idv/alternative-pathways/{id}/decision`."
        PRD §3.7: "The five pathway states are `VOUCH_PENDING`, `ATTESTATION_PENDING`,
        `APPROVED`, `DENIED` and `WITHDRAWN`, of which the last three are terminal."
        PRD §3.7: "That attempt's `evidence_quality_bps` is 9000 basis points, its
        `contribution_points` is the granting profile's `assurance_weight` multiplied by
        9000, divided by ten thousand, truncated toward zero, and `granted_points` on the
        pathway records exactly that figure."

        Design: Corner/errors/second_decision_on_an_approved_pathway_is_rejected_for_state
        """
        env = setup_pending_pathway(
            pathway_type="VOUCHING",
            client_overrides={"name": "Acme PwState"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-pwstate"},
        )
        approved = decide_pathway(env["pathway"]["id"], "APPROVE")
        assert approved["state"] == "APPROVED", "setup must reach the terminal APPROVED state"

        response = api.decide_alternative_pathway(
            env["pathway"]["id"],
            pathway_decision_payload("DENY"),
            make_inclusion_reviewer_headers(INCLUSION_REVIEWER_USER_ID),
        )

        validate_error(response, ApiErrorId.ERR_PATHWAY_STATE_INVALID)

        pathways, _ = validate_paginated(
            api.list_alternative_pathways(
                env["session"]["id"], make_client_integrator_headers(env["client"]["id"])
            )
        )
        pathway = next(row for row in pathways if row["id"] == env["pathway"]["id"])
        assert pathway["state"] == "APPROVED"
        assert pathway["granted_points"] == 27
        assert pathway["reviewer_user_id"] == INCLUSION_REVIEWER_USER_ID

        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["assurance_score_provisional"] == 27
        assert session["assurance_ceiling"] == 100

        _, meta = list_session_attempts(env["session"]["id"])
        assert meta["total_count"] == 1, "the refused denial must mint no further attempt"

    def test_cohort_submission_after_evaluation_is_rejected_for_state(self, api):
        """PRD §2.6: "`ERR_AUDIT_STATE_INVALID` (409) — the audit is `COLLECTING` for
        cohort submission and evaluation, and `REMEDIATION_REQUIRED` for remediation.
        `POST /idv/bias-audits/{id}/cohort-metrics`, `POST /idv/bias-audits/{id}/evaluate`,
        `POST /idv/bias-audits/{id}/remediation`."
        PRD §3.9: "A gating ratio of 12500 or more restricts. A gating ratio of at least
        11000 but below 12500 monitors. A gating ratio below 11000 clears."

        Design: Corner/errors/cohort_submission_after_evaluation_is_rejected_for_state
        """
        set_clock(DEFAULT_CLOCK)
        profile = register_method_profile("DOCUMENT_SCAN")
        audit = setup_bias_audit_with_cohorts(
            profile["id"],
            cohorts=BALANCED_COHORTS,
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-07-01T00:00:00Z",
        )
        evaluate_audit(audit["id"])

        response = api.create_cohort_metric(
            audit["id"],
            create_cohort_metric_payload("AGE_45_64", 400, 60, 4),
            make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID),
        )

        validate_error(response, ApiErrorId.ERR_AUDIT_STATE_INVALID)

        _, meta = validate_paginated(
            api.list_cohort_metrics(
                audit["id"], make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID)
            )
        )
        assert meta["total_count"] == 3, "the refused row must not be stored"

        stored = read_bias_audit(audit["id"])
        assert stored["state"] == "EVALUATED"
        assert stored["pooled_frr_bps"] == 500
        assert stored["disparity_ratio_max_to_pooled_bps"] == 10000
        assert stored["disparity_ratio_max_to_min_bps"] == 10000
        assert read_method_profile(profile["id"])["bias_state"] == "CLEARED"


class TestPreconditionRejections:
    def test_biometric_evidence_without_recorded_consent_is_rejected(self, api):
        """PRD §3.5: "If the session recorded `biometric_consent` as false, the submission
        is rejected with `ERR_BIOMETRIC_CONSENT_REQUIRED`."
        PRD §3.5: "The minor-band gate is evaluated before the consent gate."

        Design: Corner/errors/biometric_evidence_without_recorded_consent_is_rejected
        """
        env = setup_session(
            method_codes=("BIOMETRIC_COMPARISON",),
            client_overrides={"name": "Acme NoConsent"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "external_subject_ref": "subj-noconsent",
                "biometric_consent": False,
            },
        )
        client_id = env["client"]["id"]
        attempt = open_attempt(
            env["session"]["id"], client_id, env["profiles"]["BIOMETRIC_COMPARISON"]["id"]
        )

        response = api.create_liveness_check(
            attempt["id"],
            create_liveness_check_payload(
                capture_modality="PASSIVE", pad_score_bps=9500, match_score_bps=9500
            ),
            make_client_integrator_headers(client_id),
        )

        error = validate_error(response, ApiErrorId.ERR_BIOMETRIC_CONSENT_REQUIRED)
        assert error["error_id"] != ApiErrorId.ERR_MINOR_BIOMETRIC_PROHIBITED.value, (
            "with no age gate the session has no resolved band, so the minor gate cannot fire"
        )

        session = read_session(env["session"]["id"], client_id)
        assert session["age_state"] == "NOT_REQUIRED"
        assert session["resolved_age_band"] is None

        attempts, _ = list_session_attempts(env["session"]["id"])
        stored_attempt = next(row for row in attempts if row["id"] == attempt["id"])
        assert stored_attempt["state"] == "AWAITING_EVIDENCE"
        assert read_client(client_id)["stored_template_count"] == 0

    def test_session_creation_without_any_published_policy_is_rejected(self, api):
        """PRD §3.2: "If the candidate set is empty the session is not created and the
        request fails with `ERR_NO_PUBLISHED_POLICY`."

        Design: Corner/errors/session_creation_without_any_published_policy_is_rejected
        """
        set_clock(DEFAULT_CLOCK)
        client = create_live_client(name="Acme NoPol")
        register_method_profile("DOCUMENT_SCAN")
        policy = draft_policy(
            client["id"], allowed_method_codes=["DOCUMENT_SCAN"], min_assurance_score=40
        )

        response = api.create_verification_session(
            create_verification_session_payload(
                client["id"], external_subject_ref="subj-nopol", requested_assurance_tier="BASIC"
            ),
            make_client_integrator_headers(client["id"]),
        )

        validate_error(response, ApiErrorId.ERR_NO_PUBLISHED_POLICY)

        _, meta = validate_paginated(
            api.list_verification_sessions(ADMIN, params={"client_id": client["id"]})
        )
        assert meta["total_count"] == 0, "a rejected open must create no session"

        stored_policy = read_policy(policy["id"])
        assert stored_policy["state"] == "DRAFT"
        assert stored_policy["published_at"] is None

    def test_attempt_naming_a_profile_outside_the_policy_ladder_is_rejected(self, api):
        """PRD §3.3: "The named profile is used, `selection_mode` is recorded as
        `CLIENT_REQUESTED`, and three gates apply in the order fixed by §2.6: first, a
        profile whose `method_code` is `VOUCHING_ATTESTATION` or `AGE_ESTIMATION` is
        refused with `ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE`, because those two methods are
        granted by adjudication and by the age axis respectively and can never appear in a
        policy's admitted list; then a profile whose `method_code` falls outside the pinned
        policy's `allowed_method_codes` is refused with `ERR_METHOD_NOT_IN_POLICY`; then a
        profile whose `bias_state` is `RESTRICTED` is refused with
        `ERR_METHOD_RESTRICTED_BY_BIAS`."

        Design: Corner/errors/attempt_naming_a_profile_outside_the_policy_ladder_is_rejected
        """
        env = setup_session(
            method_codes=("DOCUMENT_SCAN",),
            extra_profiles={"DATABASE_CHECK": {}},
            client_overrides={"name": "Acme NotInPol"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-notinpol"},
        )
        client_id = env["client"]["id"]

        response = api.create_method_attempt(
            env["session"]["id"],
            {"method_profile_id": env["profiles"]["DATABASE_CHECK"]["id"]},
            make_client_integrator_headers(client_id),
        )

        error = validate_error(response, ApiErrorId.ERR_METHOD_NOT_IN_POLICY)
        assert error["error_id"] != ApiErrorId.ERR_METHOD_NOT_DIRECTLY_ATTEMPTABLE.value, (
            "a database check is a directly attemptable method, so it clears the earlier gate"
        )

        _, meta = list_session_attempts(env["session"]["id"])
        assert meta["total_count"] == 0, "the refused request must open no attempt"
        assert read_session(env["session"]["id"], client_id)["identity_state"] == "IN_PROGRESS"

    def test_step_up_with_a_zero_round_budget_is_rejected(self, api):
        """PRD §3.6: "Requesting step-up requires the session to be at `AWAITING_EVIDENCE`,
        requires the clock not to be past `expires_at`, and requires `step_up_round` to
        still be below `step_up_max_rounds` — a session that has already consumed its
        budget is rejected with `ERR_STEP_UP_LIMIT_REACHED`."
        PRD §3.6: "A policy whose `step_up_max_rounds` is 0 therefore admits no step-up at
        all: a non-tamper rejection on such a session leaves the identity axis at
        `IN_PROGRESS` and the relying party's only route forward is completion or another
        method."

        Design: Corner/errors/step_up_with_a_zero_round_budget_is_rejected
        """
        env = setup_assigned_review_case(
            client_overrides={"name": "Acme Budget0"},
            policy_overrides={"min_assurance_score": 60, "step_up_max_rounds": 0},
            session_overrides={"external_subject_ref": "subj-budget0"},
        )
        client_id = env["client"]["id"]
        decide_review_case(env["case"]["id"], "RETURN_FOR_STEP_UP")

        response = api.step_up_session(
            env["session"]["id"], make_client_integrator_headers(client_id)
        )

        validate_error(response, ApiErrorId.ERR_STEP_UP_LIMIT_REACHED)

        session = read_session(env["session"]["id"], client_id)
        assert session["identity_state"] == "AWAITING_EVIDENCE"
        assert session["step_up_round"] == 0
        assert read_client(client_id)["pending_stepup_count"] == 1, (
            "the rejected step-up must leave the client's pending counter untouched"
        )
        _, meta = list_session_audit_events(env["session"]["id"], "STEP_UP_TRIGGERED")
        assert meta["total_count"] == 0, "no step-up event may be appended for a refusal"


class TestCompletionGuardRejections:
    def test_completion_with_a_pending_pathway_is_rejected(self, api):
        """PRD §3.8: "It further requires that no attempt of the session is still open in
        `AWAITING_EVIDENCE`, `SCORED` or `REQUIRES_RESCORE`, otherwise
        `ERR_ATTEMPT_PENDING_FINALIZATION`; that no pathway of the session is still in
        `VOUCH_PENDING` or `ATTESTATION_PENDING`, otherwise
        `ERR_PENDING_PATHWAY_BLOCKS_COMPLETION`; and that, when the pinned policy sets
        `required_min_age_years` above zero, `age_state` is no longer `PENDING`, otherwise
        `ERR_AGE_ASSURANCE_MISSING`."

        Design: Corner/errors/completion_with_a_pending_pathway_is_rejected
        """
        env = setup_pending_pathway(
            pathway_type="VOUCHING",
            client_overrides={"name": "Acme PendPath"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-pendpath"},
        )
        client_id = env["client"]["id"]

        response = api.complete_session(
            env["session"]["id"], make_client_integrator_headers(client_id)
        )

        error = validate_error(response, ApiErrorId.ERR_PENDING_PATHWAY_BLOCKS_COMPLETION)
        assert error["error_id"] != ApiErrorId.ERR_ATTEMPT_PENDING_FINALIZATION.value, (
            "with no attempt in flight the attempt-pending guard passes"
        )

        session = read_session(env["session"]["id"], client_id)
        assert session["identity_state"] == "IN_PROGRESS"
        assert session["assurance_score_final"] is None
        assert session["completed_at"] is None

        pathways, _ = validate_paginated(
            api.list_alternative_pathways(
                env["session"]["id"], make_client_integrator_headers(client_id)
            )
        )
        pathway = next(row for row in pathways if row["id"] == env["pathway"]["id"])
        assert pathway["state"] == "VOUCH_PENDING"

    def test_completion_with_the_age_axis_still_pending_is_rejected(self, api):
        """PRD §3.8: "It further requires that no attempt of the session is still open in
        `AWAITING_EVIDENCE`, `SCORED` or `REQUIRES_RESCORE`, otherwise
        `ERR_ATTEMPT_PENDING_FINALIZATION`; that no pathway of the session is still in
        `VOUCH_PENDING` or `ATTESTATION_PENDING`, otherwise
        `ERR_PENDING_PATHWAY_BLOCKS_COMPLETION`; and that, when the pinned policy sets
        `required_min_age_years` above zero, `age_state` is no longer `PENDING`, otherwise
        `ERR_AGE_ASSURANCE_MISSING`."
        PRD §3.2: "The age axis, `age_state`, moves among `NOT_REQUIRED`, `PENDING`,
        `ASSURED` and `FAILED`; it starts at `NOT_REQUIRED` when the pinned policy sets
        `required_min_age_years` to 0, and at `PENDING` otherwise."

        Design: Corner/errors/completion_with_the_age_axis_still_pending_is_rejected
        """
        env = setup_age_gated_session(
            required_min_age_years=18,
            method_codes=("DOCUMENT_SCAN",),
            client_overrides={"name": "Acme AgeMiss"},
            policy_overrides={"min_assurance_score": 40},
            session_overrides={"external_subject_ref": "subj-agemiss"},
        )
        client_id = env["client"]["id"]
        attempt = open_attempt(
            env["session"]["id"], client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
        )
        submit_document_capture(attempt["id"], client_id, **CLEAN_PASSPORT)
        finalized = finalize_attempt(attempt["id"], client_id)
        assert finalized["state"] == "ACCEPTED", "setup must accept the document attempt"

        response = api.complete_session(
            env["session"]["id"], make_client_integrator_headers(client_id)
        )

        validate_error(response, ApiErrorId.ERR_AGE_ASSURANCE_MISSING)

        session = read_session(env["session"]["id"], client_id)
        assert session["age_state"] == "PENDING"
        assert session["resolved_age_band"] is None
        assert session["identity_state"] == "IN_PROGRESS"
        assert session["assurance_score_provisional"] == 45
        assert session["assurance_score_final"] is None


class TestCoverageRejections:
    def test_evaluation_with_only_two_cohorts_is_rejected_for_coverage(self, api):
        """PRD §3.9: "If fewer than 3 rows are in scope, the evaluation is refused with
        `ERR_INSUFFICIENT_COHORT_COVERAGE` before any figure is computed."

        Design: Corner/errors/evaluation_with_only_two_cohorts_is_rejected_for_coverage
        """
        set_clock(DEFAULT_CLOCK)
        profile = register_method_profile("DOCUMENT_SCAN")
        audit = setup_bias_audit_with_cohorts(
            profile["id"],
            cohorts=[("AGE_18_24", 100, 5), ("AGE_25_44", 200, 3)],
            window_start="2026-06-01T00:00:00Z",
            window_end="2026-07-01T00:00:00Z",
        )

        response = api.evaluate_bias_audit(
            audit["id"], make_compliance_officer_headers(COMPLIANCE_OFFICER_USER_ID)
        )

        validate_error(response, ApiErrorId.ERR_INSUFFICIENT_COHORT_COVERAGE)

        stored = read_bias_audit(audit["id"])
        assert stored["state"] == "COLLECTING"
        assert stored["pooled_frr_bps"] is None
        assert stored["included_cohort_count"] == 0
        assert stored["insufficient_sample"] is False
        assert stored["evaluated_by_user_id"] is None

        stored_profile = read_method_profile(profile["id"])
        assert stored_profile["bias_state"] == "CLEARED"
        assert stored_profile["version"] == 1
