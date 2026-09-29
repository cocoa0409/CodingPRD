"""Independent session axes and the two-branch inclusion pathway fork."""
from test_helpers import (
    decide_pathway,
    finalize_attempt,
    list_session_age_results,
    list_session_attempts,
    open_attempt,
    open_session,
    read_client,
    read_attempt,
    read_session,
    record_estimation_result,
    request_pathway,
    setup_age_gated_session,
    setup_client_with_published_policy,
    submit_document_capture,
    step_up,
)


def _session_with_failed_age_axis_and_awaiting_identity_axis():
    """An age axis that failed and then cleared, while the identity axis parked."""
    env = setup_age_gated_session(
        required_min_age_years=18,
        age_buffer_multiplier_bps=15000,
        estimation_mae_months=18,
        method_codes=("DOCUMENT_SCAN",),
        policy_overrides={
            "min_assurance_score": 30,
            "doc_authenticity_floor_bps": 8000,
            "step_up_max_rounds": 2,
        },
        session_overrides={"external_subject_ref": "subj-r3a"},
    )
    client_id = env["client"]["id"]
    session_id = env["session"]["id"]
    estimation_profile_id = env["profiles"]["AGE_ESTIMATION"]["id"]

    record_estimation_result(session_id, client_id, estimation_profile_id, 242)

    attempt = open_attempt(session_id, client_id, env["profiles"]["DOCUMENT_SCAN"]["id"])
    submit_document_capture(
        attempt["id"],
        client_id,
        document_type="DRIVERS_LICENSE",
        required_feature_count=8,
        passed_feature_count=7,
        tamper_signal_count=2,
        mrz_checksum_valid=True,
    )
    env["attempt"] = finalize_attempt(attempt["id"], client_id)

    record_estimation_result(session_id, client_id, estimation_profile_id, 243)
    return env


class TestIdentityAndAgeAxesAdvanceIndependently:
    def test_step_up_returns_the_identity_axis_without_disturbing_the_assured_age_axis(self):
        """PRD §3.2: "The two axes progress entirely independently of one another." PRD §3.6:
        "On success the session moves `AWAITING_EVIDENCE → IN_PROGRESS`, `step_up_round`
        increases by one, the client's `pending_stepup_count` decreases by one, and an audit
        event of type `STEP_UP_TRIGGERED` is appended."

        Design: Difficulty/non_linear_state_machine/session_identity_and_age_axes_advance_independently_across_step_up_cycle
        """
        env = _session_with_failed_age_axis_and_awaiting_identity_axis()
        client_id = env["client"]["id"]

        parked = read_session(env["session"]["id"], client_id)
        assert parked["identity_state"] == "AWAITING_EVIDENCE"
        assert parked["age_state"] == "ASSURED"

        session = step_up(env["session"]["id"], client_id)
        assert session["identity_state"] == "IN_PROGRESS"
        assert session["age_state"] == "ASSURED"
        assert session["step_up_round"] == 1
        assert read_client(client_id)["pending_stepup_count"] == 0

    def test_age_axis_re_enters_upward_from_failed_to_assured_on_the_newest_result(self):
        """PRD §3.7: "`buffer_months` is `mae_months_snapshot` multiplied by the pinned policy's
        `age_buffer_multiplier_bps`, divided by ten thousand, rounded *up* to a whole month."
        "The `decision` is `ASSURED` when `effective_age_months` is at or above
        `required_min_age_years` multiplied by twelve, and `FAILED` otherwise; an effective age
        exactly equal to the gate is `ASSURED`."

        Design: Difficulty/non_linear_state_machine/session_identity_and_age_axes_advance_independently_across_step_up_cycle
        """
        env = _session_with_failed_age_axis_and_awaiting_identity_axis()
        results, meta = list_session_age_results(env["session"]["id"], env["client"]["id"])

        assert meta["total_count"] == 2
        assert results[0]["effective_age_months"] == 215
        assert results[0]["resolved_band"] == "B16_17"
        assert results[0]["decision"] == "FAILED"
        assert results[1]["buffer_months"] == 27
        assert results[1]["effective_age_months"] == 216
        assert results[1]["resolved_band"] == "B18_20"
        assert results[1]["decision"] == "ASSURED"
        assert results[1]["documented_accuracy_bps"] == 9400

    def test_resolved_age_band_tracks_the_most_recent_result_after_the_step_up(self):
        """PRD §3.7: "Regardless of the decision, the session's `resolved_age_band` is set to
        the `resolved_band` of the most recent result, which is why a failed estimate that banded a
        subject at `U13` immediately blocks any further biometric capture on that session and, at
        closure, forces minor-protection deletion of any template already held."

        Design: Difficulty/non_linear_state_machine/session_identity_and_age_axes_advance_independently_across_step_up_cycle
        """
        env = _session_with_failed_age_axis_and_awaiting_identity_axis()
        session = step_up(env["session"]["id"], env["client"]["id"])

        assert session["resolved_age_band"] == "B18_20"

    def test_suspect_document_rejection_without_a_tamper_flag_parks_the_identity_axis(self):
        """PRD §3.6: "A document-scan attempt whose capture was assessed `FORGED` records
        `DOCUMENT_FORGED` and additionally sets the attempt's `tamper_flag` to true; a document-scan
        attempt whose capture was assessed anything else records `DOCUMENT_SUSPECT`." "When a
        rejection carries `tamper_flag` false and the session's `step_up_round` is still below the
        pinned policy's `step_up_max_rounds`, the session instead moves
        `IN_PROGRESS → AWAITING_EVIDENCE`: the provisional score is recomputed, the client's
        `pending_stepup_count` increases by one, and the audit event appended is of type
        `ATTEMPT_FINALIZED`."

        Design: Difficulty/non_linear_state_machine/session_identity_and_age_axes_advance_independently_across_step_up_cycle
        """
        env = _session_with_failed_age_axis_and_awaiting_identity_axis()
        attempt = read_attempt(env["attempt"]["id"], env["client"]["id"])

        assert attempt["evidence_quality_bps"] == 7400
        assert attempt["state"] == "REJECTED"
        assert attempt["tamper_flag"] is False
        assert attempt["rejection_reason"] == "DOCUMENT_SUSPECT"


