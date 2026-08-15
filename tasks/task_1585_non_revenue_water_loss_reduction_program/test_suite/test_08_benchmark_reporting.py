"""Benchmark reporting: submission gates, snapshot aggregation, district
freeze/compensation, resubmission, and report-level OCC (PRD §3.9, §2.6)."""
import pytest

from test_helpers import (
    ApiErrorId,
    PINNED_BALANCE,
    TEST_DEFAULTS,
    assert_benchmark_report,
    create_benchmark_report,
    create_dma,
    create_submitted_balance,
    create_water_balance_period,
    finalize_water_balance_period,
    get_dma,
    make_regulator_liaison_headers,
    make_utility_analyst_headers,
    setup_dma_with_finalized_balance,
    submit_benchmark_report,
    submit_water_balance_period,
    validate_error,
    validate_success,
)

UA = TEST_DEFAULTS["UTILITY_ANALYST"]
UA2 = TEST_DEFAULTS["UTILITY_ANALYST_ALT"]
RL = TEST_DEFAULTS["REGULATOR_LIAISON"]


def _setup_dma_with_finalized_plus_submitted(code):
    """DMA holding one FINALIZED balance (Jan-Mar) and one SUBMITTED balance
    (Apr-Jun); the DMA stands at RESTRICTED before any report is submitted."""
    dma, finalized = setup_dma_with_finalized_balance(code=code)
    second = create_water_balance_period(
        dma["id"],
        creator=UA,
        period_start="2026-04-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
        system_input_volume_m3=900000,
        billed_authorized_m3=700000,
        unbilled_authorized_m3=30000,
        unauthorized_consumption_m3=12000,
        metering_inaccuracy_m3=20000,
    )
    submit_water_balance_period(second["id"], user=UA)
    dma = get_dma(dma["id"])
    assert dma["posture"] == "RESTRICTED"
    return dma, finalized, second


class TestSubmitFreezesDmaAndBlocksFinalize:
    def test_submit_computes_snapshot_and_freezes_dma(self, api):
        """PRD §3.9: "Submission then freezes the districts: every listed DMA's
        posture is recomputed to `FROZEN`, whether it stood at `OPEN` or
        `RESTRICTED`." and "The `utility_nrw_pct` is volume-weighted, not an
        arithmetic mean of percentages: the sum of the selected balances'
        `nrw_volume_m3` divided by the sum of their `system_input_volume_m3`,
        multiplied by 100."

        Design: Difficulty/transitive_cascade/benchmark_submit_freezes_dma_blocks_finalize
        """
        dma, finalized, second = _setup_dma_with_finalized_plus_submitted("DMA-TC1")
        report = create_benchmark_report([dma["id"]])
        submitted = submit_benchmark_report(report["id"])
        assert_benchmark_report(submitted)
        assert submitted["status"] == "SUBMITTED"
        # Single qualifying balance: 280000 / 1000000 * 100 = 28.0
        assert submitted["utility_nrw_pct"] == pytest.approx(28.0, abs=0.01)

        assert get_dma(dma["id"])["posture"] == "FROZEN"

    def test_finalize_on_frozen_dma_rejected(self, api):
        """PRD §2.6: "While a DMA is `FROZEN`, the following eight operations
        are rejected with `ERR_DMA_FROZEN` (HTTP 409): creating a water balance
        period for the DMA, submitting a water balance period, finalizing a
        water balance period, creating a leak survey in the DMA, starting field
        work on a leak survey, approving a pressure project, creating an
        intervention proposal for the DMA, and submitting an intervention
        proposal."

        Design: Difficulty/transitive_cascade/benchmark_submit_freezes_dma_blocks_finalize
        """
        dma, finalized, second = _setup_dma_with_finalized_plus_submitted(
            "DMA-TC1B"
        )
        report = create_benchmark_report([dma["id"]])
        submit_benchmark_report(report["id"])

        fin_res = api.finalize_water_balance_period(
            second["id"], make_utility_analyst_headers(UA2)
        )
        validate_error(fin_res, ApiErrorId.ERR_DMA_FROZEN, expected_status=409)

        reread = validate_success(
            api.get_water_balance_period(
                second["id"], make_utility_analyst_headers(UA)
            ),
            200,
        )
        assert reread["status"] == "SUBMITTED"
        assert get_dma(dma["id"])["posture"] == "FROZEN"


