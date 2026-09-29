"""Scoring arithmetic: document authenticity, evidence quality, assurance
summation, frozen risk scoring and pooled cohort rates.

Every figure asserted here is an integer basis-point or point value derived by
the ordered formulas of the identity-verification contract.
"""
from datetime import datetime

from test_helpers import (
    FORGED_CAPTURE,
    MANUAL_REVIEWER_USER_ID,
    TEST_USERS,
    add_cohort_metric,
    assign_case_payload,
    create_document_capture_payload,
    create_verification_session_payload,
    decide_pathway,
    decide_review_case,
    finalize_attempt,
    list_session_cases,
    make_client_integrator_headers,
    make_compliance_officer_headers,
    make_review_manager_headers,
    open_attempt,
    open_bias_audit,
    open_session,
    read_attempt,
    read_bias_audit,
    read_client,
    read_method_profile,
    read_session,
    request_pathway,
    setup_client_with_published_policy,
    setup_session,
    submit_database_evidence,
    submit_document_capture,
    validate_paginated,
    validate_success,
)

ADMIN_HEADERS = TEST_USERS["platform_admin_headers"]


def assert_same_instant(actual: str, expected: str) -> None:
    """Compare two server timestamps as instants, ignoring fractional form."""
    def parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    assert actual is not None, f"expected an instant equal to {expected}, got null"
    assert parse(actual) == parse(expected), f"expected instant {expected}, got {actual}"


class TestDocumentAuthenticityArithmetic:
    """The six ordered steps that turn a capture into an authenticity verdict."""

    def test_mrz_cap_applies_after_the_tamper_penalty(self, api):
        """PRD §3.4: "Fifth, the machine-readable-zone cap is applied *after* the tamper
        penalty, never before it: when `mrz_checksum_valid` is false, `authenticity_score_bps`
        is the lesser of the raw score and 4000 basis points; when the checksum validated,
        `authenticity_score_bps` is the raw score unchanged."
        PRD §3.4: "Second, `tamper_tier_multiplier_bps` is read off the *pre-penalty* base
        score, never off any later figure."

        Design: Corner/calculations/mrz_cap_applied_after_the_tamper_penalty_not_before
        """
        env = setup_session(
            method_codes=("DOCUMENT_SCAN",),
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "requested_assurance_tier": "BASIC",
                "external_subject_ref": "subj-mrz",
            },
        )
        client_id = env["client"]["id"]
        attempt = open_attempt(
            env["session"]["id"], client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
        )

        response = api.create_document_capture(
            attempt["id"],
            create_document_capture_payload(
                document_type="NATIONAL_ID",
                required_feature_count=10,
                passed_feature_count=9,
                tamper_signal_count=1,
                mrz_checksum_valid=False,
            ),
            make_client_integrator_headers(client_id),
        )
        capture = validate_success(response, 201)

        assert capture["base_score_bps"] == 9000, (
            f"nine of ten validated features score 9000 bps, got {capture['base_score_bps']}"
        )
        assert capture["tamper_tier_multiplier_bps"] == 10000
        assert capture["tamper_penalty_bps"] == 450
        assert capture["authenticity_score_bps"] == 4000, (
            "the invalid checksum caps the post-penalty score at 4000 bps, got "
            f"{capture['authenticity_score_bps']}"
        )
        assert capture["assessment"] == "FORGED"

    def test_mrz_capped_score_becomes_the_attempt_evidence_quality(self, api):
        """PRD §3.4: "The capture's `authenticity_score_bps` becomes the attempt's
        `evidence_quality_bps` verbatim, and the attempt's `contribution_points` is the
        resolved profile's `assurance_weight` multiplied by that quality, divided by ten
        thousand, truncated toward zero."
        PRD §3.6: "A rejection also records why, in `rejection_reason`. A document-scan
        attempt whose capture was assessed `FORGED` records `DOCUMENT_FORGED` and
        additionally sets the attempt's `tamper_flag` to true"

        Design: Corner/calculations/mrz_cap_applied_after_the_tamper_penalty_not_before
        """
        env = setup_session(
            method_codes=("DOCUMENT_SCAN",),
            policy_overrides={"min_assurance_score": 40},
            session_overrides={
                "requested_assurance_tier": "BASIC",
                "external_subject_ref": "subj-mrz",
            },
        )
        client_id = env["client"]["id"]
        attempt = open_attempt(
            env["session"]["id"], client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
        )
        submit_document_capture(
            attempt["id"],
            client_id,
            document_type="NATIONAL_ID",
            required_feature_count=10,
            passed_feature_count=9,
            tamper_signal_count=1,
            mrz_checksum_valid=False,
        )

        scored = read_attempt(attempt["id"], client_id)
        assert scored["state"] == "SCORED"
        assert scored["evidence_quality_bps"] == 4000
        assert scored["contribution_points"] == 18, (
            f"45 * 4000 / 10000 truncates to 18 points, got {scored['contribution_points']}"
        )
        assert scored["tamper_flag"] is False, "the tamper flag is only written by finalisation"

        session = read_session(env["session"]["id"], client_id)
        assert session["assurance_score_provisional"] == 18