def _two_sessions_forked_on_pathway_type():
    """One vouching pathway already approved and one attestation pathway still pending."""
    env = setup_client_with_published_policy(
        method_codes=("DOCUMENT_SCAN",),
        client_overrides={"granted_review_credits": 2},
        policy_overrides={
            "min_assurance_score": 60,
            "doc_authenticity_floor_bps": 8000,
            "required_min_age_years": 0,
            "step_up_max_rounds": 2,
            "alternative_pathway_enabled": True,
        },
        extra_profiles={"VOUCHING_ATTESTATION": {}},
    )
    client_id = env["client"]["id"]

    env["vouching_session"] = open_session(
        client_id,
        external_subject_ref="subj-r3c-vouch",
        documentation_status="NO_STANDARD_DOCS",
    )
    vouching_pathway = request_pathway(
        env["vouching_session"]["id"], client_id, "VOUCHING", voucher_reference="VCH-1"
    )
    env["vouching_pathway"] = decide_pathway(vouching_pathway["id"], "APPROVE")

    env["attestation_session"] = open_session(
        client_id,
        external_subject_ref="subj-r3c-attest",
        documentation_status="NO_STANDARD_DOCS",
    )
    env["attestation_pathway"] = request_pathway(
        env["attestation_session"]["id"],
        client_id,
        "ATTESTATION",
        attestation_document_ref="ATT-1",
    )
    return env


