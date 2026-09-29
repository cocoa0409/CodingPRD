"""Two-variant scoring, multi-clamp arithmetic and the non-linear state machines.

Every test here drives one governance position from an empty database through the
PRD's own endpoints and then reads back the numbers and states the PRD mandates.
"""

import pytest

from test_helpers import (
    HIGH_USE_CASE,
    THIRD_PARTY_ASSET_CARTWRIGHT,
    ApiErrorId,
    BUSINESS_REVIEWER,
    OFFICER,
    PRIVACY_REVIEWER,
    PRIVACY_REVIEWER_2,
    REQUESTER,
    USER_PRIVACY_2,
    approval_payload,
    assert_classification_snapshot,
    assert_debt_equals,
    assert_gate_order,
    assert_ledger_entry,
    assert_oversight_design,
    assert_review_gate,
    assert_vendor_assessment,
    assessment_decision_payload,
    classified_use_case,
    classify_payload,
    conditions,
    current_version,
    design_decision_payload,
    expected_adequacy_score,
    expected_base_score,
    expected_control_credit,
    expected_debt_total,
    expected_final_score,
    expected_gate_debt,
    expected_terms_risk_points,
    expected_vendor_penalty,
    file_use_case,
    gates_by_type,
    get_success_data,
    grade_for_points,
    high_tier_use_case_ready_for_approval,
    high_tier_with_conditions_on_every_gate,
    is_iso8601_timestamp,
    issue_conditions_payload,
    list_ledger,
    list_snapshots,
    oversight_design_payload,
    pin_clock,
    read_asset,
    read_summary,
    read_use_case,
    register_asset,
    submit_assessment,
    take_up_and_clear,
    take_up_gate,
    use_case_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vendor_assessment_payload,
)
from test_helpers.api_client import ApiClient

# ─── Declarations the tests below file ─────────────────────────────────────

# Fully licensed provenance, full output-rights assignment, a documented 20-day
# retention term, no contractual retention opt-out and disclosed subprocessors.
LICENSED_TERMS_WITHOUT_OPT_OUT = vendor_assessment_payload(
    vendor_name="Cartwright Labs",
    training_data_provenance="DOCUMENTED_LICENSED",
    output_rights="FULL_ASSIGNMENT",
    retention_days=20,
    retention_opt_out=False,
    subprocessors_disclosed=True,
)

# 25 impact + 18 autonomy + 6 sensitivity + 2 reach + 0 jurisdiction = 51.
ROSTER_INTAKE = use_case_payload(
    title="Shift roster optimiser",
    business_unit="Operations",
    description="proposes weekly shift rosters with supervisor sign-off",
    affects_individuals=True,
    decision_autonomy="HUMAN_ON_LOOP",
    data_sensitivity="INTERNAL",
    individual_impact="MATERIAL",
    jurisdictions=[],
    deployed_headcount_reach=5000,
)

# 25 impact + 8 autonomy + 6 sensitivity + 2 reach + 3 jurisdiction = 44.
ORDINARY_INTAKE = use_case_payload(
    title="Supplier invoice triage",
    business_unit="Finance",
    description="routes invoices to the right approver",
    affects_individuals=True,
    decision_autonomy="HUMAN_IN_LOOP",
    data_sensitivity="INTERNAL",
    individual_impact="MATERIAL",
    jurisdictions=["EU"],
    deployed_headcount_reach=5000,
)

# 40 impact + 30 autonomy + 24 sensitivity + 0 reach + 3 jurisdiction = 97, and
# all four legs of the prohibited conjunction hold at once.
PROHIBITED_CONJUNCTION_INTAKE = use_case_payload(
    title="Autonomous medical benefit denial",
    business_unit="Claims",
    description="issues final benefit denials without a reviewer",
    affects_individuals=True,
    decision_autonomy="FULLY_AUTOMATED",
    data_sensitivity="SPECIAL_CATEGORY",
    individual_impact="CONSEQUENTIAL",
    jurisdictions=["EU"],
    deployed_headcount_reach=500,
)

# 25 impact + 18 autonomy + 14 sensitivity + 2 reach + 0 jurisdiction = 59. An
# empty jurisdictions array leaves the PRIVACY notice precondition vacuous.
LOOP_INTAKE = use_case_payload(
    title="Internal knowledge assistant",
    business_unit="Shared Services",
    description="answers staff policy questions from internal documents",
    affects_individuals=True,
    decision_autonomy="HUMAN_ON_LOOP",
    data_sensitivity="CONFIDENTIAL",
    individual_impact="MATERIAL",
    jurisdictions=[],
    deployed_headcount_reach=5000,
)


def _at_second(instant: str) -> str:
    """The instant truncated to the second, which is the precision comparisons use."""
    assert is_iso8601_timestamp(instant), f"not an ISO 8601 timestamp: {instant!r}"
    return instant[:19]


def _sign_approval(api: ApiClient, use_case_id: str) -> dict:
    """Sign the deployment approval as the officer, pinning the current version."""
    return validate_success(
        api.approve_use_case(
            use_case_id,
            approval_payload(current_version(api, use_case_id)),
            headers=OFFICER,
        )
    )


def _file_sampled_design(
    api: ApiClient, use_case_id: str, sample_pct: int, escalation_sla_hours: int
) -> dict:
    """File a SAMPLED oversight design with an override capability."""
    return validate_success(
        api.create_oversight_design(
            use_case_id,
            oversight_design_payload(
                current_version(api, use_case_id),
                review_mode="SAMPLED",
                sample_pct=sample_pct,
                escalation_sla_hours=escalation_sla_hours,
                reviewer_role="BusinessReviewer",
                override_capability=True,
            ),
            headers=REQUESTER,
        ),
        expected_status=201,
    )


def _loop_use_case(api: ApiClient) -> tuple:
    """Classify the loop intake, returning the use case and its two gates."""
    pin_clock(api)
    use_case = classified_use_case(api, LOOP_INTAKE)
    return use_case, gates_by_type(api, use_case["id"])


def _first_condition_pass(api: ApiClient, gate_id: str) -> dict:
    """Walk PENDING → IN_REVIEW → CONDITIONS_ISSUED with two conditions."""
    take_up_gate(api, gate_id, "PRIVACY")
    return get_success_data(
        api.issue_gate_conditions(
            gate_id, issue_conditions_payload(conditions(2)), headers=PRIVACY_REVIEWER
        )
    )


def _second_take_up(api: ApiClient, gate_id: str) -> dict:
    """Re-enter IN_REVIEW out of CONDITIONS_ISSUED, under a different reviewer."""
    return get_success_data(api.start_gate_review(gate_id, headers=PRIVACY_REVIEWER_2))


def _second_condition_pass(api: ApiClient, gate_id: str) -> dict:
    """Walk IN_REVIEW → CONDITIONS_ISSUED a second time, with one condition."""
    return get_success_data(
        api.issue_gate_conditions(
            gate_id, issue_conditions_payload(conditions(1)), headers=PRIVACY_REVIEWER_2
        )
    )


def _clear_out_of_conditions(api: ApiClient, gate_id: str) -> dict:
    """Clear the PRIVACY gate straight out of CONDITIONS_ISSUED."""
    return get_success_data(
        api.clear_gate(
            gate_id,
            {"decision_note": "schedule published, cleared straight out of conditions"},
            headers=PRIVACY_REVIEWER_2,
        )
    )