class TestAssuranceSummation:
    """Provisional and final assurance figures over the same attempt set."""

    def test_provisional_score_drops_the_attempt_finalisation_rejected(self, api):
        """PRD §3.8: "`assurance_score_provisional` is the running view a relying party can
        watch during collection: it sums the `contribution_points` of every attempt of the
        session currently in `SCORED` or `ACCEPTED`, and caps the sum at 100."
        PRD §3.6: "A `SCORED` attempt whose `evidence_quality_bps` is at or above the
        resolved profile's `acceptance_floor_bps` advances `SCORED → ACCEPTED`; one below the
        floor advances `SCORED → REJECTED`."
        PRD §3.6: "A policy whose `step_up_max_rounds` is 0 therefore admits no step-up at
        all: a non-tamper rejection on such a session leaves the identity axis at
        `IN_PROGRESS` and the relying party's only route forward is completion or another
        method."

        Design: Corner/calculations/provisional_score_drops_the_attempt_that_finalisation_rejected
        """
        env = setup_session(
            method_codes=("DOCUMENT_SCAN",),
            policy_overrides={"min_assurance_score": 40, "step_up_max_rounds": 0},
            session_overrides={
                "requested_assurance_tier": "BASIC",
                "external_subject_ref": "subj-filt",
            },
        )
        client_id = env["client"]["id"]
        session_id = env["session"]["id"]
        profile_id = env["profiles"]["DOCUMENT_SCAN"]["id"]

        first = open_attempt(session_id, client_id, profile_id)
        submit_document_capture(
            first["id"],
            client_id,
            document_type="PASSPORT",
            required_feature_count=10,
            passed_feature_count=10,
            tamper_signal_count=0,
            mrz_checksum_valid=True,
        )
        finalize_attempt(first["id"], client_id)

        second = open_attempt(session_id, client_id, profile_id)
        submit_document_capture(
            second["id"],
            client_id,
            document_type="DRIVERS_LICENSE",
            required_feature_count=8,
            passed_feature_count=7,
            tamper_signal_count=2,
            mrz_checksum_valid=True,
        )
        assert read_session(session_id, client_id)["assurance_score_provisional"] == 78

        response = api.finalize_method_attempt(
            second["id"], make_client_integrator_headers(client_id)
        )
        finalized = validate_success(response, 200)

        assert finalized["state"] == "REJECTED"
        assert finalized["rejection_reason"] == "DOCUMENT_SUSPECT"
        assert finalized["tamper_flag"] is False, "a SUSPECT assessment raises no tamper flag"
        assert finalized["contribution_points"] == 33, (
            "the rejected row keeps its 33 contribution points, got "
            f"{finalized['contribution_points']}"
        )

        session = read_session(session_id, client_id)
        assert session["assurance_score_provisional"] == 45, (
            "the rejected attempt leaves the SCORED-or-ACCEPTED input set, got "
            f"{session['assurance_score_provisional']}"
        )
        assert session["identity_state"] == "IN_PROGRESS"
        assert read_client(client_id)["pending_stepup_count"] == 0

    def test_final_score_clamps_to_the_attestation_lowered_ceiling(self, api):
        """PRD §3.8: "The sum is capped at 100 and then capped again at the session's
        `assurance_ceiling`, whichever bound bites first."
        PRD §3.7: "And the session's `assurance_ceiling` is lowered from 100 to 70,
        permanently capping what a self-attested subject can be certified at."
        PRD §3.8: "When the age axis is not failed and the freshly written
        `assurance_score_final` is at or above the pinned policy's `min_assurance_score`, the
        session moves `IN_PROGRESS → VERIFIED` with `disposition_reason` set to
        `SCORE_SATISFIED`, `completed_at` set to the clock, the same retention schedule
        applied and the same `SESSION_TERMINAL` event appended."

        Design: Corner/calculations/final_variant_clamps_to_the_attestation_lowered_ceiling
        """
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN", "DATABASE_CHECK"),
            policy_overrides={"min_assurance_score": 40},
            extra_profiles={"VOUCHING_ATTESTATION": {}},
        )
        client_id = env["client"]["id"]
        session = open_session(
            client_id,
            external_subject_ref="subj-ceil",
            requested_assurance_tier="BASIC",
            documentation_status="NO_STANDARD_DOCS",
        )
        session_id = session["id"]

        document_attempt = open_attempt(
            session_id, client_id, env["profiles"]["DOCUMENT_SCAN"]["id"]
        )
        submit_document_capture(
            document_attempt["id"],
            client_id,
            document_type="PASSPORT",
            required_feature_count=10,
            passed_feature_count=10,
            tamper_signal_count=0,
            mrz_checksum_valid=True,
        )
        finalize_attempt(document_attempt["id"], client_id)

        database_attempt = open_attempt(
            session_id, client_id, env["profiles"]["DATABASE_CHECK"]["id"]
        )
        submit_database_evidence(database_attempt["id"], client_id, 10, 10)
        finalize_attempt(database_attempt["id"], client_id)

        pathway = request_pathway(session_id, client_id, "ATTESTATION")
        approved = decide_pathway(pathway["id"], "APPROVE")
        assert approved["state"] == "APPROVED"
        assert approved["granted_points"] == 21, (
            f"30 * 7000 / 10000 truncates to 21 points, got {approved['granted_points']}"
        )

        response = api.complete_session(session_id, make_client_integrator_headers(client_id))
        completed = validate_success(response, 200)

        assert completed["identity_state"] == "VERIFIED"
        assert completed["disposition_reason"] == "SCORE_SATISFIED"
        assert completed["assurance_score_provisional"] == 91, (
            "the provisional figure ignores the ceiling, got "
            f"{completed['assurance_score_provisional']}"
        )
        assert completed["assurance_score_final"] == 70, (
            f"the ceiling clamps the final figure to 70, got {completed['assurance_score_final']}"
        )
        assert completed["assurance_ceiling"] == 70
        assert completed["manual_override_flag"] is False

        _, meta = validate_paginated(
            api.list_method_attempts(
                ADMIN_HEADERS, params={"session_id": session_id, "state": "ACCEPTED"}
            )
        )
        assert meta["total_count"] == 3, (
            f"the pathway grant is the third accepted attempt, got {meta['total_count']}"
        )