class TestPathwayForkRejoinsWithDivergentSideEffects:
    def test_both_branches_reach_approved_with_type_specific_granted_points(self):
        """PRD §3.7: for a vouching approval "That attempt's `evidence_quality_bps` is 9000
        basis points, its `contribution_points` is the granting profile's `assurance_weight`
        multiplied by 9000, divided by ten thousand, truncated toward zero, and `granted_points`
        on the pathway records exactly that figure." For attestation, "That attempt's
        `evidence_quality_bps` is 7000 basis points rather than 9000".

        Design: Difficulty/non_linear_state_machine/alternative_pathway_fork_joins_with_type_specific_ceiling_side_effects
        """
        env = _two_sessions_forked_on_pathway_type()
        attestation = decide_pathway(env["attestation_pathway"]["id"], "APPROVE")

        assert env["vouching_pathway"]["state"] == "APPROVED"
        assert env["vouching_pathway"]["granted_points"] == 27
        assert env["vouching_pathway"]["reviewer_user_id"] == "ir-1"
        assert attestation["state"] == "APPROVED"
        assert attestation["granted_points"] == 21

    def test_only_the_attestation_branch_lowers_the_session_assurance_ceiling(self):
        """PRD §3.7: "the session's `assurance_ceiling` is lowered from 100 to 70, permanently
        capping what a self-attested subject can be certified at. Because the ceiling is only
        consulted when the final score is written, lowering it changes nothing about the running
        provisional figure." For vouching, "The session's `assurance_ceiling` is left at 100."

        Design: Difficulty/non_linear_state_machine/alternative_pathway_fork_joins_with_type_specific_ceiling_side_effects
        """
        env = _two_sessions_forked_on_pathway_type()
        decide_pathway(env["attestation_pathway"]["id"], "APPROVE")
        client_id = env["client"]["id"]

        vouching_session = read_session(env["vouching_session"]["id"], client_id)
        attestation_session = read_session(env["attestation_session"]["id"], client_id)
        assert vouching_session["assurance_ceiling"] == 100
        assert vouching_session["assurance_score_provisional"] == 27
        assert attestation_session["assurance_ceiling"] == 70
        assert attestation_session["assurance_score_provisional"] == 21

    def test_each_approval_mints_one_accepted_pathway_granted_attempt(self):
        """PRD §3.7: "a method attempt is created and carried all the way to `ACCEPTED` inside
        the same request with `selection_mode` of `PATHWAY_GRANTED`, moving
        `AWAITING_EVIDENCE → ACCEPTED` directly with `finalized_at` set to the clock."

        Design: Difficulty/non_linear_state_machine/alternative_pathway_fork_joins_with_type_specific_ceiling_side_effects
        """
        env = _two_sessions_forked_on_pathway_type()
        decide_pathway(env["attestation_pathway"]["id"], "APPROVE")

        vouching_attempts, vouching_meta = list_session_attempts(env["vouching_session"]["id"])
        assert vouching_meta["total_count"] == 1
        assert vouching_attempts[0]["method_code"] == "VOUCHING_ATTESTATION"
        assert vouching_attempts[0]["selection_mode"] == "PATHWAY_GRANTED"
        assert vouching_attempts[0]["state"] == "ACCEPTED"
        assert vouching_attempts[0]["evidence_quality_bps"] == 9000
        assert vouching_attempts[0]["finalized_at"] is not None

        attestation_attempts, attestation_meta = list_session_attempts(
            env["attestation_session"]["id"]
        )
        assert attestation_meta["total_count"] == 1
        assert attestation_attempts[0]["selection_mode"] == "PATHWAY_GRANTED"
        assert attestation_attempts[0]["state"] == "ACCEPTED"
        assert attestation_attempts[0]["evidence_quality_bps"] == 7000

    def test_undocumented_subject_sessions_carry_the_documentation_risk_bump(self):
        """PRD §3.2: "A further 10 points are added when `documentation_status` is
        `NO_STANDARD_DOCS`." "The derived `risk_level` is `HIGH` when the score is 70 or more,
        `MEDIUM` when the score is at least 40 and below 70, and `LOW` otherwise — so a `STANDARD`
        request declaring exactly 25,000 cents scores exactly 40 and lands precisely on the
        `MEDIUM` boundary."

        Design: Difficulty/non_linear_state_machine/alternative_pathway_fork_joins_with_type_specific_ceiling_side_effects
        """
        env = _two_sessions_forked_on_pathway_type()

        assert env["vouching_session"]["risk_score"] == 40
        assert env["vouching_session"]["risk_level"] == "MEDIUM"