def _loop_with_cleared_privacy(api: ApiClient) -> tuple:
    """Drive the condition loop twice and then clear the PRIVACY gate."""
    use_case, gates = _loop_use_case(api)
    privacy_id = gates["PRIVACY"]["id"]
    _first_condition_pass(api, privacy_id)
    _second_take_up(api, privacy_id)
    _second_condition_pass(api, privacy_id)
    _clear_out_of_conditions(api, privacy_id)
    return use_case, gates


def _loop_ready_for_approval(api: ApiClient) -> tuple:
    """Clear both gates, so the use case reaches READY_FOR_APPROVAL."""
    use_case, gates = _loop_with_cleared_privacy(api)
    take_up_and_clear(api, gates["BUSINESS"]["id"], "BUSINESS")
    return use_case, gates


class TestProvisionalVersusDeploymentFinalVariant:
    """One use case carries a provisional score and a deployment-final score."""

    def test_provisional_snapshot_and_provisional_pair_survive_the_approval(self, api):
        """PRD §3.2: "Individual impact contributes nothing for `NONE`, 10 points for `LOW`, 25 points for `MATERIAL` and 40 points for `CONSEQUENTIAL`; these land on the snapshot as `impact_points`. Decision autonomy contributes nothing for `ADVISORY`, 8 points for `HUMAN_IN_LOOP`, 18 points for `HUMAN_ON_LOOP` and 30 points for `FULLY_AUTOMATED`, recorded as `autonomy_points`. Data sensitivity contributes nothing for `PUBLIC`, 6 points for `INTERNAL`, 14 points for `CONFIDENTIAL` and 24 points for `SPECIAL_CATEGORY`, recorded as `sensitivity_points`. Reach contributes by band, taking the first band that matches `deployed_headcount_reach`: 6 points at one hundred thousand individuals a year or more, otherwise 4 points at ten thousand or more, otherwise 2 points at one thousand or more, otherwise nothing; this is `reach_points`. Finally, `jurisdiction_points` is 3 points for each declared jurisdiction that is one of the three high-scrutiny jurisdictions `EU`, `UK` and `US_CO` — a use case declaring all three of those plus `US_FED` therefore earns 9 points, not 12. The five contributions add up to `base_score`."

        PRD §3.2: "At classification time both adjustments are nil by definition — the provisional pass scores the *declaration*, not the controls, so `vendor_penalty` is 0 and `control_credit` is 0, and the snapshot records `cleared_gate_count` and `passed_eval_count` as 0 even in the unusual case where such rows already exist. Banding then follows: a `risk_score` of 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, and anything below 35 is `MINIMAL`."

        PRD §3.7: "`control_credit`, `vendor_penalty`, `final_risk_score` and `final_risk_tier` are written onto the use case, `approved_by_user_id` records the signing `X-User-ID`, `monitoring_posture` is set to `HEALTHY`, and a `GovernanceLedgerEntry` of type `APPROVAL_GRANTED` is appended with a `reach_delta` of plus the use case's `deployed_headcount_reach` and a `debt_delta` of 0.00."

        Design: Difficulty/dual_variant_calc/use_case_risk_provisional_versus_deployment_final
        """
        chain = high_tier_use_case_ready_for_approval(api)
        assert expected_base_score(HIGH_USE_CASE) == 74

        approved = _sign_approval(api, chain.use_case_id)

        assert approved["risk_score"] == 74
        assert approved["risk_tier"] == "HIGH"

        provisional = list_snapshots(
            api, chain.use_case_id, variant="INTAKE_PROVISIONAL"
        )
        assert len(provisional) == 1
        assert_classification_snapshot(
            provisional[0],
            variant="INTAKE_PROVISIONAL",
            cycle_index=1,
            impact_points=40,
            autonomy_points=18,
            sensitivity_points=6,
            reach_points=4,
            jurisdiction_points=6,
            base_score=74,
            vendor_penalty=0,
            control_credit=0,
            cleared_gate_count=0,
            passed_eval_count=0,
            risk_score=74,
            risk_tier="HIGH",
        )

    def test_final_variant_credits_the_controls_and_penalises_the_vendor_grade(
        self, api
    ):
        """PRD §3.7: "Count the use case's gates whose status is `CLEARED` into `cleared_gate_count`, and count the use case's evaluations whose status is `PASSED` into `passed_eval_count`."

        PRD §3.7: "`control_credit` is 3 points for each cleared gate plus 2 points for each passed evaluation, capped at 15 — so a `HIGH`-tier use case with all four gates cleared and three evaluations passed earns 12 plus 6, which the cap trims to 15."

        PRD §3.7: "Otherwise it is drawn from the asset's `vendor_terms_grade`: nothing for grade `A`, 5 for grade `B`, 12 for grade `C` and 25 for grade `D`."

        PRD §3.7: "The five declared point contributions are computed exactly as they were at classification, summed into `base_score`, then the `vendor_penalty` from step 3 is added and the `control_credit` from step 2 is subtracted; the result is rounded half up to a whole number and clamped into 0 through 100 to give `final_risk_score`. `final_risk_tier` is banded from that score by the same bands as before — 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, below 35 is `MINIMAL` — and the same prohibited-combination override still takes precedence over the bands."

        PRD §3.7: "On success the use case moves `READY_FOR_APPROVAL → APPROVED`."

        Design: Difficulty/dual_variant_calc/use_case_risk_provisional_versus_deployment_final
        """
        chain = high_tier_use_case_ready_for_approval(api)

        approved = _sign_approval(api, chain.use_case_id)

        assert approved["status"] == "APPROVED"
        assert approved["vendor_penalty"] == 5
        assert approved["control_credit"] == 15
        assert approved["final_risk_score"] == 64
        assert approved["final_risk_tier"] == "LIMITED"
        assert expected_vendor_penalty(True, "B") == 5
        assert expected_control_credit(4, 4) == 15
        assert expected_final_score(74, 5, 15) == 64

    def test_both_variant_snapshots_stand_side_by_side_under_one_cycle_index(self, api):
        """PRD §3.2: "The `variant` is `INTAKE_PROVISIONAL` for a classification run and `DEPLOYMENT_FINAL` for the one the approval writes. Snapshots for a use case can be listed, optionally filtered by `variant`, and the currently effective provisional snapshot is the `INTAKE_PROVISIONAL` row with the highest `cycle_index`."

        PRD §3.7: "A `ClassificationSnapshot` with `variant` `DEPLOYMENT_FINAL` is appended under the current `classification_cycle_index`, recording the frozen `cleared_gate_count` and `passed_eval_count`, the `control_credit` and `vendor_penalty` applied, and the resulting score and tier."

        Design: Difficulty/dual_variant_calc/use_case_risk_provisional_versus_deployment_final
        """
        chain = high_tier_use_case_ready_for_approval(api)

        _sign_approval(api, chain.use_case_id)

        records, meta = validate_paginated(
            api.list_classification_snapshots(chain.use_case_id, headers=OFFICER)
        )
        assert meta["total_count"] == 2
        assert len(records) == 2
        by_variant = {row["variant"]: row for row in records}
        assert sorted(by_variant) == ["DEPLOYMENT_FINAL", "INTAKE_PROVISIONAL"]

        assert_classification_snapshot(
            by_variant["INTAKE_PROVISIONAL"],
            cycle_index=1,
            base_score=74,
            risk_score=74,
            risk_tier="HIGH",
        )
        assert_classification_snapshot(
            by_variant["DEPLOYMENT_FINAL"],
            cycle_index=1,
            base_score=74,
            vendor_penalty=5,
            control_credit=15,
            cleared_gate_count=4,
            passed_eval_count=4,
            risk_score=64,
            risk_tier="LIMITED",
        )

    def test_the_final_tier_not_the_provisional_one_sets_the_reassessment_clock(
        self, api
    ):
        """PRD §3.7: "`reassessment_interval_days` is 730 days (two years) for a `MINIMAL` final tier, 365 days (one year) for a `LIMITED` final tier, and 180 days (half a year) for a `HIGH` final tier."

        PRD §3.7: "`approved_at` is the current logical instant, `approval_expires_at` is that instant plus `reassessment_interval_days` days, `reassessment_due_at` is set to the very same instant as `approval_expires_at`, `reassessment_cycle_index` becomes 1 and `reassessment_status` becomes `SCHEDULED`."

        Design: Difficulty/dual_variant_calc/use_case_risk_provisional_versus_deployment_final
        """
        chain = high_tier_use_case_ready_for_approval(api)

        approved = _sign_approval(api, chain.use_case_id)

        assert approved["final_risk_tier"] == "LIMITED"
        assert approved["reassessment_interval_days"] == 365
        assert _at_second(approved["approved_at"]) == "2026-08-01T00:00:00"
        assert _at_second(approved["approval_expires_at"]) == "2027-08-01T00:00:00"
        assert _at_second(approved["reassessment_due_at"]) == _at_second(
            approved["approval_expires_at"]
        )
        assert approved["reassessment_cycle_index"] == 1
        assert approved["reassessment_status"] == "SCHEDULED"

    def test_the_gate_demand_stays_fixed_to_the_provisional_tier(self, api):
        """PRD §3.2: "`required_gate_types` is set from the provisional tier in the canonical order `LEGAL`, `PRIVACY`, `SECURITY`, `BUSINESS`: a `MINIMAL` tier demands only the `BUSINESS` gate, a `LIMITED` tier demands `PRIVACY` and `BUSINESS`, a `HIGH` tier demands all four, and a `PROHIBITED` tier demands none."

        PRD §3.7: "`control_credit`, `vendor_penalty`, `final_risk_score` and `final_risk_tier` are written onto the use case, `approved_by_user_id` records the signing `X-User-ID`, `monitoring_posture` is set to `HEALTHY`, and a `GovernanceLedgerEntry` of type `APPROVAL_GRANTED` is appended with a `reach_delta` of plus the use case's `deployed_headcount_reach` and a `debt_delta` of 0.00."

        Design: Difficulty/dual_variant_calc/use_case_risk_provisional_versus_deployment_final
        """
        chain = high_tier_use_case_ready_for_approval(api)

        approved = _sign_approval(api, chain.use_case_id)

        assert approved["final_risk_tier"] == "LIMITED"
        assert approved["required_gate_types"] == [
            "LEGAL",
            "PRIVACY",
            "SECURITY",
            "BUSINESS",
        ]
        assert approved["cleared_gate_count"] == 4


