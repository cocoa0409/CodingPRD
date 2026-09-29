"""Metrics measured exactly on their declared threshold rather than one step away."""
from test_helpers import (
    RESTRICTING_COHORTS,
    evaluate_audit,
    list_session_age_results,
    list_session_attempts,
    read_method_profile,
    read_session,
    record_estimation_result,
    register_method_profile,
    setup_age_gated_session,
    setup_bias_audit_with_cohorts,
    setup_session,
    validate_error,
)


def _database_profile_evaluated_at_the_restriction_threshold():
    """Three cohorts whose pooled disparity lands exactly on the restriction gate."""
    profile = register_method_profile("DATABASE_CHECK")
    audit = setup_bias_audit_with_cohorts(profile["id"], cohorts=tuple(RESTRICTING_COHORTS))
    return profile, evaluate_audit(audit["id"])


class TestGatingRatioExactlyAtTheRestrictionThreshold:
    def test_the_pooled_ratio_lands_on_the_threshold_while_the_disclosure_ratio_overshoots(self):
        """PRD §3.9: "`pooled_frr_bps` is ten thousand multiplied by the sum of
        `false_reject_count` over included rows, divided by the sum of `attempt_count` over
        included rows, rounded half up — a pooled rate computed from summed counts, never as an
        average of per-cohort rates."

        Design: Difficulty/boundary_precision_check/disparity_gating_ratio_exactly_at_restrict_threshold_restricts
        """
        _, audit = _database_profile_evaluated_at_the_restriction_threshold()

        assert audit["max_frr_bps"] == 500
        assert audit["min_frr_bps"] == 300
        assert audit["pooled_frr_bps"] == 400
        assert audit["disparity_ratio_max_to_pooled_bps"] == 12500
        assert audit["disparity_ratio_max_to_min_bps"] == 16667

    def test_a_ratio_exactly_at_the_threshold_restricts_rather_than_merely_monitoring(self):
        """PRD §3.9: "A gating ratio of 12500 or more restricts. A gating ratio of at least 11000
        but below 12500 monitors." "When the gating ratio reaches 12500, the audit moves
        `COLLECTING → REMEDIATION_REQUIRED`, all disparity fields are written, and the restriction
        cascades transitively through everything the profile touches."

        Design: Difficulty/boundary_precision_check/disparity_gating_ratio_exactly_at_restrict_threshold_restricts
        """
        profile, audit = _database_profile_evaluated_at_the_restriction_threshold()

        assert audit["state"] == "REMEDIATION_REQUIRED"
        assert audit["included_cohort_count"] == 3
        assert audit["worst_cohort_code"] == "AGE_18_24"
        refreshed = read_method_profile(profile["id"])
        assert refreshed["bias_state"] == "RESTRICTED"
        assert refreshed["restricted_at"] is not None


def _age_axis_stepped_across_the_gate_by_one_month():
    """Two estimates either side of the gate, both carrying a twenty-four month buffer."""
    env = setup_age_gated_session(
        required_min_age_years=18,
        age_buffer_multiplier_bps=20000,
        estimation_mae_months=12,
        method_codes=("DOCUMENT_SCAN",),
        policy_overrides={"min_assurance_score": 30, "doc_authenticity_floor_bps": 8000},
        session_overrides={"external_subject_ref": "subj-r6b"},
    )
    client_id = env["client"]["id"]
    estimation_profile_id = env["profiles"]["AGE_ESTIMATION"]["id"]

    record_estimation_result(env["session"]["id"], client_id, estimation_profile_id, 239)
    record_estimation_result(env["session"]["id"], client_id, estimation_profile_id, 240)
    return env


