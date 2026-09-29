"""Which error surfaces when two guards on one endpoint fail at the same time."""
from test_helpers import (
    create_verification_session_payload,
    list_session_attempts,
    make_client_integrator_headers,
    open_session,
    patch_client,
    read_client,
    read_session,
    restrict_profile_by_bias,
    set_clock,
    setup_client_with_published_policy,
    setup_scored_document_attempt,
    setup_session_in_manual_review_from_fraud,
    validate_error,
    validate_paginated,
)

STANDARD_POLICY = {
    "min_assurance_score": 60,
    "doc_authenticity_floor_bps": 8000,
    "required_min_age_years": 0,
    "step_up_max_rounds": 2,
}


def _escalated_session_and_an_unadmitted_profile():
    """A session sitting in review, plus a profile the pinned policy never admitted."""
    return setup_session_in_manual_review_from_fraud(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 2},
        policy_overrides=dict(STANDARD_POLICY),
        session_overrides={"external_subject_ref": "subj-r5a"},
        extra_profiles={"KNOWLEDGE_BASED": {}},
    )


class TestSessionStateOutranksMethodMembership:
    def test_the_session_state_error_is_reported_rather_than_the_membership_error(self, api):
        """PRD §2.6: "Checks are evaluated strictly in the order listed below, and the first failing
        check determines the response." The state check is listed as "`ERR_SESSION_STATE_INVALID`
        (409) — the session is in a state the operation admits. Every session-mutating endpoint."
        and the later membership check as "`ERR_METHOD_NOT_IN_POLICY` (409) — an explicitly
        requested profile's method is admitted by the pinned policy."

        Design: Difficulty/priority_pair_validation_conflict/session_state_error_outranks_method_not_in_policy_error
        """
        env = _escalated_session_and_an_unadmitted_profile()
        error = validate_error(
            api.create_method_attempt(
                env["session"]["id"],
                {"method_profile_id": env["profiles"]["KNOWLEDGE_BASED"]["id"]},
                env["headers"],
            ),
            "ERR_SESSION_STATE_INVALID",
            409,
        )

        assert error["error_id"] != "ERR_METHOD_NOT_IN_POLICY"

    def test_the_rejected_request_adds_no_attempt_and_leaves_the_session_in_review(self, api):
        """PRD §3.3: "A `ClientIntegrator` opens one against a session that is `IN_PROGRESS` and not
        lapsed, whose client is not `SUSPENDED`, and whose pinned policy is still `PUBLISHED`."
        PRD §2.6: "`ERR_SESSION_STATE_INVALID` (409) — the session is in a state the operation
        admits. Every session-mutating endpoint."

        Design: Difficulty/priority_pair_validation_conflict/session_state_error_outranks_method_not_in_policy_error
        """
        env = _escalated_session_and_an_unadmitted_profile()
        validate_error(
            api.create_method_attempt(
                env["session"]["id"],
                {"method_profile_id": env["profiles"]["KNOWLEDGE_BASED"]["id"]},
                env["headers"],
            ),
            "ERR_SESSION_STATE_INVALID",
        )

        attempts, meta = list_session_attempts(env["session"]["id"])
        assert meta["total_count"] == 1
        assert attempts[0]["id"] == env["attempt"]["id"]
        assert read_session(env["session"]["id"], env["client"]["id"])["identity_state"] == (
            "MANUAL_REVIEW"
        )


def _suspended_client_whose_quota_is_also_exhausted():
    """A suspended client whose rolling window already holds its single session."""
    env = setup_client_with_published_policy(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"daily_session_quota": 1, "granted_review_credits": 1},
        policy_overrides=dict(STANDARD_POLICY),
    )
    env["first_session"] = open_session(
        env["client"]["id"],
        external_subject_ref="subj-r5b-1",
        requested_assurance_tier="BASIC",
    )
    patch_client(env["client"]["id"], integration_state="SUSPENDED")
    return env


