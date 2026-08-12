"""Compensating invariants: retro compute/void and batch price/reopen."""
from test_helpers import (
    get_success_data,
    create_simulation_claim_payload,
    setup_contract_in_testing, setup_contract_with_retro_run,
    TEST_USERS,
)

ADMIN = TEST_USERS["plan_admin_headers"]
CA = TEST_USERS["configuration_analyst_headers"]
PI = TEST_USERS["payment_integrity_headers"]


class TestRetroComputeVoidConservesPaidLedger:
    def _setup(self, api):
        return setup_contract_with_retro_run(
            claim_specs=[
                {"claim_number": "CLM-1", "service_date": "2026-08-10",
                 "billed_cents": 15000, "paid_cents": 10000},
                {"claim_number": "CLM-2", "service_date": "2026-08-20",
                 "billed_cents": 20000, "paid_cents": 15000},
                {"claim_number": "CLM-3", "service_date": "2026-07-15",
                 "billed_cents": 15000, "paid_cents": 10000},
            ],
            v2_effective_date="2026-09-01", v2_retro_effective_date="2026-08-01",
            v2_pct_of_medicare_bps=12000,
        )

    def test_compute_produces_expected_totals_without_mutating_snapshots(self, api):
        """PRD §3.8: "Compute never mutates the snapshots themselves. After the
        sweep, the run's totals are recomputed over its non-`VOIDED` adjustments:
        `total_underpaid_cents` sums the positive deltas, `total_overpaid_cents`
        sums the magnitudes of the negative deltas, `net_delta_cents` is the
        underpaid total minus the overpaid total, and `adjustment_count` counts
        the rows."
        PRD §3.8: "candidates are those still `OPEN` whose `service_date` falls
        inside the run's half-open window, on or after `window_start_date` and
        strictly before `window_end_date`"

        Design: Difficulty/compensating_invariant/retro_compute_void_conserves_paid_ledger
        """
        artefacts = self._setup(api)
        run = artefacts["run"]
        computed = get_success_data(api.compute_retro_run(run["id"], PI))
        assert computed["total_underpaid_cents"] == 2000
        assert computed["total_overpaid_cents"] == 3000
        assert computed["net_delta_cents"] == -1000
        assert computed["adjustment_count"] == 2
        # CLM-3 (2026-07-15) is outside [2026-08-01, 2026-09-01): untouched.
        for pc in artefacts["paid_claims"]:
            after = get_success_data(api.get_paid_claim(pc["id"], ADMIN))
            assert after["snapshot_status"] == "OPEN"

    def test_void_compensates_and_restores_zero_totals(self, api):
        """PRD §3.8: "the run becomes `VOID`, every `PROPOSED` adjustment of the
        run cascades to `VOIDED`, all four run totals reset to zero, the
        snapshots remain `OPEN` (compute never touched them), and the paid
        ledger emerges unchanged end-to-end"

        Design: Difficulty/compensating_invariant/retro_compute_void_conserves_paid_ledger
        """
        artefacts = self._setup(api)
        run = artefacts["run"]
        get_success_data(api.compute_retro_run(run["id"], PI))
        voided = get_success_data(api.void_retro_run(run["id"], PI))
        assert voided["run_status"] == "VOID"
        assert voided["adjustment_count"] == 0
        assert voided["total_underpaid_cents"] == 0
        assert voided["total_overpaid_cents"] == 0
        assert voided["net_delta_cents"] == 0

        # Ledger sum unchanged end-to-end.
        claims = get_success_data(api.list_paid_claims(artefacts["contract"]["id"], ADMIN))
        assert sum(c["paid_cents"] for c in claims) == 35000
        for c in claims:
            assert c["snapshot_status"] == "OPEN"


class TestBatchPriceReopenConservesClaimCounts:
    def _setup_batch(self, api):
        artefacts = setup_contract_in_testing()
        batch_id = artefacts["batch"]["id"]
        for d in ("2026-07-15", "2026-07-16"):
            get_success_data(api.create_simulation_claim(
                batch_id, create_simulation_claim_payload(service_date=d), CA))
        get_success_data(api.create_simulation_claim(
            batch_id, create_simulation_claim_payload(
                service_date="2026-07-17", expected_allowed_cents=9999), CA))
        return batch_id

    def test_partition_holds_at_creation_and_after_pricing(self, api):
        """PRD §3.6: "A new batch begins with `batch_status` set to `OPEN` and
        every counter at zero: `total_claims`, `matched_claims`,
        `mismatched_claims`, `excluded_claims`, `pending_claims`, and
        `total_priced_cents`."
        PRD §3.6: "every claim added recomputes the batch's `total_claims` and
        `pending_claims`, each rising by one."
        PRD §3.6: "After the sweep the batch's counters — matched, mismatched,
        excluded, pending, and total priced — are recomputed in full."

        Design: Difficulty/compensating_invariant/batch_price_reopen_conserves_claim_counts
        """
        batch_id = self._setup_batch(api)
        before = get_success_data(api.get_simulation_batch(batch_id, ADMIN))
        assert before["total_claims"] == 3
        assert before["pending_claims"] == 3
        assert before["matched_claims"] == 0

        priced = get_success_data(api.price_batch(batch_id, CA))
        assert priced["total_claims"] == 3
        assert priced["matched_claims"] == 2
        assert priced["mismatched_claims"] == 1
        assert priced["pending_claims"] == 0
        assert (priced["matched_claims"] + priced["mismatched_claims"]
                + priced["excluded_claims"] + priced["pending_claims"]) == 3

    def test_reopen_restores_the_pre_price_partition(self, api):
        """PRD §3.6: "every claim whose outcome was `MATCH`, `MISMATCH`, or
        `EXCLUDED` reverts to `PENDING` with its `priced_allowed_cents` reset to
        null, the matched, mismatched, and excluded counters return to zero,
        `pending_claims` is restored to `total_claims`, and `total_priced_cents`
        returns to zero."

        Design: Difficulty/compensating_invariant/batch_price_reopen_conserves_claim_counts
        """
        batch_id = self._setup_batch(api)
        get_success_data(api.price_batch(batch_id, CA))
        get_success_data(api.score_batch(batch_id, CA))
        reopened = get_success_data(api.reopen_batch(batch_id, CA))
        assert reopened["total_claims"] == 3
        assert reopened["matched_claims"] == 0
        assert reopened["mismatched_claims"] == 0
        assert reopened["excluded_claims"] == 0
        assert reopened["pending_claims"] == 3
        assert reopened["total_priced_cents"] == 0