class TestEffectiveAgeExactlyAtTheRequiredMinimum:
    def test_the_buffer_is_subtracted_before_banding_on_both_estimates(self):
        """PRD §3.7: "`buffer_months` is `mae_months_snapshot` multiplied by the pinned policy's
        `age_buffer_multiplier_bps`, divided by ten thousand, rounded *up* to a whole month. The
        `effective_age_months` used for every downstream decision is `estimated_age_months` less
        `buffer_months`, floored at zero."

        Design: Difficulty/boundary_precision_check/effective_age_exactly_at_required_minimum_months_is_assured
        """
        env = _age_axis_stepped_across_the_gate_by_one_month()
        results, meta = list_session_age_results(env["session"]["id"], env["client"]["id"])

        assert meta["total_count"] == 2
        assert results[0]["buffer_months"] == 24
        assert results[0]["effective_age_months"] == 215
        assert results[1]["buffer_months"] == 24
        assert results[1]["effective_age_months"] == 216
        assert results[1]["mae_months_snapshot"] == 12
        assert results[1]["source_vendor_code"] == env["profiles"]["AGE_ESTIMATION"]["vendor_code"]

    def test_an_effective_age_exactly_on_the_gate_is_assured_where_one_month_less_failed(self):
        """PRD §3.7: "The `decision` is `ASSURED` when `effective_age_months` is at or above
        `required_min_age_years` multiplied by twelve, and `FAILED` otherwise; an effective age
        exactly equal to the gate is `ASSURED`."

        Design: Difficulty/boundary_precision_check/effective_age_exactly_at_required_minimum_months_is_assured
        """
        env = _age_axis_stepped_across_the_gate_by_one_month()
        results, _ = list_session_age_results(env["session"]["id"], env["client"]["id"])

        assert results[0]["decision"] == "FAILED"
        assert results[1]["decision"] == "ASSURED"

    def test_the_bands_either_side_of_the_gate_carry_their_documented_accuracies(self):
        """PRD §3.7: "`B16_17` above 191 and at most 215, `B18_20` above 215 and at most 251, and
        `A21_PLUS` above 251."
        "For an estimation result the server then reads `documented_accuracy_bps` out of the
        estimating profile's `band_accuracy_bps` map at exactly that band".

        Design: Difficulty/boundary_precision_check/effective_age_exactly_at_required_minimum_months_is_assured
        """
        env = _age_axis_stepped_across_the_gate_by_one_month()
        results, _ = list_session_age_results(env["session"]["id"], env["client"]["id"])

        assert results[0]["resolved_band"] == "B16_17"
        assert results[0]["documented_accuracy_bps"] == 9100
        assert results[1]["resolved_band"] == "B18_20"
        assert results[1]["documented_accuracy_bps"] == 9400

        session = read_session(env["session"]["id"], env["client"]["id"])
        assert session["age_state"] == "ASSURED"
        assert session["resolved_age_band"] == "B18_20"


def _high_risk_session_whose_policy_admits_only_weak_methods():
    """A high-risk session whose two admitted vendors both lack strong evidence."""
    return setup_session(
        method_codes=("DATABASE_CHECK", "KNOWLEDGE_BASED"),
        client_overrides={"granted_review_credits": 1},
        policy_overrides={
            "min_assurance_score": 60,
            "required_min_age_years": 0,
            "step_up_max_rounds": 2,
        },
        session_overrides={
            "external_subject_ref": "subj-r6c",
            "requested_assurance_tier": "ENHANCED",
            "declared_transaction_value_cents": 150000,
        },
    )


class TestEmptyLadderCandidateSetAtHighRisk:
    def test_the_strong_evidence_filter_empties_the_ladder_for_a_high_risk_session(self, api):
        """PRD §3.3: "A profile is a candidate when all four of the following hold: its
        `method_code` appears in the pinned policy's `allowed_method_codes`; its `bias_state` is not
        `RESTRICTED`; either the session's `risk_level` is not `HIGH` or the profile's
        `strong_evidence` is true; and no attempt of this session already carries that same
        `method_code` in the `ACCEPTED` state." "An empty candidate set is rejected with
        `ERR_NO_ELIGIBLE_METHOD` — which is precisely what a `HIGH`-risk session gets when its
        policy admits only profiles whose `strong_evidence` is false."

        Design: Difficulty/boundary_precision_check/empty_candidate_set_on_high_risk_ladder_selection_is_rejected
        """
        env = _high_risk_session_whose_policy_admits_only_weak_methods()

        assert env["session"]["risk_score"] == 70
        assert env["session"]["risk_level"] == "HIGH"
        validate_error(
            api.create_method_attempt(env["session"]["id"], {}, env["headers"]),
            "ERR_NO_ELIGIBLE_METHOD",
            409,
        )

    def test_the_empty_selection_creates_nothing_and_leaves_the_session_collecting(self, api):
        """PRD §3.3: "When the caller omits `method_profile_id`, the server climbs the method ladder
        on its behalf." A refused selection is not a fallback: "The top-ranked candidate is used and
        `selection_mode` is recorded as `SERVER_SELECTED`." "An empty candidate set is rejected with
        `ERR_NO_ELIGIBLE_METHOD`".

        Design: Difficulty/boundary_precision_check/empty_candidate_set_on_high_risk_ladder_selection_is_rejected
        """
        env = _high_risk_session_whose_policy_admits_only_weak_methods()
        validate_error(
            api.create_method_attempt(env["session"]["id"], {}, env["headers"]),
            "ERR_NO_ELIGIBLE_METHOD",
        )

        _, meta = list_session_attempts(env["session"]["id"])
        assert meta["total_count"] == 0
        assert read_session(env["session"]["id"], env["client"]["id"])["identity_state"] == (
            "IN_PROGRESS"
        )
