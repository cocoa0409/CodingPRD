"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Agreement periods ---
    def create_agreement_period(self, payload, headers):
        return self._request("POST", "/aco/agreement-periods", payload, headers)

    def get_agreement_period(self, period_id, headers):
        return self._request("GET", f"/aco/agreement-periods/{period_id}", headers=headers)

    def open_agreement_period(self, period_id, headers):
        return self._request("POST", f"/aco/agreement-periods/{period_id}/open", {}, headers)

    def lock_assignment(self, period_id, headers):
        return self._request(
            "POST", f"/aco/agreement-periods/{period_id}/lock-assignment", {}, headers
        )

    def get_expenditure_summary(self, period_id, headers):
        return self._request(
            "GET", f"/aco/agreement-periods/{period_id}/expenditure-summary", headers=headers
        )

    # --- Participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/aco/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/aco/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/aco/participants", headers=headers, params=params)

    # --- Beneficiaries and data-sharing elections ---
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/aco/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/aco/beneficiaries/{beneficiary_id}", headers=headers)

    def create_data_sharing_election(self, beneficiary_id, payload, headers):
        return self._request(
            "POST", f"/aco/beneficiaries/{beneficiary_id}/data-sharing-elections", payload, headers
        )

    def list_data_sharing_elections(self, beneficiary_id, headers):
        return self._request(
            "GET", f"/aco/beneficiaries/{beneficiary_id}/data-sharing-elections", headers=headers
        )

    # --- Alignment runs ---
    def create_alignment_run(self, period_id, payload, headers):
        return self._request(
            "POST", f"/aco/agreement-periods/{period_id}/alignment-runs", payload, headers
        )

    def get_alignment_run(self, run_id, headers):
        return self._request("GET", f"/aco/alignment-runs/{run_id}", headers=headers)

    def list_alignment_runs(self, headers, params=None):
        return self._request("GET", "/aco/alignment-runs", headers=headers, params=params)

    # --- Attribution records ---
    def get_attribution_record(self, record_id, headers):
        return self._request("GET", f"/aco/attribution-records/{record_id}", headers=headers)

    def list_attribution_records(self, headers, params=None):
        return self._request("GET", "/aco/attribution-records", headers=headers, params=params)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/aco/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/aco/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/aco/claims", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/aco/claims/{claim_id}/adjudicate", {}, headers)

    def void_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/aco/claims/{claim_id}/void", payload, headers)

    # --- Benchmarks ---
    def create_benchmark(self, period_id, payload, headers):
        return self._request(
            "POST", f"/aco/agreement-periods/{period_id}/benchmarks", payload, headers
        )

    def get_benchmark(self, benchmark_id, headers):
        return self._request("GET", f"/aco/benchmarks/{benchmark_id}", headers=headers)

    def list_benchmarks(self, headers, params=None):
        return self._request("GET", "/aco/benchmarks", headers=headers, params=params)

    # --- Quality scores ---
    def create_quality_score(self, payload, headers):
        return self._request("POST", "/aco/quality-scores", payload, headers)

    def get_quality_score(self, score_id, headers):
        return self._request("GET", f"/aco/quality-scores/{score_id}", headers=headers)

    def list_quality_scores(self, headers, params=None):
        return self._request("GET", "/aco/quality-scores", headers=headers, params=params)

    def review_quality_score(self, score_id, payload, headers):
        return self._request("POST", f"/aco/quality-scores/{score_id}/review", payload, headers)

    def resubmit_quality_score(self, score_id, payload, headers):
        return self._request("POST", f"/aco/quality-scores/{score_id}/resubmit", payload, headers)

    # --- Settlements ---
    def create_settlement(self, period_id, payload, headers):
        return self._request(
            "POST", f"/aco/agreement-periods/{period_id}/settlements", payload, headers
        )

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/aco/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/aco/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/aco/settlements/{settlement_id}/finalize", {}, headers)

    def reopen_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/aco/settlements/{settlement_id}/reopen", payload, headers)

    def create_distribution_run(self, settlement_id, headers):
        return self._request(
            "POST", f"/aco/settlements/{settlement_id}/distribution-runs", {}, headers
        )

    # --- Distribution lines ---
    def get_distribution_line(self, line_id, headers):
        return self._request("GET", f"/aco/distribution-lines/{line_id}", headers=headers)

    def list_distribution_lines(self, headers, params=None):
        return self._request("GET", "/aco/distribution-lines", headers=headers, params=params)

    def approve_distribution_line(self, line_id, headers):
        return self._request("POST", f"/aco/distribution-lines/{line_id}/approve", {}, headers)

    def pay_distribution_line(self, line_id, headers):
        return self._request("POST", f"/aco/distribution-lines/{line_id}/pay", {}, headers)

    # --- High-cost reviews ---
    def get_high_cost_review(self, review_id, headers):
        return self._request("GET", f"/aco/high-cost-reviews/{review_id}", headers=headers)

    def list_high_cost_reviews(self, headers, params=None):
        return self._request("GET", "/aco/high-cost-reviews", headers=headers, params=params)

    def determine_high_cost_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/aco/high-cost-reviews/{review_id}/determine", payload, headers
        )

    # --- Appeals ---
    def create_appeal(self, payload, headers):
        return self._request("POST", "/aco/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/aco/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/aco/appeals", headers=headers, params=params)

    def create_rebuttal(self, appeal_id, payload, headers):
        return self._request("POST", f"/aco/appeals/{appeal_id}/rebuttals", payload, headers)

    def resume_review(self, appeal_id, headers):
        return self._request("POST", f"/aco/appeals/{appeal_id}/resume-review", {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/aco/appeals/{appeal_id}/decide", payload, headers)

    # --- Reconciliation adjustments ---
    def create_reconciliation_adjustment(self, settlement_id, payload, headers):
        return self._request(
            "POST",
            f"/aco/settlements/{settlement_id}/reconciliation-adjustments",
            payload,
            headers,
        )

    def get_reconciliation_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/aco/reconciliation-adjustments/{adjustment_id}", headers=headers
        )

    def list_reconciliation_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/aco/reconciliation-adjustments", headers=headers, params=params
        )

    def reverse_reconciliation_adjustment(self, adjustment_id, headers):
        return self._request(
            "POST", f"/aco/reconciliation-adjustments/{adjustment_id}/reverse", {}, headers
        )

    # --- Logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/aco/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
