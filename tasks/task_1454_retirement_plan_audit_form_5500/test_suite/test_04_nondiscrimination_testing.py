"""Nondiscrimination and coverage testing: ratio math, OCC, finalize cascades."""
from test_helpers import (
    AUDITOR as AUD,
    SPONSOR,
    TPA,
    ApiErrorId,
    add_census_group,
    add_participant,
    api_client,
    create_engagement,
    create_filing_ready_to_file,
    get_single_finding,
    get_success_data,
    recompute_count,
    run_test,
    validate_error,
)


class TestAdpTestTiers:

    def test_alternative_limit_branch_passes_at_boundary(self):
        """PRD §3.5: "The `max_allowed_hce_pct` is the larger of two quantities:
        one-and-a-quarter times the `nhce_avg_pct` (the 1.25 aggregate-limit
        factor), and the smaller of two times the `nhce_avg_pct` (the
        alternative-limit multiplier) and the `nhce_avg_pct` plus 2.00 (the
        alternative-limit spread) — with each factor rounded half-up to two
        decimal places."
        PRD §3.5: "The `result` is `PASS` when the `hce_avg_pct` is less than or
        equal to the `max_allowed_hce_pct` — the comparison is boundary-inclusive
        — and `FAIL` otherwise."

        Census: NHCE ADRs 2.00/1.60 (avg 1.80) and HCE ADRs 4.00/3.20 (avg 3.60).
        max_allowed = max(2.25, min(3.60, 3.80)) = 3.60; 3.60 <= 3.60 passes.

        Design: Difficulty/combinatorial_formula/adp_test_tiered_min_max
        """
        eng = create_engagement(prior_year_schedule_type="H")
        add_participant(eng["id"], "N-001", is_hce=False, deferral_amount_cy_cents=200_000)
        add_participant(eng["id"], "N-002", is_hce=False, deferral_amount_cy_cents=160_000)
        add_participant(eng["id"], "H-001", is_hce=True, deferral_amount_cy_cents=400_000)
        add_participant(eng["id"], "H-002", is_hce=True, deferral_amount_cy_cents=320_000)
        result = run_test(eng["id"], "ADP")
        assert result["nhce_avg_pct"] == 1.80
        assert result["hce_avg_pct"] == 3.60
        assert result["max_allowed_hce_pct"] == 3.60
        assert result["result"] == "PASS"
        assert result["excess_contribution_cents"] == 0
        assert result["status"] == "COMPUTED"

    def test_aggregate_limit_branch_passes_at_boundary(self):
        """PRD §3.5: "The `max_allowed_hce_pct` is the larger of two quantities:
        one-and-a-quarter times the `nhce_avg_pct` (the 1.25 aggregate-limit
        factor), and the smaller of two times the `nhce_avg_pct` (the
        alternative-limit multiplier) and the `nhce_avg_pct` plus 2.00 (the
        alternative-limit spread) — with each factor rounded half-up to two
        decimal places."

        Census: NHCE ADRs 12.00/12.00 and HCE ADRs 15.00/15.00.
        max_allowed = max(15.00, min(24.00, 14.00)) = 15.00; 15.00 <= 15.00 passes.
        This exercises the 1.25x aggregate-limit branch of the nested max.

        Design: Difficulty/combinatorial_formula/adp_test_tiered_min_max
        """
        eng = create_engagement(prior_year_schedule_type="H")
        add_participant(eng["id"], "N-001", is_hce=False, deferral_amount_cy_cents=1_200_000)
        add_participant(eng["id"], "N-002", is_hce=False, deferral_amount_cy_cents=1_200_000)
        add_participant(eng["id"], "H-001", is_hce=True, deferral_amount_cy_cents=1_500_000)
        add_participant(eng["id"], "H-002", is_hce=True, deferral_amount_cy_cents=1_500_000)
        result = run_test(eng["id"], "ADP")
        assert result["nhce_avg_pct"] == 12.00
        assert result["hce_avg_pct"] == 15.00
        assert result["max_allowed_hce_pct"] == 15.00
        assert result["result"] == "PASS"
        assert result["excess_contribution_cents"] == 0


class TestCoverageRatio:

    def test_coverage_ratio_exactly_70_passes(self):
        """PRD §3.5: "The `coverage_ratio_pct` is the ratio of benefiting NHCEs to
        total NHCEs divided by the ratio of benefiting HCEs to total HCEs,
        multiplied by 100, and rounded half-up to two decimal places. The `result`
        is `PASS` when the rounded `coverage_ratio_pct` is greater than or equal
        to 70.00 — boundary-inclusive — and `FAIL` otherwise."

        Census: 10 NHCE (7 eligible) and 2 HCE (both eligible):
        (7/10) / (2/2) * 100 = 70.00.

        Design: Corner/calculations/coverage_ratio_exactly_70_passes
        """
        eng = create_engagement()
        add_census_group(eng["id"], 100_000, is_hce=False, count=7, ref_prefix="NE",
                         compensation_cy_cents=5_000_000)
        add_census_group(eng["id"], 0, is_hce=False, count=3, ref_prefix="NN",
                         compensation_cy_cents=5_000_000, is_eligible=False)
        add_census_group(eng["id"], 500_000, is_hce=True, count=2, ref_prefix="H",
                         compensation_cy_cents=20_000_000)
        result = run_test(eng["id"], "COVERAGE_410B")
        assert result["coverage_ratio_pct"] == 70.00
        assert result["result"] == "PASS"