class TestClientPostureOutranksQuotaExhaustion:
    def test_the_posture_error_is_reported_rather_than_the_quota_error(self, api):
        """PRD §2.6 lists the posture check as "`ERR_CLIENT_NOT_LIVE` (409) — the client's
        integration posture admits the operation." ahead of "`ERR_CLIENT_DAILY_QUOTA_EXCEEDED`
        (409) — the client's rolling-window session count is below its quota.", and "the first
        failing check determines the response".

        Design: Difficulty/priority_pair_validation_conflict/client_not_live_error_outranks_daily_quota_exhaustion
        """
        env = _suspended_client_whose_quota_is_also_exhausted()
        client_id = env["client"]["id"]
        error = validate_error(
            api.create_verification_session(
                create_verification_session_payload(
                    client_id,
                    external_subject_ref="subj-r5b-2",
                    requested_assurance_tier="BASIC",
                ),
                make_client_integrator_headers(client_id),
            ),
            "ERR_CLIENT_NOT_LIVE",
            409,
        )

        assert error["error_id"] != "ERR_CLIENT_DAILY_QUOTA_EXCEEDED"

    def test_no_second_session_is_created_for_the_suspended_client(self, api):
        """PRD §3.2: "Opening a session requires the client's `integration_state` to be exactly
        `LIVE`. A client still in `SANDBOX`, or one that has been `SUSPENDED`, is rejected with
        `ERR_CLIENT_NOT_LIVE`".

        Design: Difficulty/priority_pair_validation_conflict/client_not_live_error_outranks_daily_quota_exhaustion
        """
        env = _suspended_client_whose_quota_is_also_exhausted()
        client_id = env["client"]["id"]
        validate_error(
            api.create_verification_session(
                create_verification_session_payload(
                    client_id,
                    external_subject_ref="subj-r5b-2",
                    requested_assurance_tier="BASIC",
                ),
                make_client_integrator_headers(client_id),
            ),
            "ERR_CLIENT_NOT_LIVE",
        )

        sessions, meta = validate_paginated(
            api.list_verification_sessions(
                make_client_integrator_headers(client_id), params={"client_id": client_id}
            )
        )
        assert meta["total_count"] == 1
        assert sessions[0]["id"] == env["first_session"]["id"]
        assert read_client(client_id)["integration_state"] == "SUSPENDED"


def _lapsed_session_parked_without_any_step_up_budget():
    """A parked session whose window closed and whose step-up budget was always zero."""
    set_clock("2026-08-10T09:00:00Z")
    env = setup_scored_document_attempt(
        capture_overrides={
            "document_type": "PASSPORT",
            "required_feature_count": 16,
            "passed_feature_count": 14,
            "tamper_signal_count": 0,
            "mrz_checksum_valid": True,
        },
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 1},
        policy_overrides={
            "min_assurance_score": 60,
            "doc_authenticity_floor_bps": 8000,
            "required_min_age_years": 0,
            "step_up_max_rounds": 0,
        },
        session_overrides={"external_subject_ref": "subj-r5c"},
    )
    restrict_profile_by_bias(env["profiles"]["DOCUMENT_SCAN"]["id"])
    set_clock("2026-08-10T10:00:01Z")
    return env


class TestSessionExpiryOutranksStepUpBudget:
    def test_the_expiry_error_is_reported_rather_than_the_step_up_limit_error(self, api):
        """PRD §2.6 lists "`ERR_SESSION_EXPIRED` (409) — the session has not lapsed. Every
        session-mutating endpoint and every attempt-mutating endpoint." ahead of
        "`ERR_STEP_UP_LIMIT_REACHED` (409) — step-up budget remains.", and "the first failing check
        determines the response".

        Design: Difficulty/priority_pair_validation_conflict/session_expiry_error_outranks_step_up_limit_error
        """
        env = _lapsed_session_parked_without_any_step_up_budget()
        error = validate_error(
            api.step_up_session(env["session"]["id"], env["headers"]),
            "ERR_SESSION_EXPIRED",
            409,
        )

        assert error["error_id"] != "ERR_STEP_UP_LIMIT_REACHED"

    def test_the_lapsed_session_keeps_its_parked_axis_and_its_step_up_counter(self, api):
        """PRD §3.2: "A session is treated as lapsed by every mutating endpoint as soon as the clock
        is strictly past `expires_at`, and such requests are rejected with `ERR_SESSION_EXPIRED` —
        even before the operations sweep has materialised the lapse as an `EXPIRED` identity state."

        Design: Difficulty/priority_pair_validation_conflict/session_expiry_error_outranks_step_up_limit_error
        """
        env = _lapsed_session_parked_without_any_step_up_budget()
        validate_error(
            api.step_up_session(env["session"]["id"], env["headers"]), "ERR_SESSION_EXPIRED"
        )

        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["identity_state"] == "AWAITING_EVIDENCE"
        assert session["step_up_round"] == 0
        assert read_client(env["client"]["id"])["pending_stepup_count"] == 1
