"""Cohort disparity measurement and the remediation cycle of a bias audit."""
from test_helpers import (
    DEFAULT_CLOCK,
    OFFICER,
    RESTRICTING_COHORTS,
    SECOND_COMPLIANCE_OFFICER_USER_ID,
    add_cohort_metric,
    evaluate_audit,
    read_method_profile,
    register_method_profile,
    remediate_audit,
    set_clock,
    setup_bias_audit_with_cohorts,
    validate_paginated,
)


def _evaluated_biometric_audit_with_divergent_ratios():
    """Three cohorts whose disclosure ratio restricts but whose gating ratio only monitors."""
    profile = register_method_profile("BIOMETRIC_COMPARISON")
    audit = setup_bias_audit_with_cohorts(
        profile["id"],
        cohorts=(("AGE_18_24", 500, 25), ("AGE_25_44", 1000, 40), ("AGE_65_PLUS", 200, 10)),
    )
    return profile, evaluate_audit(audit["id"])


class TestDisclosureAndGatingDisparityVariants:
    def test_the_two_disparity_ratios_diverge_over_the_identical_cohort_rows(self):
        """PRD §3.9: "`disparity_ratio_max_to_min_bps` is ten thousand multiplied by
        `max_frr_bps`, divided by `min_frr_bps`, rounded half up" and
        "`disparity_ratio_max_to_pooled_bps` is ten thousand multiplied by `max_frr_bps`,
        divided by `pooled_frr_bps`, rounded half up".

        Design: Difficulty/dual_variant_calc/disparity_disclosure_variant_diverges_from_gating_variant_on_same_cohorts
        """
        _, audit = _evaluated_biometric_audit_with_divergent_ratios()

        assert audit["max_frr_bps"] == 500
        assert audit["min_frr_bps"] == 400
        assert audit["pooled_frr_bps"] == 441
        assert audit["disparity_ratio_max_to_min_bps"] == 12500
        assert audit["disparity_ratio_max_to_pooled_bps"] == 11338

    def test_only_the_pooled_ratio_gates_so_the_profile_is_merely_monitored(self):
        """PRD §3.9: "A gating ratio of 12500 or more restricts. A gating ratio of at least
        11000 but below 12500 monitors. A gating ratio below 11000 clears." The disclosure ratio
        "exists purely for disclosure and never drives a state change".

        Design: Difficulty/dual_variant_calc/disparity_disclosure_variant_diverges_from_gating_variant_on_same_cohorts
        """
        profile, audit = _evaluated_biometric_audit_with_divergent_ratios()

        assert audit["state"] == "EVALUATED"
        refreshed = read_method_profile(profile["id"])
        assert refreshed["bias_state"] == "MONITORED"
        assert refreshed["restricted_at"] is None

    def test_cohort_coverage_counters_and_the_worst_cohort_tie_break_are_recorded(self):
        """PRD §3.9: "`included_cohort_count` is the size of that set and
        `excluded_cohort_count` is the number of in-scope rows less that size."
        "`worst_cohort_code` is the included cohort with the highest `frr_bps`, ties broken by
        `cohort_code` in ascending alphabetical order; entity identifiers are never used as a
        tie-break key."

        Design: Difficulty/dual_variant_calc/disparity_disclosure_variant_diverges_from_gating_variant_on_same_cohorts
        """
        _, audit = _evaluated_biometric_audit_with_divergent_ratios()

        assert audit["included_cohort_count"] == 3
        assert audit["excluded_cohort_count"] == 0
        assert audit["insufficient_sample"] is False
        assert audit["worst_cohort_code"] == "AGE_18_24"


def _audit_cycled_back_to_collecting_after_remediation():
    """A restricted profile lifted to monitored, with a fresh round of cohort rows on file."""
    set_clock(DEFAULT_CLOCK)
    profile = register_method_profile("DOCUMENT_SCAN")
    audit = setup_bias_audit_with_cohorts(profile["id"], cohorts=tuple(RESTRICTING_COHORTS))
    evaluate_audit(audit["id"])

    # PRD §3.9 scopes the next evaluation to the rows whose `created_at` is at or
    # after `remediated_at`, so the clock must leave the first round's rows behind
    # before the remediation stamps that instant — otherwise round one's rows share
    # the instant and stay in scope.
    set_clock("2026-08-02T00:00:00Z")

    remediated = remediate_audit(
        audit["id"],
        read_method_profile(profile["id"])["version"],
        SECOND_COMPLIANCE_OFFICER_USER_ID,
        remediation_note="recalibrated document matcher on cohort-balanced training data",
    )

    for cohort_code, attempt_count, false_reject_count in (
        ("SKIN_TONE_I_III", 1000, 40),
        ("SKIN_TONE_IV_VI", 1000, 42),
        ("AGE_45_64", 1000, 38),
    ):
        add_cohort_metric(audit["id"], cohort_code, attempt_count, false_reject_count)
    return profile, remediated