class TestFrozenRiskScoring:
    """The history term of the risk score and its declared saturation point."""

    def test_prior_reject_history_bump_saturates_at_thirty_points(self, api):
        """PRD §3.2: "Finally a history bump is added: 15 points for each earlier session of
        the same client with the same `external_subject_ref` whose identity axis ended in
        `REJECTED`, with the whole history bump capped at 30 points so that a third and any
        subsequent prior rejection adds nothing further."
        PRD §3.2: "The derived `risk_level` is `HIGH` when the score is 70 or more, `MEDIUM`
        when the score is at least 40 and below 70, and `LOW` otherwise"
        PRD §3.8: "`REJECT` moves the session `MANUAL_REVIEW → REJECTED` and is symmetrical
        in every respect except the reason: `manual_override_flag` becomes true,
        `disposition_reason` becomes `REVIEW_REJECTED`, `completed_at` is stamped,
        `assurance_score_final` is written, and the retention schedule runs."

        Design: Corner/calculations/prior_reject_history_bump_saturates_at_the_declared_cap
        """
        env = setup_client_with_published_policy(
            method_codes=("DOCUMENT_SCAN",),
            policy_overrides={"min_assurance_score": 40},
        )
        client_id = env["client"]["id"]
        profile_id = env["profiles"]["DOCUMENT_SCAN"]["id"]

        earlier_session_ids = []
        for index in range(3):
            session = open_session(
                client_id,
                external_subject_ref="subj-hist",
                requested_assurance_tier="BASIC",
            )
            attempt = open_attempt(session["id"], client_id, profile_id)
            submit_document_capture(attempt["id"], client_id, **FORGED_CAPTURE)
            finalize_attempt(attempt["id"], client_id)

            cases, _ = list_session_cases(session["id"])
            assert len(cases) == 1, f"the forged finalisation must queue one case (round {index})"
            validate_success(
                api.assign_manual_review_case(
                    cases[0]["id"],
                    assign_case_payload(MANUAL_REVIEWER_USER_ID),
                    make_review_manager_headers(),
                ),
                200,
            )
            decide_review_case(cases[0]["id"], "REJECT")
            earlier_session_ids.append(session["id"])

        response = api.create_verification_session(
            create_verification_session_payload(
                client_id,
                external_subject_ref="subj-hist",
                requested_assurance_tier="BASIC",
            ),
            make_client_integrator_headers(client_id),
        )
        fourth = validate_success(response, 201)

        assert fourth["risk_score"] == 40, (
            "10 tier points plus a history bump saturated at 30 is 40, got "
            f"{fourth['risk_score']}"
        )
        assert fourth["risk_level"] == "MEDIUM"

        for session_id in earlier_session_ids:
            earlier = read_session(session_id, client_id)
            assert earlier["identity_state"] == "REJECTED"
            assert earlier["disposition_reason"] == "REVIEW_REJECTED"

        client = read_client(client_id)
        assert client["consumed_review_count"] == 3
        assert client["reserved_review_credits"] == 0
        assert client["available_review_credits"] == 1


