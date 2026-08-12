"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint methods for the Fair Lending Analysis API."""

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Markets ---
    def create_market(self, payload, headers):
        return self._request("POST", "/fair-lending/markets", payload, headers)

    def list_markets(self, headers, params=None):
        return self._request("GET", "/fair-lending/markets", headers=headers, params=params)

    def get_market(self, market_id, headers):
        return self._request("GET", f"/fair-lending/markets/{market_id}", headers=headers)

    def get_penetration_report(self, market_id, params, headers):
        return self._request(
            "GET", f"/fair-lending/markets/{market_id}/penetration-report",
            headers=headers, params=params,
        )

    # --- Branches ---
    def create_branch(self, payload, headers):
        return self._request("POST", "/fair-lending/branches", payload, headers)

    def list_branches(self, headers, params=None):
        return self._request("GET", "/fair-lending/branches", headers=headers, params=params)

    def get_branch(self, branch_id, headers):
        return self._request("GET", f"/fair-lending/branches/{branch_id}", headers=headers)

    def close_branch(self, branch_id, headers):
        return self._request("POST", f"/fair-lending/branches/{branch_id}/close", {}, headers)

    # --- Loan officers ---
    def create_loan_officer(self, payload, headers):
        return self._request("POST", "/fair-lending/loan-officers", payload, headers)

    def list_loan_officers(self, headers, params=None):
        return self._request("GET", "/fair-lending/loan-officers", headers=headers, params=params)

    def get_loan_officer(self, officer_id, headers):
        return self._request("GET", f"/fair-lending/loan-officers/{officer_id}", headers=headers)

    def get_risk_scorecard(self, officer_id, headers):
        return self._request(
            "GET", f"/fair-lending/loan-officers/{officer_id}/risk-scorecard",
            headers=headers,
        )

    def suspend_loan_officer(self, officer_id, headers):
        return self._request("POST", f"/fair-lending/loan-officers/{officer_id}/suspend", {}, headers)

    def reinstate_loan_officer(self, officer_id, headers):
        return self._request("POST", f"/fair-lending/loan-officers/{officer_id}/reinstate", {}, headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/fair-lending/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/fair-lending/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/fair-lending/applications/{application_id}", headers=headers)

    def validate_application(self, application_id, headers):
        return self._request(
            "POST", f"/fair-lending/applications/{application_id}/validate", {}, headers
        )

    def correct_application(self, application_id, payload, headers):
        return self._request("PUT", f"/fair-lending/applications/{application_id}", payload, headers)

    def exclude_application(self, application_id, headers):
        return self._request(
            "POST", f"/fair-lending/applications/{application_id}/exclude", {}, headers
        )

    # --- Pricing exceptions ---
    def create_pricing_exception(self, payload, headers):
        return self._request("POST", "/fair-lending/pricing-exceptions", payload, headers)

    def list_pricing_exceptions(self, headers, params=None):
        return self._request("GET", "/fair-lending/pricing-exceptions", headers=headers, params=params)

    def get_pricing_exception(self, exception_id, headers):
        return self._request(
            "GET", f"/fair-lending/pricing-exceptions/{exception_id}", headers=headers
        )

    def approve_pricing_exception(self, exception_id, headers):
        return self._request(
            "POST", f"/fair-lending/pricing-exceptions/{exception_id}/approve", {}, headers
        )

    def deny_pricing_exception(self, exception_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/pricing-exceptions/{exception_id}/deny", payload, headers
        )

    def rescind_pricing_exception(self, exception_id, headers):
        return self._request(
            "POST", f"/fair-lending/pricing-exceptions/{exception_id}/rescind", {}, headers
        )

    def withdraw_pricing_exception(self, exception_id, headers):
        return self._request(
            "POST", f"/fair-lending/pricing-exceptions/{exception_id}/withdraw", {}, headers
        )

    # --- Underwriting overrides ---
    def create_underwriting_override(self, payload, headers):
        return self._request("POST", "/fair-lending/underwriting-overrides", payload, headers)

    def list_underwriting_overrides(self, headers, params=None):
        return self._request(
            "GET", "/fair-lending/underwriting-overrides", headers=headers, params=params
        )

    def get_underwriting_override(self, override_id, headers):
        return self._request(
            "GET", f"/fair-lending/underwriting-overrides/{override_id}", headers=headers
        )

    def confirm_underwriting_override(self, override_id, headers):
        return self._request(
            "POST", f"/fair-lending/underwriting-overrides/{override_id}/confirm", {}, headers
        )

    def reverse_underwriting_override(self, override_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/underwriting-overrides/{override_id}/reverse", payload, headers
        )

    # --- Peer benchmarks ---
    def create_peer_benchmark(self, payload, headers):
        return self._request("POST", "/fair-lending/peer-benchmarks", payload, headers)

    def list_peer_benchmarks(self, headers, params=None):
        return self._request("GET", "/fair-lending/peer-benchmarks", headers=headers, params=params)

    def get_peer_benchmark(self, benchmark_id, headers):
        return self._request("GET", f"/fair-lending/peer-benchmarks/{benchmark_id}", headers=headers)

    # --- Analysis runs ---
    def create_analysis_run(self, payload, headers):
        return self._request("POST", "/fair-lending/analysis-runs", payload, headers)

    def list_analysis_runs(self, headers, params=None):
        return self._request("GET", "/fair-lending/analysis-runs", headers=headers, params=params)

    def get_analysis_run(self, run_id, headers):
        return self._request("GET", f"/fair-lending/analysis-runs/{run_id}", headers=headers)

    def lock_analysis_run(self, run_id, headers):
        return self._request("POST", f"/fair-lending/analysis-runs/{run_id}/lock", {}, headers)

    def unlock_analysis_run(self, run_id, headers):
        return self._request("POST", f"/fair-lending/analysis-runs/{run_id}/unlock", {}, headers)

    def compute_analysis_run(self, run_id, headers):
        return self._request("POST", f"/fair-lending/analysis-runs/{run_id}/compute", {}, headers)

    def finalize_analysis_run(self, run_id, headers):
        return self._request("POST", f"/fair-lending/analysis-runs/{run_id}/finalize", {}, headers)

    def archive_analysis_run(self, run_id, headers):
        return self._request("POST", f"/fair-lending/analysis-runs/{run_id}/archive", {}, headers)

    # --- Disparity findings ---
    def create_finding(self, payload, headers):
        return self._request("POST", "/fair-lending/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/fair-lending/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/fair-lending/findings/{finding_id}", headers=headers)

    def begin_review_finding(self, finding_id, headers):
        return self._request(
            "POST", f"/fair-lending/findings/{finding_id}/begin-review", {}, headers
        )

    def substantiate_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/findings/{finding_id}/substantiate", payload, headers
        )

    def refute_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/findings/{finding_id}/refute", payload, headers
        )

    def reopen_finding(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/findings/{finding_id}/reopen", payload, headers
        )

    # --- Matched-pair reviews ---
    def create_matched_pair_review(self, payload, headers):
        return self._request("POST", "/fair-lending/matched-pair-reviews", payload, headers)

    def list_matched_pair_reviews(self, headers, params=None):
        return self._request(
            "GET", "/fair-lending/matched-pair-reviews", headers=headers, params=params
        )

    def get_matched_pair_review(self, review_id, headers):
        return self._request(
            "GET", f"/fair-lending/matched-pair-reviews/{review_id}", headers=headers
        )

    def submit_initial_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/matched-pair-reviews/{review_id}/submit-initial",
            payload, headers,
        )

    def confirm_matched_pair_review(self, review_id, headers):
        return self._request(
            "POST", f"/fair-lending/matched-pair-reviews/{review_id}/confirm", {}, headers
        )

    def dispute_matched_pair_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/matched-pair-reviews/{review_id}/dispute", payload, headers
        )

    # --- Corrective action plans ---
    def create_corrective_action_plan(self, payload, headers):
        return self._request("POST", "/fair-lending/corrective-action-plans", payload, headers)

    def list_corrective_action_plans(self, headers, params=None):
        return self._request(
            "GET", "/fair-lending/corrective-action-plans", headers=headers, params=params
        )

    def get_corrective_action_plan(self, cap_id, headers):
        return self._request(
            "GET", f"/fair-lending/corrective-action-plans/{cap_id}", headers=headers
        )

    def submit_corrective_action_plan(self, cap_id, headers):
        return self._request(
            "POST", f"/fair-lending/corrective-action-plans/{cap_id}/submit", {}, headers
        )

    def approve_corrective_action_plan(self, cap_id, headers):
        return self._request(
            "POST", f"/fair-lending/corrective-action-plans/{cap_id}/approve", {}, headers
        )

    def return_corrective_action_plan(self, cap_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/corrective-action-plans/{cap_id}/return", payload, headers
        )

    def revise_corrective_action_plan(self, cap_id, headers):
        return self._request(
            "POST", f"/fair-lending/corrective-action-plans/{cap_id}/revise", {}, headers
        )

    def extend_corrective_action_plan(self, cap_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/corrective-action-plans/{cap_id}/extend", payload, headers
        )

    def cancel_corrective_action_plan(self, cap_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/corrective-action-plans/{cap_id}/cancel", payload, headers
        )

    # --- Remediation payments ---
    def create_remediation_payment(self, payload, headers):
        return self._request("POST", "/fair-lending/remediation-payments", payload, headers)

    def list_remediation_payments(self, headers, params=None):
        return self._request(
            "GET", "/fair-lending/remediation-payments", headers=headers, params=params
        )

    def get_remediation_payment(self, payment_id, headers):
        return self._request(
            "GET", f"/fair-lending/remediation-payments/{payment_id}", headers=headers
        )

    def disburse_remediation_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/fair-lending/remediation-payments/{payment_id}/disburse", {}, headers
        )

    def void_remediation_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/remediation-payments/{payment_id}/void", payload, headers
        )

    def mark_returned_remediation_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/remediation-payments/{payment_id}/mark-returned",
            payload, headers,
        )

    # --- Self tests ---
    def create_self_test(self, payload, headers):
        return self._request("POST", "/fair-lending/self-tests", payload, headers)

    def list_self_tests(self, headers, params=None):
        return self._request("GET", "/fair-lending/self-tests", headers=headers, params=params)

    def get_self_test(self, self_test_id, headers):
        return self._request("GET", f"/fair-lending/self-tests/{self_test_id}", headers=headers)

    def designate_self_test_privileged(self, self_test_id, headers):
        return self._request(
            "POST", f"/fair-lending/self-tests/{self_test_id}/designate-privileged", {}, headers
        )

    def close_self_test(self, self_test_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/self-tests/{self_test_id}/close", payload, headers
        )

    def mark_self_test_remediated(self, self_test_id, headers):
        return self._request(
            "POST", f"/fair-lending/self-tests/{self_test_id}/mark-remediated", {}, headers
        )

    # --- Board reports ---
    def create_board_report(self, payload, headers):
        return self._request("POST", "/fair-lending/board-reports", payload, headers)

    def list_board_reports(self, headers, params=None):
        return self._request("GET", "/fair-lending/board-reports", headers=headers, params=params)

    def get_board_report(self, report_id, headers):
        return self._request("GET", f"/fair-lending/board-reports/{report_id}", headers=headers)

    def refresh_board_report(self, report_id, headers):
        return self._request(
            "POST", f"/fair-lending/board-reports/{report_id}/refresh", {}, headers
        )

    def submit_board_report(self, report_id, headers):
        return self._request(
            "POST", f"/fair-lending/board-reports/{report_id}/submit", {}, headers
        )

    def return_board_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/fair-lending/board-reports/{report_id}/return", payload, headers
        )

    def revise_board_report(self, report_id, headers):
        return self._request(
            "POST", f"/fair-lending/board-reports/{report_id}/revise", {}, headers
        )

    def approve_board_report(self, report_id, headers):
        return self._request(
            "POST", f"/fair-lending/board-reports/{report_id}/approve", {}, headers
        )

    def publish_board_report(self, report_id, headers):
        return self._request(
            "POST", f"/fair-lending/board-reports/{report_id}/publish", {}, headers
        )

    # --- Monitoring checkpoint ---
    def run_monitoring_cycle(self, headers):
        return self._request("POST", "/fair-lending/monitoring/run-cycle", {}, headers)


api_client = ApiClient()