class TestVendorTermsConservativeVersusDocumented:
    """The same stored assessment row grades two bands apart across the variants."""

    def test_submission_grades_the_row_under_the_conservative_variant(self, api):
        """PRD §3.1: "A new assessment lands in status `SUBMITTED` with `terms_variant` set to `CONSERVATIVE_LEGAL`, and it is graded immediately under that variant."

        PRD §3.1: "Under `CONSERVATIVE_LEGAL`, `effective_retention_days` is taken as a worst-case assumption of 3650 days whenever `retention_days` is null **or** whenever `retention_opt_out` is false, and only otherwise is the declared `retention_days` used; the `UNDISCLOSED` provenance surcharge of 10 points also applies."

        PRD §3.1: "Provenance contributes nothing when it is `DOCUMENTED_LICENSED`, 8 points when it is `DOCUMENTED_MIXED`, and 20 points when it is `UNDISCLOSED`; under the conservative variant an `UNDISCLOSED` provenance carries a further surcharge of 10 points on top of that 20. Output rights contribute nothing for `FULL_ASSIGNMENT`, 6 points for `LICENSE_WITH_RESTRICTIONS` and 16 points for `VENDOR_RETAINS`. Retention contributes according to the `effective_retention_days` the variant scored: nothing when that figure is at most 30 days, 5 points when it is above 30 and at most 90, 10 points when it is above 90 and at most 365, and 18 points when it exceeds 365. A further 6 points are added when `retention_opt_out` is false, and nothing when it is true. A final 5 points are added when `subprocessors_disclosed` is false, and nothing when it is true. The total is banded into a grade: at most 8 points is `A`, above 8 and at most 20 is `B`, above 20 and at most 34 is `C`, and anything above 34 is `D`."

        Design: Difficulty/dual_variant_calc/vendor_terms_conservative_versus_documented_variant
        """
        pin_clock(api)
        asset = register_asset(api, THIRD_PARTY_ASSET_CARTWRIGHT)

        submitted = validate_success(
            api.create_vendor_assessment(
                asset["id"], LICENSED_TERMS_WITHOUT_OPT_OUT, headers=OFFICER
            ),
            expected_status=201,
        )

        assert_vendor_assessment(
            submitted,
            status="SUBMITTED",
            terms_variant="CONSERVATIVE_LEGAL",
            effective_retention_days=3650,
            terms_risk_points=24,
            terms_grade="C",
        )
        assert (
            expected_terms_risk_points(
                LICENSED_TERMS_WITHOUT_OPT_OUT, "CONSERVATIVE_LEGAL"
            )
            == 24
        )
        assert grade_for_points(24) == "C"

    def test_the_documented_variant_regrades_the_same_row_from_c_to_a(self, api):
        """PRD §3.1: "Under `DOCUMENTED_TERMS`, `effective_retention_days` is the declared `retention_days` verbatim and no provenance surcharge is added at all."

        PRD §3.1: "Retention contributes according to the `effective_retention_days` the variant scored: nothing when that figure is at most 30 days, 5 points when it is above 30 and at most 90, 10 points when it is above 90 and at most 365, and 18 points when it exceeds 365. A further 6 points are added when `retention_opt_out` is false, and nothing when it is true. A final 5 points are added when `subprocessors_disclosed` is false, and nothing when it is true. The total is banded into a grade: at most 8 points is `A`, above 8 and at most 20 is `B`, above 20 and at most 34 is `C`, and anything above 34 is `D`."

        PRD §3.1: "Whichever way the decision falls, the grading is re-run under the requested variant and `effective_retention_days`, `terms_risk_points` and `terms_grade` are all overwritten, and `decided_by_user_id` and `decided_at` are recorded."

        Design: Difficulty/dual_variant_calc/vendor_terms_conservative_versus_documented_variant
        """
        pin_clock(api)
        asset = register_asset(api, THIRD_PARTY_ASSET_CARTWRIGHT)
        submitted = submit_assessment(
            api, asset["id"], LICENSED_TERMS_WITHOUT_OPT_OUT
        )

        decided = validate_success(
            api.decide_vendor_assessment(
                submitted["id"],
                assessment_decision_payload("ACCEPT", "DOCUMENTED_TERMS"),
                headers=OFFICER,
            )
        )

        assert decided["id"] == submitted["id"]
        assert_vendor_assessment(
            decided,
            status="ACCEPTED",
            terms_variant="DOCUMENTED_TERMS",
            effective_retention_days=20,
            terms_risk_points=6,
            terms_grade="A",
            retention_days=20,
            retention_opt_out=False,
            subprocessors_disclosed=True,
            training_data_provenance="DOCUMENTED_LICENSED",
            output_rights="FULL_ASSIGNMENT",
        )
        assert (
            expected_terms_risk_points(
                LICENSED_TERMS_WITHOUT_OPT_OUT, "DOCUMENTED_TERMS"
            )
            == 6
        )
        assert grade_for_points(6) == "A"

    def test_acceptance_copies_the_documented_grade_onto_the_asset(self, api):
        """PRD §3.1: "The two branches then diverge in one specific way: accepting moves the assessment `SUBMITTED → ACCEPTED` **and** copies its `terms_grade` onto the parent asset's `vendor_terms_grade`, whereas rejecting moves it `SUBMITTED → REJECTED` and leaves the asset's `vendor_terms_grade` untouched."

        PRD §2.10: "`vendor_terms_grade` on a `ModelAsset` is the `terms_grade` of the most recently `ACCEPTED` assessment on that asset, and null when no assessment has been accepted or when acceptance has since been expired."

        Design: Difficulty/dual_variant_calc/vendor_terms_conservative_versus_documented_variant
        """
        pin_clock(api)
        asset = register_asset(api, THIRD_PARTY_ASSET_CARTWRIGHT)
        assert asset["vendor_terms_grade"] is None
        submitted = submit_assessment(
            api, asset["id"], LICENSED_TERMS_WITHOUT_OPT_OUT
        )

        validate_success(
            api.decide_vendor_assessment(
                submitted["id"],
                assessment_decision_payload("ACCEPT", "DOCUMENTED_TERMS"),
                headers=OFFICER,
            )
        )

        assert read_asset(api, asset["id"])["vendor_terms_grade"] == "A"

    def test_the_two_variant_results_cannot_both_be_persisted_on_the_row(self, api):
        """PRD §3.1: "An assessment that is not `SUBMITTED` cannot be decided again and the attempt is rejected with `ERR_ASSESSMENT_ALREADY_DECIDED`."

        Design: Difficulty/dual_variant_calc/vendor_terms_conservative_versus_documented_variant
        """
        pin_clock(api)
        asset = register_asset(api, THIRD_PARTY_ASSET_CARTWRIGHT)
        submitted = submit_assessment(
            api, asset["id"], LICENSED_TERMS_WITHOUT_OPT_OUT
        )
        get_success_data(
            api.decide_vendor_assessment(
                submitted["id"],
                assessment_decision_payload("ACCEPT", "DOCUMENTED_TERMS"),
                headers=OFFICER,
            )
        )

        response = api.decide_vendor_assessment(
            submitted["id"],
            assessment_decision_payload("ACCEPT", "CONSERVATIVE_LEGAL"),
            headers=OFFICER,
        )

        validate_error(response, ApiErrorId.ASSESSMENT_ALREADY_DECIDED)