class TestPooledCohortRates:
    """Disparity evaluation over three cohorts of unequal size."""

    def _audit_with_unequal_cohorts(self) -> dict:
        profile = read_method_profile(
            setup_client_with_published_policy(method_codes=("DOCUMENT_SCAN",))["profiles"][
                "DOCUMENT_SCAN"
            ]["id"]
        )
        audit = open_bias_audit(
            profile["id"], "2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"
        )
        add_cohort_metric(audit["id"], "AGE_18_24", 100, 5)
        add_cohort_metric(audit["id"], "AGE_25_44", 200, 3)
        add_cohort_metric(audit["id"], "AGE_65_PLUS", 300, 7)
        return {"profile": profile, "audit": audit}

    def test_pooled_false_reject_rate_comes_from_summed_counts(self, api):
        """PRD §3.9: "`pooled_frr_bps` is ten thousand multiplied by the sum of
        `false_reject_count` over included rows, divided by the sum of `attempt_count` over
        included rows, rounded half up — a pooled rate computed from summed counts, never as
        an average of per-cohort rates."
        PRD §3.9: "`disparity_ratio_max_to_pooled_bps` is ten thousand multiplied by
        `max_frr_bps`, divided by `pooled_frr_bps`, rounded half up; it is null when
        `pooled_frr_bps` is 0 or when fewer than two cohorts are included, and it is the
        gating ratio."

        Design: Corner/calculations/pooled_false_reject_rate_comes_from_summed_counts_not_a_mean_of_rates
        """
        fixture = self._audit_with_unequal_cohorts()
        validate_success(
            api.evaluate_bias_audit(fixture["audit"]["id"], make_compliance_officer_headers()),
            200,
        )

        audit = read_bias_audit(fixture["audit"]["id"])
        assert audit["pooled_frr_bps"] == 250, (
            "10000 * 15 / 600 pools to 250 bps rather than the 294 bps mean of rates, got "
            f"{audit['pooled_frr_bps']}"
        )
        assert audit["max_frr_bps"] == 500
        assert audit["min_frr_bps"] == 150
        assert audit["disparity_ratio_max_to_pooled_bps"] == 20000, (
            f"the gating ratio is 10000 * 500 / 250, got "
            f"{audit['disparity_ratio_max_to_pooled_bps']}"
        )
        assert audit["disparity_ratio_max_to_min_bps"] == 33333
        assert audit["included_cohort_count"] == 3
        assert audit["excluded_cohort_count"] == 0
        assert audit["worst_cohort_code"] == "AGE_18_24"

    def test_pooled_gating_ratio_above_the_restriction_threshold_restricts(self, api):
        """PRD §3.9: "When the gating ratio reaches 12500, the audit moves `COLLECTING →
        REMEDIATION_REQUIRED`, all disparity fields are written, and the restriction cascades
        transitively through everything the profile touches. The profile's `bias_state`
        becomes `RESTRICTED` and its `restricted_at` records the clock."
        PRD §3.9: "`worst_cohort_code` is the included cohort with the highest `frr_bps`,
        ties broken by `cohort_code` in ascending alphabetical order; entity identifiers are
        never used as a tie-break key."

        Design: Corner/calculations/pooled_false_reject_rate_comes_from_summed_counts_not_a_mean_of_rates
        """
        fixture = self._audit_with_unequal_cohorts()
        response = api.evaluate_bias_audit(
            fixture["audit"]["id"], make_compliance_officer_headers()
        )
        evaluated = validate_success(response, 200)
        assert evaluated["state"] == "REMEDIATION_REQUIRED"

        profile = read_method_profile(fixture["profile"]["id"])
        assert profile["bias_state"] == "RESTRICTED"
        assert_same_instant(profile["restricted_at"], "2026-08-01T00:00:00Z")
        assert profile["version"] == 2, (
            f"the restriction is one mutation of the profile, got version {profile['version']}"
        )