class TestFrozenGatePrecedence:
    def test_finalize_on_frozen_dma_reports_frozen_error(self, api):
        """PRD §2.6: "While a DMA is `FROZEN`, the following eight operations
        are rejected with `ERR_DMA_FROZEN` (HTTP 409): creating a water balance
        period for the DMA, submitting a water balance period, finalizing a
        water balance period, creating a leak survey in the DMA, starting field
        work on a leak survey, approving a pressure project, creating an
        intervention proposal for the DMA, and submitting an intervention
        proposal."
        PRD §2.7: "the server evaluates them in a fixed priority order and
        reports only the first failure encountered."

        Design: Difficulty/priority_pair_validation_conflict/frozen_dma_state_error_beats_missing_prerequisite
        """
        dma, finalized, second = _setup_dma_with_finalized_plus_submitted("DMA-PP1")
        report = create_benchmark_report([dma["id"]])
        submit_benchmark_report(report["id"])
        assert get_dma(dma["id"])["posture"] == "FROZEN"

        res = api.finalize_water_balance_period(
            second["id"], make_utility_analyst_headers(UA2)
        )
        validate_error(res, ApiErrorId.ERR_DMA_FROZEN, expected_status=409)

    def test_create_balance_on_frozen_dma_also_reports_frozen_error(self, api):
        """PRD §2.6: "While a DMA is `FROZEN`, the following eight operations
        are rejected with `ERR_DMA_FROZEN` (HTTP 409): creating a water balance
        period for the DMA, submitting a water balance period, finalizing a
        water balance period, creating a leak survey in the DMA, starting field
        work on a leak survey, approving a pressure project, creating an
        intervention proposal for the DMA, and submitting an intervention
        proposal."

        Design: Difficulty/priority_pair_validation_conflict/frozen_dma_state_error_beats_missing_prerequisite
        """
        dma, finalized, second = _setup_dma_with_finalized_plus_submitted(
            "DMA-PP1B"
        )
        report = create_benchmark_report([dma["id"]])
        submit_benchmark_report(report["id"])

        fresh = get_dma(dma["id"])
        res = api.create_water_balance_period(
            {
                "dma_id": dma["id"],
                "period_start": "2026-07-01T00:00:00Z",
                "period_end": "2026-10-01T00:00:00Z",
                "system_input_volume_m3": 800000,
                "billed_authorized_m3": 600000,
                "unbilled_authorized_m3": 25000,
                "unauthorized_consumption_m3": 10000,
                "metering_inaccuracy_m3": 18000,
                "expected_dma_version": fresh["version"],
            },
            make_utility_analyst_headers(UA),
        )
        validate_error(res, ApiErrorId.ERR_DMA_FROZEN, expected_status=409)