class TestOversightAdequacyClampsAndCaps:
    """Three clamps and two floors sit inside the one adequacy expression."""

    def test_the_limited_tier_and_autonomy_pair_select_the_seventy_point_bar(self, api):
        """PRD §3.2: "Individual impact contributes nothing for `NONE`, 10 points for `LOW`, 25 points for `MATERIAL` and 40 points for `CONSEQUENTIAL`; these land on the snapshot as `impact_points`. Decision autonomy contributes nothing for `ADVISORY`, 8 points for `HUMAN_IN_LOOP`, 18 points for `HUMAN_ON_LOOP` and 30 points for `FULLY_AUTOMATED`, recorded as `autonomy_points`. Data sensitivity contributes nothing for `PUBLIC`, 6 points for `INTERNAL`, 14 points for `CONFIDENTIAL` and 24 points for `SPECIAL_CATEGORY`, recorded as `sensitivity_points`. Reach contributes by band, taking the first band that matches `deployed_headcount_reach`: 6 points at one hundred thousand individuals a year or more, otherwise 4 points at ten thousand or more, otherwise 2 points at one thousand or more, otherwise nothing; this is `reach_points`. Finally, `jurisdiction_points` is 3 points for each declared jurisdiction that is one of the three high-scrutiny jurisdictions `EU`, `UK` and `US_CO` — a use case declaring all three of those plus `US_FED` therefore earns 9 points, not 12. The five contributions add up to `base_score`."

        PRD §3.2: "Banding then follows: a `risk_score` of 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, and anything below 35 is `MINIMAL`."

        PRD §3.5: "The bar the score must clear, `required_adequacy_score`, is selected two-dimensionally from the use case's provisional `risk_tier` and its `decision_autonomy`, and only the two fields participate. At a `HIGH` tier the requirement is 60 for `ADVISORY`, 75 for `HUMAN_IN_LOOP`, 85 for `HUMAN_ON_LOOP` and 95 for `FULLY_AUTOMATED`. At a `LIMITED` tier it is 45, 60, 70 and 80 for those same four autonomy levels."

        Design: Difficulty/combinatorial_formula/oversight_adequacy_nested_cap_and_zero_clamp_mode_a
        """
        pin_clock(api)
        classified = classified_use_case(api, ROSTER_INTAKE)
        assert classified["risk_score"] == 51
        assert classified["risk_tier"] == "LIMITED"
        assert expected_base_score(ROSTER_INTAKE) == 51

        design = _file_sampled_design(api, classified["id"], 100, 126)

        assert_oversight_design(
            design,
            status="DRAFT",
            review_mode="SAMPLED",
            sample_pct=100,
            escalation_sla_hours=126,
            required_adequacy_score=70,
        )

    def test_both_inner_clamps_bind_and_the_score_lands_exactly_on_seventy(self, api):
        """PRD §3.5: "Four components add together. The mode base contributes nothing for `NONE`, 30 points for `SAMPLED`, 70 points for `PRE_DECISION_REVIEW` and 90 points for `DUAL_REVIEW`. The sample component applies only when `review_mode` is `SAMPLED`, and is `sample_pct` multiplied by three tenths, taken down to the next whole number, then capped at 30 — so sampling every decision earns the full 30 while sampling half of them earns 15; for every other review mode the sample component is 0 regardless of what `sample_pct` says. The SLA component starts from 20 points and subtracts one point for every whole 6 hours of `escalation_sla_hours`, with the result floored at 0 so it can never go negative — an SLA of 6 hours costs 1 point, an SLA of 240 hours costs the full 20 and leaves nothing. The override component is 10 points when `override_capability` is true and nothing when it is false. `adequacy_score` is the sum of the four, capped at 100. Both flooring operations happen inside their own components, before the outer capping and flooring are applied — never afterwards."

        Design: Difficulty/combinatorial_formula/oversight_adequacy_nested_cap_and_zero_clamp_mode_a
        """
        pin_clock(api)
        classified = classified_use_case(api, ROSTER_INTAKE)

        design = _file_sampled_design(api, classified["id"], 100, 126)

        # 30 mode base + min(30, floor(100 * 0.3)) + max(0, 20 - floor(126 / 6)) + 10.
        assert design["adequacy_score"] == 70
        assert design["adequacy_score"] != 69
        assert (
            expected_adequacy_score(
                {
                    "review_mode": "SAMPLED",
                    "sample_pct": 100,
                    "escalation_sla_hours": 126,
                    "override_capability": True,
                }
            )
            == 70
        )

    def test_the_sample_component_is_capped_at_thirty_points(self, api):
        """PRD §3.5: "Four components add together. The mode base contributes nothing for `NONE`, 30 points for `SAMPLED`, 70 points for `PRE_DECISION_REVIEW` and 90 points for `DUAL_REVIEW`. The sample component applies only when `review_mode` is `SAMPLED`, and is `sample_pct` multiplied by three tenths, taken down to the next whole number, then capped at 30 — so sampling every decision earns the full 30 while sampling half of them earns 15; for every other review mode the sample component is 0 regardless of what `sample_pct` says. The SLA component starts from 20 points and subtracts one point for every whole 6 hours of `escalation_sla_hours`, with the result floored at 0 so it can never go negative — an SLA of 6 hours costs 1 point, an SLA of 240 hours costs the full 20 and leaves nothing. The override component is 10 points when `override_capability` is true and nothing when it is false. `adequacy_score` is the sum of the four, capped at 100. Both flooring operations happen inside their own components, before the outer capping and flooring are applied — never afterwards."

        Design: Difficulty/combinatorial_formula/oversight_adequacy_nested_cap_and_zero_clamp_mode_a
        """
        pin_clock(api)
        classified = classified_use_case(api, ROSTER_INTAKE)

        design = _file_sampled_design(api, classified["id"], 100, 0)

        # 30 mode base + 30 capped sample component + 20 untouched SLA + 10 override.
        assert design["adequacy_score"] == 90
        assert (
            expected_adequacy_score(
                {
                    "review_mode": "SAMPLED",
                    "sample_pct": 100,
                    "escalation_sla_hours": 0,
                    "override_capability": True,
                }
            )
            == 90
        )

    def test_the_design_is_approved_because_the_comparison_is_inclusive(self, api):
        """PRD §3.5: "Approving moves the design `DRAFT → APPROVED` and requires `adequacy_score` to be at least `required_adequacy_score`; a shortfall is rejected with `ERR_OVERSIGHT_DESIGN_INADEQUATE`."

        Design: Difficulty/combinatorial_formula/oversight_adequacy_nested_cap_and_zero_clamp_mode_a
        """
        pin_clock(api)
        classified = classified_use_case(api, ROSTER_INTAKE)
        design = _file_sampled_design(api, classified["id"], 100, 126)
        assert design["adequacy_score"] == design["required_adequacy_score"] == 70

        decided = validate_success(
            api.decide_oversight_design(
                design["id"], design_decision_payload("APPROVE"), headers=OFFICER
            )
        )

        assert_oversight_design(
            decided, status="APPROVED", adequacy_score=70, required_adequacy_score=70
        )