class TestBiasAuditCyclesThroughRemediation:
    def test_remediation_returns_the_audit_to_collecting_and_lifts_the_restriction(self):
        """PRD §3.9: "On success the audit moves `REMEDIATION_REQUIRED → COLLECTING`, its
        `remediation_round` rises by one, `remediated_at` records the clock — thereby scoping the
        next evaluation to cohort rows created from that instant onward — and
        `remediated_by_user_id` records the acting user. The profile moves
        `RESTRICTED → MONITORED` with `restricted_at` set back to null, and its `version` increments
        by one."

        Design: Difficulty/non_linear_state_machine/bias_audit_cycles_through_remediation_back_to_collecting_and_clears
        """
        profile, remediated = _audit_cycled_back_to_collecting_after_remediation()

        assert remediated["state"] == "COLLECTING"
        assert remediated["remediation_round"] == 1
        assert remediated["remediated_at"] is not None
        assert remediated["remediated_by_user_id"] == SECOND_COMPLIANCE_OFFICER_USER_ID
        assert remediated["evaluated_by_user_id"] == "co-1"

        refreshed = read_method_profile(profile["id"])
        assert refreshed["bias_state"] == "MONITORED"
        assert refreshed["restricted_at"] is None

    def test_second_evaluation_scores_only_the_post_remediation_cohort_rows(self):
        """PRD §3.9: "The rows in scope are those cohort rows of the audit whose `created_at` is
        at or after the audit's `remediated_at`, or all of the audit's rows when `remediated_at`
        is null — this is how each remediation round starts from a clean measurement."

        Design: Difficulty/non_linear_state_machine/bias_audit_cycles_through_remediation_back_to_collecting_and_clears
        """
        _, remediated = _audit_cycled_back_to_collecting_after_remediation()
        audit = evaluate_audit(remediated["id"])

        assert audit["max_frr_bps"] == 420
        assert audit["min_frr_bps"] == 380
        assert audit["pooled_frr_bps"] == 400
        assert audit["disparity_ratio_max_to_min_bps"] == 11053
        assert audit["disparity_ratio_max_to_pooled_bps"] == 10500
        assert audit["included_cohort_count"] == 3
        assert audit["excluded_cohort_count"] == 0
        assert audit["worst_cohort_code"] == "SKIN_TONE_IV_VI"

    def test_a_cleared_second_round_closes_the_audit_and_clears_the_profile(self):
        """PRD §3.9: "when the audit's `remediation_round` is already at least 1 and the gating
        ratio is below 11000, the remediation programme has demonstrably worked, and the audit
        moves `COLLECTING → REMEDIATED` instead — a terminal state — with the profile's
        `bias_state` set to `CLEARED` and its `restricted_at` set back to null."

        Design: Difficulty/non_linear_state_machine/bias_audit_cycles_through_remediation_back_to_collecting_and_clears
        """
        profile, remediated = _audit_cycled_back_to_collecting_after_remediation()
        audit = evaluate_audit(remediated["id"])

        assert audit["state"] == "REMEDIATED"
        assert audit["remediation_round"] == 1
        refreshed = read_method_profile(profile["id"])
        assert refreshed["bias_state"] == "CLEARED"
        assert refreshed["restricted_at"] is None

    def test_every_cohort_row_of_both_rounds_stays_on_the_audit(self, api):
        """PRD §3.9: "Observations arrive as **CohortMetric** rows filed under the audit's
        `bias_audit_id`. Each row names a `cohort_code` ... which must be unique within the
        audit, a repeat being rejected with `ERR_COHORT_DUPLICATE`."

        Design: Difficulty/non_linear_state_machine/bias_audit_cycles_through_remediation_back_to_collecting_and_clears
        """
        _, remediated = _audit_cycled_back_to_collecting_after_remediation()
        evaluate_audit(remediated["id"])

        rows, meta = validate_paginated(
            api.list_cohort_metrics(remediated["id"], OFFICER, params={"limit": 100})
        )
        assert meta["total_count"] == 6
        assert len(rows) == 6