class TestSubmitGatedOnFinalizedBalances:
    def test_submit_without_finalized_balance_rejected(self, api):
        """PRD §3.9: "The `dma_ids` array must be non-empty, and every listed
        DMA must have a qualifying balance: a finalized, non-superseded water
        balance period whose half-open window lies fully inside the reporting
        window — a DMA without one blocks submission with
        `ERR_MISSING_PREREQUISITE`."

        Design: Difficulty/cross_entity_state_dependency/benchmark_submit_gated_on_finalized_balances
        """
        dma = create_dma(code="DMA-CE2", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        period = create_submitted_balance(dma["id"], creator=UA)
        assert period["status"] == "SUBMITTED"
        report = create_benchmark_report([dma["id"]])

        res = api.submit_benchmark_report(
            report["id"], {"expected_report_version": report["version"]},
            make_regulator_liaison_headers(RL),
        )
        validate_error(res, ApiErrorId.ERR_MISSING_PREREQUISITE,
                       expected_status=422)

        reread = validate_success(
            api.get_benchmark_report(
                report["id"], make_regulator_liaison_headers(RL)
            ),
            200,
        )
        assert reread["status"] == "DRAFT"
        # The failed submission must not freeze the district.
        assert get_dma(dma["id"])["posture"] == "RESTRICTED"

    def test_submit_succeeds_once_balance_finalized(self, api):
        """PRD §3.9: "every listed DMA must have a qualifying balance: a
        finalized, non-superseded water balance period whose half-open window
        lies fully inside the reporting window" and "Submission then freezes the
        districts: every listed DMA's posture is recomputed to `FROZEN`, whether
        it stood at `OPEN` or `RESTRICTED`."

        Design: Difficulty/cross_entity_state_dependency/benchmark_submit_gated_on_finalized_balances
        """
        dma = create_dma(code="DMA-CE2B", connection_count=5000,
                         mains_length_km=120.0, target_nrw_pct=20.0)
        period = create_submitted_balance(dma["id"], creator=UA)
        finalize_water_balance_period(period["id"], user=UA2)
        report = create_benchmark_report([dma["id"]])

        submitted = submit_benchmark_report(report["id"])
        assert submitted["status"] == "SUBMITTED"
        assert get_dma(dma["id"])["posture"] == "FROZEN"


class TestReturnCompensation:
    def test_submit_freezes_then_return_restores_open(self, api):
        """PRD §2.6: "It becomes `FROZEN` when a benchmark report whose
        `dma_ids` contains that DMA enters `SUBMITTED` or `ACCEPTED`, and it
        returns from `FROZEN` to `OPEN` only when the covering report enters
        `RETURNED` and no other gating child state holds (no balance period in
        `SUBMITTED`, no pressure project `ACTIVE`)."
        PRD §3.9: "Return moves it from `SUBMITTED` to `RETURNED` and
        compensates: every listed DMA's posture is recomputed, releasing
        `FROZEN` districts back to `OPEN` wherever no other gating child state
        holds."

        Design: Difficulty/compensating_invariant/benchmark_return_restores_dma_posture_conservation
        """
        dma, _ = setup_dma_with_finalized_balance(code="DMA-CI1")
        assert get_dma(dma["id"])["posture"] == "OPEN"

        report = create_benchmark_report([dma["id"]])
        submit_benchmark_report(report["id"])
        assert get_dma(dma["id"])["posture"] == "FROZEN"

        returned = validate_success(
            api.return_benchmark_report(
                report["id"], make_regulator_liaison_headers(RL)
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert get_dma(dma["id"])["posture"] == "OPEN"

    def test_returned_report_resubmits_and_refreezes(self, api):
        """PRD §3.9: "A returned report may be corrected and resubmitted —
        `RETURNED` back to `SUBMITTED` — under the same preconditions and OCC
        guard as the original submission; resubmission recomputes and re-freezes
        the snapshot and re-applies the district freeze."

        Design: Difficulty/compensating_invariant/benchmark_return_restores_dma_posture_conservation
        """
        dma, _ = setup_dma_with_finalized_balance(code="DMA-CI1B")
        report = create_benchmark_report([dma["id"]])
        submit_benchmark_report(report["id"])

        returned = validate_success(
            api.return_benchmark_report(
                report["id"], make_regulator_liaison_headers(RL)
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert get_dma(dma["id"])["posture"] == "OPEN"

        resubmitted = submit_benchmark_report(report["id"])
        assert resubmitted["status"] == "SUBMITTED"
        assert get_dma(dma["id"])["posture"] == "FROZEN"


class TestVolumeWeightedAggregation:
    def test_utility_figures_and_breakdown_order(self, api):
        """PRD §3.9: "The `utility_nrw_pct` is volume-weighted, not an
        arithmetic mean of percentages: the sum of the selected balances'
        `nrw_volume_m3` divided by the sum of their `system_input_volume_m3`,
        multiplied by 100. The `utility_ili` is likewise aggregate-first: the
        sum of the selected balances' annualized real losses divided by the sum
        of their unavoidable annual losses, taken over exactly those DMAs whose
        `ili` is non-null." and "the rows of `per_dma_breakdown` are ordered
        deterministically by the DMA `code` in ascending lexicographic order,
        which admits no ties because codes are unique."

        Design: Corner/calculations/benchmark_volume_weighted_aggregation
        """
        dma_a, _ = setup_dma_with_finalized_balance(code="DMA-BW-A")
        dma_b, _ = setup_dma_with_finalized_balance(
            code="DMA-BW-B",
            dma_overrides={"connection_count": 2000, "mains_length_km": 60.0},
            period_overrides={
                "system_input_volume_m3": 500000,
                "billed_authorized_m3": 380000,
                "unbilled_authorized_m3": 20000,
                "unauthorized_consumption_m3": 8000,
                "metering_inaccuracy_m3": 12000,
            },
        )
        report = create_benchmark_report([dma_a["id"], dma_b["id"]])
        submitted = submit_benchmark_report(report["id"])

        assert submitted["status"] == "SUBMITTED"
        # (280000 + 120000) / (1000000 + 500000) * 100 = 26.67 (volume-weighted)
        assert submitted["utility_nrw_pct"] == pytest.approx(26.67, abs=0.01)
        # sum(carl)/sum(uarl) = (811111.11 + 324444.44) / (33250.04 + 13522.52)
        #                     = 24.28
        assert submitted["utility_ili"] == pytest.approx(24.28, abs=0.01)

        breakdown = submitted["per_dma_breakdown"]
        assert len(breakdown) == 2
        assert breakdown[0]["dma_code"] == "DMA-BW-A"
        assert breakdown[0]["dma_id"] == dma_a["id"]
        assert breakdown[0]["nrw_pct"] == pytest.approx(
            PINNED_BALANCE["NRW_PCT_AUDITED"], abs=0.01
        )
        assert breakdown[1]["dma_code"] == "DMA-BW-B"
        assert breakdown[1]["nrw_pct"] == pytest.approx(23.5, abs=0.01)


class TestReportOcc:
    def test_stale_report_version_rejected_fresh_retry_succeeds(self, api):
        """PRD §2.10: "Submitting a benchmark report requires the request to
        carry `expected_report_version`, a non-optional field holding the
        report's own `version` as the client last observed it. If the report's
        `version` has advanced since — for instance because another writer
        returned the report and refreshed the DMA snapshot set — the submission
        is rejected with `ERR_STALE_VERSION` (HTTP 412), since the client's view
        of which balances feed the aggregation is stale."

        Design: Corner/cross_cutting_layers/occ_stale_report_version_rejected
        """
        dma, _ = setup_dma_with_finalized_balance(code="DMA-OCC2")
        report = create_benchmark_report([dma["id"]])
        stale_version = report["version"]

        submit_benchmark_report(report["id"], expected_report_version=stale_version)

        returned = validate_success(
            api.return_benchmark_report(
                report["id"], make_regulator_liaison_headers(RL)
            ),
            200,
        )
        assert returned["status"] == "RETURNED"
        assert returned["version"] > stale_version

        stale_res = api.submit_benchmark_report(
            report["id"], {"expected_report_version": stale_version},
            make_regulator_liaison_headers(RL),
        )
        validate_error(stale_res, ApiErrorId.ERR_STALE_VERSION,
                       expected_status=412)

        fresh = validate_success(
            api.get_benchmark_report(
                report["id"], make_regulator_liaison_headers(RL)
            ),
            200,
        )
        resubmitted = submit_benchmark_report(
            report["id"], expected_report_version=fresh["version"]
        )
        assert resubmitted["status"] == "SUBMITTED"