class TestControlDebtRoundedPerGateThenSummed:
    """Rounding each gate first and summing after differs from summing first."""

    def test_each_gate_rounds_its_own_debt_to_the_cent(self, api):
        """PRD §3.3: "A gate's `control_debt_index` is its gate-type weight, multiplied by its `open_condition_count` divided by 3, multiplied by the tier multiplier of its own `pinned_risk_tier`, with the product rounded half up to two decimal places. The gate-type weights are 1.35 for `LEGAL`, 1.25 for `PRIVACY`, 1.15 for `SECURITY` and 0.75 for `BUSINESS`. The tier multipliers are 0.5 for `MINIMAL`, 1.0 for `LIMITED`, 1.5 for `HIGH` and 2.0 for `PROHIBITED`."

        PRD §2.7: "**Control debt carries two decimal places and is rounded per gate, never per portfolio.** The control debt a single gate carries is rounded half up to two decimal places at the gate, and the portfolio total is the plain sum of those already-rounded per-gate values. Summing the unrounded products first and rounding the sum once at the end is incorrect and yields a different cent value. To make the ordering unambiguous: for a `HIGH`-tier use case whose `LEGAL` gate holds two open conditions and whose `PRIVACY`, `SECURITY` and `BUSINESS` gates each hold one, the mandated order yields per-gate values of 1.35, 0.63, 0.58 and 0.38 and a total of 2.94, whereas summing first and rounding once would yield 2.93. The mandated total is 2.94."

        Design: Difficulty/combinatorial_formula/control_debt_round_per_gate_then_sum_mode_b
        """
        chain = high_tier_with_conditions_on_every_gate(api)
        gates = gates_by_type(api, chain.use_case_id)

        expected = {"LEGAL": 1.35, "PRIVACY": 0.63, "SECURITY": 0.58, "BUSINESS": 0.38}
        counts = {"LEGAL": 2, "PRIVACY": 1, "SECURITY": 1, "BUSINESS": 1}
        for gate_type, debt in expected.items():
            assert_review_gate(
                gates[gate_type],
                status="CONDITIONS_ISSUED",
                pinned_risk_tier="HIGH",
                open_condition_count=counts[gate_type],
            )
            assert_debt_equals(gates[gate_type]["control_debt_index"], debt)
            assert expected_gate_debt(gate_type, counts[gate_type], "HIGH") == debt

    def test_the_portfolio_total_sums_the_already_rounded_gate_values(self, api):
        """PRD §2.7: "**Control debt carries two decimal places and is rounded per gate, never per portfolio.** The control debt a single gate carries is rounded half up to two decimal places at the gate, and the portfolio total is the plain sum of those already-rounded per-gate values. Summing the unrounded products first and rounding the sum once at the end is incorrect and yields a different cent value. To make the ordering unambiguous: for a `HIGH`-tier use case whose `LEGAL` gate holds two open conditions and whose `PRIVACY`, `SECURITY` and `BUSINESS` gates each hold one, the mandated order yields per-gate values of 1.35, 0.63, 0.58 and 0.38 and a total of 2.94, whereas summing first and rounding once would yield 2.93. The mandated total is 2.94."

        PRD §2.11: "`control_debt_index_total` is the sum of `control_debt_index` over every gate whose status is `PENDING`, `IN_REVIEW`, `CONDITIONS_ISSUED` or `CLEARED`; `VOIDED` gates are excluded entirely."

        Design: Difficulty/combinatorial_formula/control_debt_round_per_gate_then_sum_mode_b
        """
        high_tier_with_conditions_on_every_gate(api)

        summary = read_summary(api)

        assert_debt_equals(summary["control_debt_index_total"], 2.94)
        assert (
            expected_debt_total(
                {"LEGAL": 2, "PRIVACY": 1, "SECURITY": 1, "BUSINESS": 1}, "HIGH"
            )
            == 2.94
        )

    def test_the_five_open_conditions_push_the_intake_back_to_its_requester(self, api):
        """PRD §2.10: "`open_conditions_count` on a `UseCase` is the sum of `open_condition_count` over that use case's gates whose status is `CONDITIONS_ISSUED`."

        PRD §3.3: "Issuing conditions moves a gate `IN_REVIEW → CONDITIONS_ISSUED`. The reviewer supplies a `conditions` array of between 1 and 20 remediation strings, and optionally a `decision_note`. `open_condition_count` becomes the number of entries supplied, `control_debt_index` is recomputed for the gate, the use case's `open_conditions_count` is recomputed, and the use case bubbles `UNDER_REVIEW → CHANGES_REQUESTED` — any single gate issuing conditions pushes the whole intake back to its requester."

        Design: Difficulty/combinatorial_formula/control_debt_round_per_gate_then_sum_mode_b
        """
        chain = high_tier_with_conditions_on_every_gate(api)

        use_case = read_use_case(api, chain.use_case_id)

        assert use_case["open_conditions_count"] == 5
        assert use_case["status"] == "CHANGES_REQUESTED"
        assert use_case["cleared_gate_count"] == 0


