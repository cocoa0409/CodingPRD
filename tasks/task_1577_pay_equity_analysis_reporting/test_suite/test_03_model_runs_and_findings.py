"""Model runs, gap findings, and methodology variants (PRD §2.6, §3.2, §3.3)."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_snapshots,
    advance_study,
    assign_snapshot,
    create_group,
    create_run,
    create_study,
    finalize_run,
    four_two_dim_member_specs,
    get_group,
    list_run_findings,
    lock_group,
    member_spec,
    seven_eng_member_specs,
    setup_analyzed_study,
    setup_provisional_run_scenario,
    setup_remediation_open,
    two_eng_member_specs,
    validate_error,
    validate_paginated,
    validate_success,
)

ANALYST = TEST_USERS["comp_analyst_headers"]


class TestMethodologyVariantsDiverge:
    def test_cohort_median_run_values(self, api):
        """PRD §3.2: "Under `COHORT_MEDIAN`, no level deflation is applied: the raw `annualized_base_cents` medians of the reference members and of the class members are taken — for an even member count, the median is the exact mean of the two middle values — and the gap is the reference median minus the class median, divided by the reference median, expressed as a percentage, rounded half-up to four decimal places."
        PRD §3.2: "Statistical significance follows a fixed heuristic shared by both variants: the `p_value` is one divided by the quantity one plus the `class_headcount` multiplied by the absolute value of the adjusted gap percentage, using the already-rounded four-decimal gap, with the result itself rounded half-up to four decimal places."
        PRD §3.3: "the finding is actionable when its `adjusted_gap_pct` is at least the study's `actionable_gap_pct` and its `p_value` is no greater than the study's `significance_threshold` — a gap exactly equal to the threshold qualifies, as does a p-value exactly equal to the ceiling."

        Design: Difficulty/dual_variant_calc/gap_methodology_variants_diverge
        """
        ctx = setup_analyzed_study(
            name="StudyGap", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=seven_eng_member_specs(),
            group_name="ENG-CA-L4-6", min_job_level=4, max_job_level=6,
            min_group_size=7, methodology="COHORT_MEDIAN",
        )
        # Median reference pay 10500000 vs class median 9500000 -> 9.5238.
        finding = ctx["findings"][0]
        assert finding["protected_class"] == "GENDER"
        assert finding["class_value"] == "FEMALE"
        assert finding["reference_class"] == "MALE"
        assert finding["adjusted_gap_pct"] == pytest.approx(9.5238, abs=1e-9)
        # p = ROUND(1 / (1 + 3 * 9.5238), 4) = 0.0338; 0.0338 <= 0.05 default ceiling.
        assert finding["p_value"] == pytest.approx(0.0338, abs=1e-9)
        assert finding["is_actionable"] is True
        assert finding["status"] == "FLAGGED"

    def test_regression_ols_run_values_diverge_on_identical_membership(self, api):
        """PRD §3.2: "Under `REGRESSION_OLS`, each member's pay is first level-deflated individually: the member's `annualized_base_cents` is divided by one plus a per-level loading of 0.04 multiplied by the member's `job_level` minus one, and the result is rounded half-up to two decimal places per employee before any averaging."
        PRD §3.2: "The same membership can therefore yield different gaps under the two methodologies, which is why the methodology is pinned on the run."
        PRD §3.2: "A `CompAnalyst` then runs a statistical model against a group that is `LOCKED` or `ANALYZED` (otherwise `ERR_GROUP_INVALID_STATE`) and whose study is in `MODELING` or `MONITORING`."

        Design: Difficulty/dual_variant_calc/gap_methodology_variants_diverge
        """
        ctx = setup_analyzed_study(
            name="StudyGap", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=seven_eng_member_specs(),
            group_name="ENG-CA-L4-6", min_job_level=4, max_job_level=6,
            min_group_size=7, methodology="COHORT_MEDIAN",
        )
        median_finding = ctx["findings"][0]
        # The group is ANALYZED and the study MODELING, so a second run on the
        # identical membership is permitted; re-read the version for the OCC token.
        ols_run = create_run(ctx["group"]["id"], methodology="REGRESSION_OLS")
        ols_run = finalize_run(ols_run["id"])
        ols_finding = list_run_findings(ols_run["id"])[0]
        # Level-deflated means 8750000.00 (reference) vs 8482142.86 (class) -> 3.0612.
        assert ols_finding["adjusted_gap_pct"] == pytest.approx(3.0612, abs=1e-9)
        # p = ROUND(1 / (1 + 3 * 3.0612), 4) = 0.0982; 0.0982 > 0.05 -> not actionable.
        assert ols_finding["p_value"] == pytest.approx(0.0982, abs=1e-9)
        assert ols_finding["is_actionable"] is False
        # The two methodologies diverge on the identical membership.
        assert ols_finding["adjusted_gap_pct"] != pytest.approx(
            median_finding["adjusted_gap_pct"], abs=1e-9
        )


class TestFinalizeGenerationCascade:
    def test_finalize_generates_flagged_findings_with_frozen_values(self, api):
        """PRD §3.3: "For each key of the run's `per_class_results` whose dimension appears in the study's `protected_classes`, the server generates one gap finding in `FLAGGED` status."
        PRD §3.3: "Each finding records its `model_run_id`, its `comparator_group_id` and `study_id` denormalized from the run, the `protected_class` dimension, the non-reference `class_value` analyzed, the `reference_class` baseline, the `adjusted_gap_pct` and `p_value` copied from the run's results, and an `affected_headcount` equal to the class headcount at generation."
        PRD §3.2: "Finalizing a run, performed by a `CompAnalyst`, requires the run to be in `PROVISIONAL` (otherwise `ERR_RUN_INVALID_STATE`). Finalization stamps `finalized_at` from the logical clock and moves the run to `FINAL`."

        Design: Difficulty/transitive_cascade/finalize_generation_cascade
        """
        ctx = setup_provisional_run_scenario(
            name="StudyD", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", protected_classes=("GENDER", "AGE_BAND"),
            member_specs=four_two_dim_member_specs(), group_name="GD",
            min_job_level=5, max_job_level=5, min_group_size=4,
            methodology="COHORT_MEDIAN",
        )
        assert ctx["group"]["status"] == "LOCKED"
        assert ctx["run"]["status"] == "PROVISIONAL"

        finalized = finalize_run(ctx["run"]["id"])
        assert finalized["status"] == "FINAL"
        # finalized_at reads from the logical clock, still at its startup default.
        assert finalized["finalized_at"].startswith("2026-08-01T00:00:00")

        findings = list_run_findings(ctx["run"]["id"])
        assert len(findings) == 2
        by_class = {(f["protected_class"], f["class_value"]): f for f in findings}
        assert set(by_class) == {("GENDER", "FEMALE"), ("AGE_BAND", "FORTY_PLUS")}
        for f in findings:
            assert f["model_run_id"] == ctx["run"]["id"]
            assert f["comparator_group_id"] == ctx["group"]["id"]
            assert f["study_id"] == ctx["study"]["id"]
            assert f["status"] == "FLAGGED"
        # GENDER:FEMALE — medians 10500000 vs 9250000 -> 11.9048, p 0.0403.
        gender = by_class[("GENDER", "FEMALE")]
        assert gender["reference_class"] == "MALE"
        assert gender["adjusted_gap_pct"] == pytest.approx(11.9048, abs=1e-9)
        assert gender["p_value"] == pytest.approx(0.0403, abs=1e-9)
        assert gender["is_actionable"] is True
        # AGE_BAND:FORTY_PLUS — medians 9500000 vs 10250000 -> -7.8947, p 0.0596;
        # a negative gap is not actionable (it fails the >= actionable_gap_pct leg).
        age = by_class[("AGE_BAND", "FORTY_PLUS")]
        assert age["reference_class"] == "UNDER_40"
        assert age["adjusted_gap_pct"] == pytest.approx(-7.8947, abs=1e-9)
        assert age["p_value"] == pytest.approx(0.0596, abs=1e-9)
        assert age["is_actionable"] is False

    def test_finalize_flips_group_locked_to_analyzed(self, api):
        """PRD §3.2: "The parent group automatically transitions from `LOCKED` to `ANALYZED` once finding generation completes, and the study's finding aggregates are recomputed."

        Design: Difficulty/transitive_cascade/finalize_generation_cascade
        """
        ctx = setup_provisional_run_scenario(
            name="StudyD", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", protected_classes=("GENDER", "AGE_BAND"),
            member_specs=four_two_dim_member_specs(), group_name="GD",
            min_job_level=5, max_job_level=5, min_group_size=4,
            methodology="COHORT_MEDIAN",
        )
        assert ctx["group"]["status"] == "LOCKED"
        finalize_run(ctx["run"]["id"])
        assert get_group(ctx["group"]["id"])["status"] == "ANALYZED"


class TestRunStateGuards:
    def test_run_finalize_and_supersede_guards(self, api):
        """PRD §3.2: "The new run begins in `PROVISIONAL`, denormalizes `study_id` from its group, and receives a `run_index` equal to the count of the group's prior runs plus one. Creation immediately supersedes the group's prior `PROVISIONAL` runs — they become `SUPERSEDED` — and advances the group's `version` by one."
        PRD §3.2: "Finalizing a run, performed by a `CompAnalyst`, requires the run to be in `PROVISIONAL` (otherwise `ERR_RUN_INVALID_STATE`). Finalization stamps `finalized_at` from the logical clock and moves the run to `FINAL`."

        Design: Corner/state_machines/run_finalize_and_supersede_guards
        """
        ctx = setup_provisional_run_scenario(
            name="RS", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GRS", min_group_size=2, methodology="COHORT_MEDIAN",
        )
        r1 = ctx["run"]
        assert r1["run_index"] == 1
        assert r1["status"] == "PROVISIONAL"
        # A newer run supersedes the prior PROVISIONAL one and gets index 2.
        r2 = create_run(ctx["group"]["id"], methodology="REGRESSION_OLS")
        assert r2["run_index"] == 2
        r1_after = validate_success(api.get_model_run(r1["id"], ANALYST))
        assert r1_after["status"] == "SUPERSEDED"
        # Finalizing a SUPERSEDED run fails.
        res = api.finalize_run(r1["id"], ANALYST)
        validate_error(res, ApiErrorId.ERR_RUN_INVALID_STATE)
        # The current PROVISIONAL run finalizes.
        r2_final = finalize_run(r2["id"])
        assert r2_final["status"] == "FINAL"
        # Finalizing a FINAL run again fails.
        res2 = api.finalize_run(r2["id"], ANALYST)
        validate_error(res2, ApiErrorId.ERR_RUN_INVALID_STATE)

    def test_run_create_on_draft_group_rejected(self, api):
        """PRD §3.2: "A `CompAnalyst` then runs a statistical model against a group that is `LOCKED` or `ANALYZED` (otherwise `ERR_GROUP_INVALID_STATE`) and whose study is in `MODELING` or `MONITORING`."

        Design: Corner/state_machines/run_create_on_draft_group_rejected
        """
        study = create_study(
            name="RD", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        members = add_snapshots(study["id"], two_eng_member_specs())
        group = create_group(study["id"], name="GRD")
        for m in members:
            assign_snapshot(m["id"], group["id"])
        advance_study(study["id"])
        # Fresh (matching) version, but the group is still DRAFT.
        fresh_version = get_group(group["id"])["version"]
        res = api.create_model_run(
            {
                "comparator_group_id": group["id"],
                "methodology": "COHORT_MEDIAN",
                "expected_group_version": fresh_version,
            },
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_GROUP_INVALID_STATE)


class TestModelRunOcc:
    def test_stale_group_version_beats_state_rejection(self, api, people_ops_admin_headers):
        """PRD §2.6: "Creating a model run requires the request body to carry `expected_group_version`, holding the `version` of the parent comparator group as the client last observed it. If the group's current `version` has advanced since then, the create is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412)."
        PRD §2.8: "Fourth, the optimistic-concurrency version check runs where the endpoint participates in it (§2.6)."
        PRD §2.8: "Sixth, entity state preconditions for the attempted action are enforced (the state-guard errors catalogued in §5)."

        Design: Difficulty/priority_pair_validation_conflict/model_run_create_occ_beats_state
        """
        study = create_study(
            name="StudyF", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31",
        )
        snap = add_snapshots(
            study["id"], [member_spec("FM1", "MALE", 10000000)]
        )[0]
        group = create_group(study["id"], name="GF")
        stale_version = group["version"]
        # The membership PATCH advances the group's version, so the captured
        # version is stale; the group is also still DRAFT (state would fail too).
        assign_snapshot(snap["id"], group["id"])
        assert get_group(group["id"])["version"] != stale_version
        res = api.create_model_run(
            {
                "comparator_group_id": group["id"],
                "methodology": "COHORT_MEDIAN",
                "expected_group_version": stale_version,
            },
            ANALYST,
        )
        # The OCC check (fourth) precedes the state check (sixth).
        validate_error(res, ApiErrorId.ERR_STALE_GROUP_VERSION)
        # No model run is created for the group.
        data, meta = validate_paginated(
            api.list_model_runs(ANALYST, {"comparator_group_id": group["id"]})
        )
        assert data == []
        assert meta["total_count"] == 0

    def test_stale_group_version_rejected_on_locked_group(self, api):
        """PRD §2.6: "If the group's current `version` has advanced since then, the create is rejected with `ERR_STALE_GROUP_VERSION` (HTTP 412). This guard exists because a successful run creation supersedes the group's prior provisional runs and advances the group's `version`, so a client holding a stale version is acting on a superseded view of the group."

        Design: Difficulty/priority_pair_validation_conflict/model_run_create_occ_beats_state
        """
        study = create_study(
            name="StudyF2", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", min_group_size=2,
        )
        members = add_snapshots(study["id"], two_eng_member_specs())
        group = create_group(study["id"], name="GF2")
        for m in members:
            assign_snapshot(m["id"], group["id"])
        advance_study(study["id"])
        locked = lock_group(group["id"])
        observed_version = locked["version"]
        # A first creation with the observed (fresh) version succeeds and
        # advances the group's version.
        first = validate_success(
            api.create_model_run(
                {
                    "comparator_group_id": group["id"],
                    "methodology": "COHORT_MEDIAN",
                    "expected_group_version": observed_version,
                },
                ANALYST,
            ),
            201,
        )
        assert first["status"] == "PROVISIONAL"
        # Replaying the same token is now stale: the group version advanced.
        res = api.create_model_run(
            {
                "comparator_group_id": group["id"],
                "methodology": "REGRESSION_OLS",
                "expected_group_version": observed_version,
            },
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_STALE_GROUP_VERSION)
        # The rejected creation adds no run: still exactly one on the group.
        data, meta = validate_paginated(
            api.list_model_runs(ANALYST, {"comparator_group_id": group["id"]})
        )
        assert len(data) == 1
        assert meta["total_count"] == 1


class TestFindingDispositionGuards:
    def test_finding_disposition_guards(self, api):
        """PRD §3.3: "A `TARGETED` disposition marks the finding for remediation and is permitted only when the finding's `is_actionable` is true (otherwise `ERR_FINDING_NOT_ACTIONABLE`); a targeted finding still counts as unresolved."
        PRD §3.3: "A `DISMISSED` disposition closes the finding without action and requires a non-empty `disposition_rationale` (otherwise `ERR_RATIONALE_REQUIRED`), which is stored on the finding."
        PRD §3.3: "attempting a disposition while the study is in any other state is rejected with `ERR_STUDY_NOT_IN_REMEDIATION`, and the finding itself must still be `FLAGGED` (otherwise `ERR_FINDING_INVALID_STATE`)"

        Design: Corner/state_machines/finding_disposition_guards
        """
        ctx = setup_remediation_open(
            name="FD", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=two_eng_member_specs(),
            group_name="GFD", min_group_size=2, target_finding=False,
        )
        finding = ctx["findings"][0]
        # Fixture check: gap 10.0000 but p 0.0909 > 0.05 -> not actionable.
        assert finding["adjusted_gap_pct"] == pytest.approx(10.0, abs=1e-9)
        assert finding["p_value"] == pytest.approx(0.0909, abs=1e-9)
        assert finding["is_actionable"] is False
        assert finding["status"] == "FLAGGED"

        # TARGETED requires is_actionable.
        res = api.disposition_finding(finding["id"], {"disposition": "TARGETED"}, ANALYST)
        validate_error(res, ApiErrorId.ERR_FINDING_NOT_ACTIONABLE)
        # DISMISSED requires a non-empty disposition_rationale.
        res2 = api.disposition_finding(finding["id"], {"disposition": "DISMISSED"}, ANALYST)
        validate_error(res2, ApiErrorId.ERR_RATIONALE_REQUIRED)
        # DISMISSED with rationale succeeds and stores the rationale.
        dismissed = validate_success(
            api.disposition_finding(
                finding["id"],
                {
                    "disposition": "DISMISSED",
                    "disposition_rationale": "Gap within statistical noise band",
                },
                ANALYST,
            )
        )
        assert dismissed["status"] == "DISMISSED"
        assert dismissed["disposition_rationale"] == "Gap within statistical noise band"
        # DISMISSED is terminal: any further disposition fails on state.
        res3 = api.disposition_finding(finding["id"], {"disposition": "MONITORED"}, ANALYST)
        validate_error(res3, ApiErrorId.ERR_FINDING_INVALID_STATE)

    def test_actionability_p_at_significance_threshold_inclusive(self, api):
        """PRD §3.3: "A finding's `is_actionable` flag is derived by comparing those stored four-decimal values against the parent study's thresholds with both comparisons inclusive: the finding is actionable when its `adjusted_gap_pct` is at least the study's `actionable_gap_pct` and its `p_value` is no greater than the study's `significance_threshold` — a gap exactly equal to the threshold qualifies, as does a p-value exactly equal to the ceiling."

        Design: Corner/calculations/actionability_p_at_significance_threshold_inclusive
        """
        ctx = setup_analyzed_study(
            name="SG", analysis_period_start="2025-01-01",
            analysis_period_end="2025-12-31", member_specs=seven_eng_member_specs(),
            group_name="GSG", min_job_level=4, max_job_level=6, min_group_size=7,
            significance_threshold=0.0338, methodology="COHORT_MEDIAN",
        )
        finding = ctx["findings"][0]
        # The computed p_value lands exactly on the study's significance ceiling.
        assert finding["p_value"] == pytest.approx(0.0338, abs=1e-9)
        assert finding["adjusted_gap_pct"] == pytest.approx(9.5238, abs=1e-9)
        # Inclusive <= at the ceiling: the finding IS actionable.
        assert finding["is_actionable"] is True