class TestOptimisticConcurrency:

    def test_stale_engagement_version_rejected(self):
        """PRD §2.8: "When computing a new nondiscrimination or coverage test
        result (§3.4), the request must carry `expected_engagement_version`,
        holding the client's last-observed `version` of the parent `Engagement`.
        ... If the engagement's `version` has advanced since the client last read
        it, the request is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."

        Design: Corner/complexity_layers/stale_engagement_version_rejected
        """
        eng = create_engagement()
        stale_version = eng["version"]
        add_census_group(eng["id"], 300_000, is_hce=False, count=2, ref_prefix="N")
        add_census_group(eng["id"], 300_000, is_hce=True, count=1, ref_prefix="H")
        # First create consumes the captured version (creating a test result
        # increments the engagement's version).
        first = run_test(eng["id"], "ADP")
        assert first["status"] == "COMPUTED"
        resp = api_client.create_test_result(
            {
                "engagement_id": eng["id"],
                "test_type": "ACP",
                "expected_engagement_version": stale_version,
            },
            TPA,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION,
                       expected_status=412)


class TestFinalizeCascade:

    def _setup_failing_adp_with_ready_filing(self):
        eng = create_engagement(prior_year_schedule_type="I")
        add_participant(eng["id"], "N-001", is_hce=False, deferral_amount_cy_cents=300_000)
        add_participant(eng["id"], "N-002", is_hce=False, deferral_amount_cy_cents=300_000)
        add_participant(eng["id"], "H-001", is_hce=True, deferral_amount_cy_cents=502_000,
                        opening_balance_cents=500_000)
        add_participant(eng["id"], "H-002", is_hce=True, deferral_amount_cy_cents=500_000,
                        opening_balance_cents=500_000)
        # Compute the participant count so required_schedule_type is deterministically
        # "I" (4 < 100 under the standard rule, §3.2); PRD §3.8 pins the required
        # schedule set only through that computed field, so mark_schedules_complete
        # must not depend on the PRD-silent null case.
        recompute_count(eng["id"])
        filing = create_filing_ready_to_file(eng["id"], schedule_type="I")
        return eng, filing

    def test_fail_finalize_creates_finding_blocks_and_reverts_filing(self):
        """PRD §3.5: "When the finalized result is a `FAIL`, the finalization
        auto-creates an `AuditFinding` whose `source` is `TEST_FAILURE_AUTO`, whose
        `category` is `NONDISCRIMINATION_FAILURE`, whose `severity` is `HIGH`, and
        whose `status` is `OPEN`."
        PRD §3.5: "That new `OPEN` `HIGH` finding recomputes the engagement's
        `posture` to `BLOCKED` under §2.9, and a posture entering `BLOCKED` reverts
        any filing of the engagement in `READY_TO_FILE` back to
        `SCHEDULES_COMPLETE`."

        Census: NHCE ADRs 3.00/3.00 and HCE ADRs 5.02/5.00 (avg 5.01).
        max_allowed = max(3.75, min(6.00, 5.00)) = 5.00; 5.01 > 5.00 fails.

        Design: Difficulty/transitive_cascade/test_failure_finalize_cascade
        """
        eng, filing = self._setup_failing_adp_with_ready_filing()
        result = run_test(eng["id"], "ADP")
        assert result["result"] == "FAIL"
        assert result["nhce_avg_pct"] == 3.00
        assert result["hce_avg_pct"] == 5.01
        assert result["max_allowed_hce_pct"] == 5.00
        assert result["excess_contribution_cents"] == 2000
        assert result["correction_deadline"] == "2026-12-31"
        finalized = get_success_data(api_client.finalize_test_result(result["id"], AUD))
        assert finalized["status"] == "FINAL"
        finding = get_single_finding(eng["id"], category="NONDISCRIMINATION_FAILURE")
        assert finding["source"] == "TEST_FAILURE_AUTO"
        assert finding["severity"] == "HIGH"
        assert finding["status"] == "OPEN"
        eng_now = get_success_data(api_client.get_engagement(eng["id"], SPONSOR))
        assert eng_now["posture"] == "BLOCKED"
        filing_now = get_success_data(api_client.get_filing(filing["id"], SPONSOR))
        assert filing_now["status"] == "SCHEDULES_COMPLETE"

    def test_finalize_supersedes_prior_official_result(self):
        """PRD §3.5: "Finalization is the point at which one result supersedes
        another: any prior `FINAL` result for the same combination of
        `engagement_id` and `test_type` flips to `SUPERSEDED` with
        `is_current_official` set to false, while the newly finalized result
        becomes `is_current_official` true."

        Design: Difficulty/transitive_cascade/test_failure_finalize_cascade
        """
        eng = create_engagement(prior_year_schedule_type="I")
        add_census_group(eng["id"], 300_000, is_hce=False, count=2, ref_prefix="N")
        add_census_group(eng["id"], 300_000, is_hce=True, count=1, ref_prefix="H")
        first = run_test(eng["id"], "ADP")
        assert first["result"] == "PASS"
        first = get_success_data(api_client.finalize_test_result(first["id"], AUD))
        assert first["status"] == "FINAL"
        assert first["is_current_official"] is True
        second = run_test(eng["id"], "ADP")
        second = get_success_data(api_client.finalize_test_result(second["id"], AUD))
        assert second["status"] == "FINAL"
        assert second["is_current_official"] is True
        first_now = get_success_data(api_client.get_test_result(first["id"], SPONSOR))
        assert first_now["status"] == "SUPERSEDED"
        assert first_now["is_current_official"] is False