class TestClassificationForksToReviewOrRejection:
    """One trigger, two mutually exclusive targets, one of them terminal."""

    def test_the_ordinary_branch_moves_the_intake_into_review(self, api):
        """PRD §3.2: "Individual impact contributes nothing for `NONE`, 10 points for `LOW`, 25 points for `MATERIAL` and 40 points for `CONSEQUENTIAL`; these land on the snapshot as `impact_points`. Decision autonomy contributes nothing for `ADVISORY`, 8 points for `HUMAN_IN_LOOP`, 18 points for `HUMAN_ON_LOOP` and 30 points for `FULLY_AUTOMATED`, recorded as `autonomy_points`. Data sensitivity contributes nothing for `PUBLIC`, 6 points for `INTERNAL`, 14 points for `CONFIDENTIAL` and 24 points for `SPECIAL_CATEGORY`, recorded as `sensitivity_points`. Reach contributes by band, taking the first band that matches `deployed_headcount_reach`: 6 points at one hundred thousand individuals a year or more, otherwise 4 points at ten thousand or more, otherwise 2 points at one thousand or more, otherwise nothing; this is `reach_points`. Finally, `jurisdiction_points` is 3 points for each declared jurisdiction that is one of the three high-scrutiny jurisdictions `EU`, `UK` and `US_CO` — a use case declaring all three of those plus `US_FED` therefore earns 9 points, not 12. The five contributions add up to `base_score`."

        PRD §3.2: "Banding then follows: a `risk_score` of 85 or more is `PROHIBITED`, 70 or more is `HIGH`, 35 or more is `LIMITED`, and anything below 35 is `MINIMAL`."

        PRD §3.2: "Classification therefore forks into two branches from one action, and their side effects diverge sharply. Both branches increment `classification_cycle_index` by 1, append a `ClassificationSnapshot` for that cycle, write `risk_score` and `risk_tier` onto the use case, clear `classification_stale` to false, and increment the use case's `version`."

        PRD §3.2: "**On the ordinary branch**, where the prohibited combination does not hold, the use case moves `DRAFT → UNDER_REVIEW`. `required_gate_types` is set from the provisional tier in the canonical order `LEGAL`, `PRIVACY`, `SECURITY`, `BUSINESS`: a `MINIMAL` tier demands only the `BUSINESS` gate, a `LIMITED` tier demands `PRIVACY` and `BUSINESS`, a `HIGH` tier demands all four, and a `PROHIBITED` tier demands none."

        Design: Difficulty/non_linear_state_machine/classify_forks_to_review_or_prohibited_terminal
        """
        pin_clock(api)
        draft = file_use_case(api, ORDINARY_INTAKE)
        assert expected_base_score(ORDINARY_INTAKE) == 44

        classified = validate_success(
            api.classify_use_case(
                draft["id"], classify_payload(draft["version"]), headers=OFFICER
            )
        )

        assert classified["status"] == "UNDER_REVIEW"
        assert classified["risk_score"] == 44
        assert classified["risk_tier"] == "LIMITED"
        assert classified["required_gate_types"] == ["PRIVACY", "BUSINESS"]
        assert classified["rejection_reason"] is None
        assert classified["classification_cycle_index"] == 1
        assert classified["classification_stale"] is False
        assert classified["version"] == draft["version"] + 1

    def test_the_ordinary_branch_creates_the_two_limited_gates_it_demands(self, api):
        """PRD §3.2: "Every pre-existing gate on the use case that is not already `VOIDED` is moved to `VOIDED` with `control_debt_index` zeroed to 0.00, and then one fresh `ReviewGate` is created per entry of `required_gate_types`, in that canonical creation order, each starting in status `PENDING`, each with `pinned_risk_tier` frozen to the tier just computed and `pinned_classification_index` frozen to the new `classification_cycle_index`."

        PRD §2.3: "This ordering is load-bearing in one place in particular: because the review gates a classification creates are created in the canonical order `LEGAL`, `PRIVACY`, `SECURITY`, `BUSINESS`, listing a use case's gates by `created_at` ascending yields that same canonical order and is therefore index-stable across runs."

        Design: Difficulty/non_linear_state_machine/classify_forks_to_review_or_prohibited_terminal
        """
        pin_clock(api)
        draft = file_use_case(api, ORDINARY_INTAKE)

        validate_success(
            api.classify_use_case(
                draft["id"], classify_payload(draft["version"]), headers=OFFICER
            )
        )

        records, meta = validate_paginated(
            api.list_review_gates(draft["id"], headers=OFFICER)
        )
        assert meta["total_count"] == 2
        assert_gate_order(records, ["PRIVACY", "BUSINESS"])
        for gate in records:
            assert_review_gate(
                gate,
                status="PENDING",
                pinned_risk_tier="LIMITED",
                pinned_classification_index=1,
                open_condition_count=0,
            )
            assert_debt_equals(gate["control_debt_index"], 0.00)

    def test_the_prohibited_conjunction_rejects_outright_and_opens_no_gate(self, api):
        """PRD §3.2: "When `affects_individuals` is true **and** `individual_impact` is `CONSEQUENTIAL` **and** `decision_autonomy` is `FULLY_AUTOMATED` **and** `data_sensitivity` is `SPECIAL_CATEGORY`, the combination is prohibited outright: `forced_prohibited` on the snapshot is set to true and `risk_tier` becomes `PROHIBITED` regardless of what the score came to."

        PRD §3.2: "**On the prohibited branch**, where the combination holds, the use case moves `DRAFT → REJECTED`, which is terminal. The snapshot records `forced_prohibited` true and `risk_tier` `PROHIBITED`; `required_gate_types` is set to empty and **no gate rows are created at all**; `rejection_reason` is recorded as the literal string `PROHIBITED_COMBINATION`; and a `GovernanceLedgerEntry` of type `CLASSIFICATION_REJECTED` is appended with `reach_delta` 0 and `debt_delta` 0.00."

        Design: Difficulty/non_linear_state_machine/classify_forks_to_review_or_prohibited_terminal
        """
        pin_clock(api)
        draft = file_use_case(api, PROHIBITED_CONJUNCTION_INTAKE)
        assert expected_base_score(PROHIBITED_CONJUNCTION_INTAKE) == 97

        classified = validate_success(
            api.classify_use_case(
                draft["id"], classify_payload(draft["version"]), headers=OFFICER
            )
        )

        assert classified["status"] == "REJECTED"
        assert classified["risk_score"] == 97
        assert classified["risk_tier"] == "PROHIBITED"
        assert classified["rejection_reason"] == "PROHIBITED_COMBINATION"
        assert classified["required_gate_types"] == []
        assert classified["classification_cycle_index"] == 1
        assert classified["version"] == draft["version"] + 1

        snapshots = list_snapshots(api, draft["id"])
        assert len(snapshots) == 1
        assert_classification_snapshot(
            snapshots[0],
            variant="INTAKE_PROVISIONAL",
            forced_prohibited=True,
            risk_score=97,
            risk_tier="PROHIBITED",
        )

        gates, meta = validate_paginated(
            api.list_review_gates(draft["id"], headers=OFFICER)
        )
        assert meta["total_count"] == 0
        assert gates == []

    def test_only_the_rejected_branch_books_a_ledger_entry(self, api):
        """PRD §3.2: "**On the prohibited branch**, where the combination holds, the use case moves `DRAFT → REJECTED`, which is terminal. The snapshot records `forced_prohibited` true and `risk_tier` `PROHIBITED`; `required_gate_types` is set to empty and **no gate rows are created at all**; `rejection_reason` is recorded as the literal string `PROHIBITED_COMBINATION`; and a `GovernanceLedgerEntry` of type `CLASSIFICATION_REJECTED` is appended with `reach_delta` 0 and `debt_delta` 0.00."

        PRD §2.11: "Every governance event of consequence appends a `GovernanceLedgerEntry` against the use case whose position it moves."

        Design: Difficulty/non_linear_state_machine/classify_forks_to_review_or_prohibited_terminal
        """
        pin_clock(api)
        ordinary = classified_use_case(api, ORDINARY_INTAKE)
        rejected = classified_use_case(api, PROHIBITED_CONJUNCTION_INTAKE)

        rejected_entries = list_ledger(api, rejected["id"])
        ordinary_entries = list_ledger(api, ordinary["id"])

        assert len(rejected_entries) == 1
        assert_ledger_entry(
            rejected_entries[0],
            entry_type="CLASSIFICATION_REJECTED",
            reach_delta=0,
            use_case_id=rejected["id"],
        )
        assert rejected_entries[0]["debt_delta"] == pytest.approx(0.00, abs=0.01)
        assert ordinary_entries == []

    def test_the_rejected_branch_is_terminal_for_a_second_classification(self, api):
        """PRD §2.8: "A record whose parent use case has reached a terminal status is frozen. If the addressed use case — or the parent use case of the addressed child record — is `REJECTED` or `REVOKED`, every mutating request against it is rejected with `ERR_USE_CASE_TERMINAL` (HTTP 409). Reads are unaffected."

        Design: Difficulty/non_linear_state_machine/classify_forks_to_review_or_prohibited_terminal
        """
        pin_clock(api)
        rejected = classified_use_case(api, PROHIBITED_CONJUNCTION_INTAKE)
        assert rejected["status"] == "REJECTED"

        response = api.classify_use_case(
            rejected["id"],
            classify_payload(current_version(api, rejected["id"])),
            headers=OFFICER,
        )

        validate_error(response, ApiErrorId.USE_CASE_TERMINAL)


class TestReviewGateConditionLoopAndReopen:
    """The gate re-enters IN_REVIEW twice through conditions and once by reopen."""

    def test_the_first_condition_pass_books_debt_and_pushes_the_intake_back(self, api):
        """PRD §3.3: "Issuing conditions moves a gate `IN_REVIEW → CONDITIONS_ISSUED`. The reviewer supplies a `conditions` array of between 1 and 20 remediation strings, and optionally a `decision_note`. `open_condition_count` becomes the number of entries supplied, `control_debt_index` is recomputed for the gate, the use case's `open_conditions_count` is recomputed, and the use case bubbles `UNDER_REVIEW → CHANGES_REQUESTED` — any single gate issuing conditions pushes the whole intake back to its requester."

        PRD §3.3: "A gate's `control_debt_index` is its gate-type weight, multiplied by its `open_condition_count` divided by 3, multiplied by the tier multiplier of its own `pinned_risk_tier`, with the product rounded half up to two decimal places. The gate-type weights are 1.35 for `LEGAL`, 1.25 for `PRIVACY`, 1.15 for `SECURITY` and 0.75 for `BUSINESS`. The tier multipliers are 0.5 for `MINIMAL`, 1.0 for `LIMITED`, 1.5 for `HIGH` and 2.0 for `PROHIBITED`."

        Design: Difficulty/non_linear_state_machine/review_gate_condition_loop_traversed_twice_then_reopened
        """
        use_case, gates = _loop_use_case(api)
        assert use_case["risk_tier"] == "LIMITED"
        take_up_gate(api, gates["PRIVACY"]["id"], "PRIVACY")

        gate = validate_success(
            api.issue_gate_conditions(
                gates["PRIVACY"]["id"],
                issue_conditions_payload(conditions(2)),
                headers=PRIVACY_REVIEWER,
            )
        )

        assert_review_gate(
            gate,
            gate_type="PRIVACY",
            status="CONDITIONS_ISSUED",
            pinned_risk_tier="LIMITED",
            open_condition_count=2,
        )
        assert len(gate["conditions"]) == 2
        assert_debt_equals(gate["control_debt_index"], 0.83)
        assert expected_gate_debt("PRIVACY", 2, "LIMITED") == 0.83

        parent = read_use_case(api, use_case["id"])
        assert parent["status"] == "CHANGES_REQUESTED"
        assert parent["open_conditions_count"] == 2

    def test_the_second_take_up_wipes_the_loop_state_and_reassigns_the_gate(self, api):
        """PRD §3.3: "Taking up a gate moves it `PENDING → IN_REVIEW` or `CONDITIONS_ISSUED → IN_REVIEW`, sets `assigned_reviewer_user_id` to the acting `X-User-ID`, and is permitted only while the parent use case is in `UNDER_REVIEW` or `CHANGES_REQUESTED`. Coming out of `CONDITIONS_ISSUED` it additionally wipes the slate: `conditions` becomes empty, `open_condition_count` drops to 0 and `control_debt_index` drops to 0.00. The use case's `open_conditions_count` is then recomputed, and if it reaches 0 the use case bubbles `CHANGES_REQUESTED → UNDER_REVIEW`; while any other gate still holds open conditions the use case stays in `CHANGES_REQUESTED`."

        Design: Difficulty/non_linear_state_machine/review_gate_condition_loop_traversed_twice_then_reopened
        """
        use_case, gates = _loop_use_case(api)
        _first_condition_pass(api, gates["PRIVACY"]["id"])

        gate = validate_success(
            api.start_gate_review(
                gates["PRIVACY"]["id"], headers=PRIVACY_REVIEWER_2
            )
        )

        assert_review_gate(
            gate,
            status="IN_REVIEW",
            open_condition_count=0,
            assigned_reviewer_user_id=USER_PRIVACY_2,
        )
        assert gate["conditions"] == []
        assert_debt_equals(gate["control_debt_index"], 0.00)

        parent = read_use_case(api, use_case["id"])
        assert parent["status"] == "UNDER_REVIEW"
        assert parent["open_conditions_count"] == 0

    def test_the_second_condition_pass_rebooks_the_single_condition_debt(self, api):
        """PRD §3.3: "Issuing conditions moves a gate `IN_REVIEW → CONDITIONS_ISSUED`. The reviewer supplies a `conditions` array of between 1 and 20 remediation strings, and optionally a `decision_note`. `open_condition_count` becomes the number of entries supplied, `control_debt_index` is recomputed for the gate, the use case's `open_conditions_count` is recomputed, and the use case bubbles `UNDER_REVIEW → CHANGES_REQUESTED` — any single gate issuing conditions pushes the whole intake back to its requester."

        PRD §3.3: "A gate's `control_debt_index` is its gate-type weight, multiplied by its `open_condition_count` divided by 3, multiplied by the tier multiplier of its own `pinned_risk_tier`, with the product rounded half up to two decimal places. The gate-type weights are 1.35 for `LEGAL`, 1.25 for `PRIVACY`, 1.15 for `SECURITY` and 0.75 for `BUSINESS`. The tier multipliers are 0.5 for `MINIMAL`, 1.0 for `LIMITED`, 1.5 for `HIGH` and 2.0 for `PROHIBITED`."

        Design: Difficulty/non_linear_state_machine/review_gate_condition_loop_traversed_twice_then_reopened
        """
        use_case, gates = _loop_use_case(api)
        _first_condition_pass(api, gates["PRIVACY"]["id"])
        _second_take_up(api, gates["PRIVACY"]["id"])

        gate = validate_success(
            api.issue_gate_conditions(
                gates["PRIVACY"]["id"],
                issue_conditions_payload(conditions(1)),
                headers=PRIVACY_REVIEWER_2,
            )
        )

        assert_review_gate(gate, status="CONDITIONS_ISSUED", open_condition_count=1)
        assert_debt_equals(gate["control_debt_index"], 0.42)
        assert expected_gate_debt("PRIVACY", 1, "LIMITED") == 0.42

        parent = read_use_case(api, use_case["id"])
        assert parent["status"] == "CHANGES_REQUESTED"
        assert parent["open_conditions_count"] == 1

    def test_the_loop_can_be_left_straight_out_of_conditions_issued(self, api):
        """PRD §3.3: "The gate must be in `IN_REVIEW` or `CONDITIONS_ISSUED` (a reviewer may clear straight out of `CONDITIONS_ISSUED` when the requester satisfied the conditions out of band); the acting role must own the `gate_type`, or the request fails with `ERR_GATE_ROLE_MISMATCH`; and the acting `X-User-ID` must not be the use case's `requester_user_id`, or the request fails with `ERR_SEGREGATION_OF_DUTIES`."

        PRD §3.3: "Once those pass, the clearance captures `debt_before_clear` from the gate's current `control_debt_index` (this is what makes the compensating reopen exact), zeroes `control_debt_index` to 0.00 and `open_condition_count` to 0, records `cleared_by_user_id` and `cleared_at`, and appends a `GovernanceLedgerEntry` of type `GATE_CLEARED` with `reach_delta` 0 and a `debt_delta` of minus the captured `debt_before_clear`."

        Design: Difficulty/non_linear_state_machine/review_gate_condition_loop_traversed_twice_then_reopened
        """
        use_case, gates = _loop_use_case(api)
        _first_condition_pass(api, gates["PRIVACY"]["id"])
        _second_take_up(api, gates["PRIVACY"]["id"])
        _second_condition_pass(api, gates["PRIVACY"]["id"])

        gate = validate_success(
            api.clear_gate(
                gates["PRIVACY"]["id"],
                {"decision_note": "schedule published"},
                headers=PRIVACY_REVIEWER_2,
            )
        )

        assert_review_gate(
            gate,
            status="CLEARED",
            open_condition_count=0,
            cleared_by_user_id=USER_PRIVACY_2,
        )
        assert_debt_equals(gate["debt_before_clear"], 0.42)
        assert_debt_equals(gate["control_debt_index"], 0.00)
        assert gate["cleared_at"] is not None
        assert read_use_case(api, use_case["id"])["cleared_gate_count"] == 1

    def test_clearing_the_second_gate_bubbles_the_use_case_to_ready(self, api):
        """PRD §3.3: "Taking up a gate moves it `PENDING → IN_REVIEW` or `CONDITIONS_ISSUED → IN_REVIEW`, sets `assigned_reviewer_user_id` to the acting `X-User-ID`, and is permitted only while the parent use case is in `UNDER_REVIEW` or `CHANGES_REQUESTED`."

        PRD §3.3: "The use case's `cleared_gate_count` is recomputed. When, after this clearance, every non-`VOIDED` gate on the use case is `CLEARED` and `cleared_gate_count` equals the number of entries in `required_gate_types`, the use case bubbles `UNDER_REVIEW → READY_FOR_APPROVAL`."

        Design: Difficulty/non_linear_state_machine/review_gate_condition_loop_traversed_twice_then_reopened
        """
        use_case, gates = _loop_with_cleared_privacy(api)

        taken_up = validate_success(
            api.start_gate_review(gates["BUSINESS"]["id"], headers=BUSINESS_REVIEWER)
        )
        assert taken_up["status"] == "IN_REVIEW"
        assert read_use_case(api, use_case["id"])["status"] == "UNDER_REVIEW"

        cleared = validate_success(
            api.clear_gate(
                gates["BUSINESS"]["id"],
                {"decision_note": "benefit case accepted"},
                headers=BUSINESS_REVIEWER,
            )
        )

        assert cleared["status"] == "CLEARED"
        parent = read_use_case(api, use_case["id"])
        assert parent["status"] == "READY_FOR_APPROVAL"
        assert parent["cleared_gate_count"] == 2

    def test_the_reopen_re_enters_the_cycle_and_restores_the_exact_debt(self, api):
        """PRD §3.3: "It moves a gate `CLEARED → IN_REVIEW`, and is permitted only while the parent use case is in `UNDER_REVIEW`, `CHANGES_REQUESTED` or `READY_FOR_APPROVAL`. It restores `control_debt_index` verbatim from `debt_before_clear`, sets `open_condition_count` to 0, nulls both `cleared_by_user_id` and `cleared_at`, optionally records a `decision_note`, and appends a `GovernanceLedgerEntry` of type `GATE_REOPENED` with `reach_delta` 0 and a `debt_delta` of plus that same `debt_before_clear`."

        PRD §3.3: "The use case's `cleared_gate_count` and `open_conditions_count` are recomputed and the use case is pushed `READY_FOR_APPROVAL → UNDER_REVIEW`."

        PRD §2.11: "For any gate, clearing and then reopening is debt-neutral by construction: clearance books a `debt_delta` of minus the debt the gate carried and reopening books plus exactly that same figure, so `control_debt_index_total` returns to its exact pre-clearance cent value and the ledger debt balance for that use case returns to 0.00."

        Design: Difficulty/non_linear_state_machine/review_gate_condition_loop_traversed_twice_then_reopened
        """
        use_case, gates = _loop_ready_for_approval(api)

        gate = validate_success(
            api.reopen_gate(
                gates["PRIVACY"]["id"],
                {"decision_note": "new corpus added, privacy must look again"},
                headers=OFFICER,
            )
        )

        assert_review_gate(gate, status="IN_REVIEW", open_condition_count=0)
        assert_debt_equals(gate["control_debt_index"], 0.42)
        assert gate["cleared_by_user_id"] is None
        assert gate["cleared_at"] is None

        parent = read_use_case(api, use_case["id"])
        assert parent["status"] == "UNDER_REVIEW"
        assert parent["cleared_gate_count"] == 1

    def test_a_second_reopen_is_refused_because_the_gate_left_cleared(self, api):
        """PRD §2.9: "The addressed gate is in a status the requested action has a transition out of: take-up needs `PENDING` or `CONDITIONS_ISSUED`, issuing conditions needs `IN_REVIEW`, clearing needs `IN_REVIEW` or `CONDITIONS_ISSUED`, reopening needs `CLEARED` — `ERR_GATE_NOT_IN_REVIEWABLE_STATE` (409), on all four gate actions."

        Design: Difficulty/non_linear_state_machine/review_gate_condition_loop_traversed_twice_then_reopened
        """
        _use_case, gates = _loop_ready_for_approval(api)
        get_success_data(
            api.reopen_gate(
                gates["PRIVACY"]["id"],
                {"decision_note": "first reopen"},
                headers=OFFICER,
            )
        )

        response = api.reopen_gate(
            gates["PRIVACY"]["id"],
            {"decision_note": "second reopen"},
            headers=OFFICER,
        )

        validate_error(response, ApiErrorId.GATE_NOT_IN_REVIEWABLE_STATE)
