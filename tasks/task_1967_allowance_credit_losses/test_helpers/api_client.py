"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- LossModel ---
    def create_loss_model(self, payload, headers):
        return self._request("POST", "/cecl/loss-models", payload, headers)

    def list_loss_models(self, headers, params=None):
        return self._request("GET", "/cecl/loss-models", headers=headers, params=params)

    def get_loss_model(self, model_id, headers):
        return self._request("GET", f"/cecl/loss-models/{model_id}", headers=headers)

    def activate_loss_model(self, model_id, headers):
        return self._request("POST", f"/cecl/loss-models/{model_id}/activate", {}, headers)

    def retire_loss_model(self, model_id, headers):
        return self._request("POST", f"/cecl/loss-models/{model_id}/retire", {}, headers)

    def refresh_loss_model(self, model_id, headers):
        return self._request("POST", f"/cecl/loss-models/{model_id}/refresh", {}, headers)

    def create_backtest(self, model_id, payload, headers):
        return self._request("POST", f"/cecl/loss-models/{model_id}/backtests", payload, headers)

    def list_backtest_results(self, model_id, headers, params=None):
        return self._request("GET", f"/cecl/loss-models/{model_id}/backtest-results", headers=headers, params=params)

    # --- PortfolioSegment ---
    def create_portfolio_segment(self, payload, headers):
        return self._request("POST", "/cecl/portfolio-segments", payload, headers)

    def get_portfolio_segment(self, segment_id, headers):
        return self._request("GET", f"/cecl/portfolio-segments/{segment_id}", headers=headers)

    def list_segment_loans(self, segment_id, headers, params=None):
        return self._request("GET", f"/cecl/portfolio-segments/{segment_id}/loans", headers=headers, params=params)

    def list_segment_qualitative_factors(self, segment_id, headers, params=None):
        return self._request("GET", f"/cecl/portfolio-segments/{segment_id}/qualitative-factors", headers=headers, params=params)

    # --- Loan ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/cecl/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/cecl/loans/{loan_id}", headers=headers)

    def charge_off_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/cecl/loans/{loan_id}/charge_off", payload, headers)

    def record_recovery(self, loan_id, payload, headers):
        return self._request("POST", f"/cecl/loans/{loan_id}/record_recovery", payload, headers)

    # --- EconomicScenario ---
    def create_economic_scenario(self, payload, headers):
        return self._request("POST", "/cecl/economic-scenarios", payload, headers)

    def get_economic_scenario(self, scenario_id, headers):
        return self._request("GET", f"/cecl/economic-scenarios/{scenario_id}", headers=headers)

    def archive_economic_scenario(self, scenario_id, headers):
        return self._request("POST", f"/cecl/economic-scenarios/{scenario_id}/archive", {}, headers)

    # --- QualitativeFactor ---
    def create_qualitative_factor(self, payload, headers):
        return self._request("POST", "/cecl/qualitative-factors", payload, headers)

    def get_qualitative_factor(self, factor_id, headers):
        return self._request("GET", f"/cecl/qualitative-factors/{factor_id}", headers=headers)

    def document_qualitative_factor(self, factor_id, payload, headers):
        return self._request("POST", f"/cecl/qualitative-factors/{factor_id}/document", payload, headers)

    def approve_qualitative_factor(self, factor_id, headers):
        return self._request("POST", f"/cecl/qualitative-factors/{factor_id}/approve", {}, headers)

    def retire_qualitative_factor(self, factor_id, headers):
        return self._request("POST", f"/cecl/qualitative-factors/{factor_id}/retire", {}, headers)

    # --- ModelRun ---
    def create_model_run(self, payload, headers):
        return self._request("POST", "/cecl/model-runs", payload, headers)

    def list_model_runs(self, headers, params=None):
        return self._request("GET", "/cecl/model-runs", headers=headers, params=params)

    def get_model_run(self, run_id, headers):
        return self._request("GET", f"/cecl/model-runs/{run_id}", headers=headers)

    def execute_model_run(self, run_id, headers):
        return self._request("POST", f"/cecl/model-runs/{run_id}/execute", {}, headers)

    def submit_model_run_for_review(self, run_id, headers):
        return self._request("POST", f"/cecl/model-runs/{run_id}/submit_for_review", {}, headers)

    def approve_model_run(self, run_id, headers):
        return self._request("POST", f"/cecl/model-runs/{run_id}/approve", {}, headers)

    def request_model_run_rework(self, run_id, payload, headers):
        return self._request("POST", f"/cecl/model-runs/{run_id}/request_rework", payload, headers)

    def finalize_model_run(self, run_id, payload, headers):
        return self._request("POST", f"/cecl/model-runs/{run_id}/finalize", payload, headers)

    def get_allowance_summary(self, run_id, headers):
        return self._request("GET", f"/cecl/model-runs/{run_id}/allowance-summary", headers=headers)

    # --- IndividualEvaluation ---
    def list_individual_evaluations(self, headers, params=None):
        return self._request("GET", "/cecl/individual-evaluations", headers=headers, params=params)

    def get_individual_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/cecl/individual-evaluations/{evaluation_id}", headers=headers)

    def patch_individual_evaluation(self, evaluation_id, payload, headers):
        return self._request("PATCH", f"/cecl/individual-evaluations/{evaluation_id}", payload, headers)

    def submit_individual_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/cecl/individual-evaluations/{evaluation_id}/submit", {}, headers)

    def review_individual_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/cecl/individual-evaluations/{evaluation_id}/review", {}, headers)

    def reopen_individual_evaluation(self, evaluation_id, payload, headers):
        return self._request("POST", f"/cecl/individual-evaluations/{evaluation_id}/reopen", payload, headers)

    # --- ManagementAdjustment ---
    def create_management_adjustment(self, run_id, payload, headers):
        return self._request("POST", f"/cecl/model-runs/{run_id}/management-adjustments", payload, headers)

    def list_management_adjustments(self, run_id, headers, params=None):
        return self._request("GET", f"/cecl/model-runs/{run_id}/management-adjustments", headers=headers, params=params)

    def approve_management_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/cecl/management-adjustments/{adjustment_id}/approve", {}, headers)

    def reject_management_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/cecl/management-adjustments/{adjustment_id}/reject", {}, headers)

    # --- DisclosureReport ---
    def list_disclosure_reports(self, run_id, headers, params=None):
        return self._request("GET", f"/cecl/model-runs/{run_id}/disclosure-reports", headers=headers, params=params)

    def get_disclosure_report(self, report_id, headers):
        return self._request("GET", f"/cecl/disclosure-reports/{report_id}", headers=headers)

    def submit_disclosure_for_audit(self, report_id, headers):
        return self._request("POST", f"/cecl/disclosure-reports/{report_id}/submit_for_audit", {}, headers)

    def sign_off_disclosure_report(self, report_id, payload, headers):
        return self._request("POST", f"/cecl/disclosure-reports/{report_id}/sign_off", payload, headers)

    def return_disclosure_for_revision(self, report_id, payload, headers):
        return self._request("POST", f"/cecl/disclosure-reports/{report_id}/return_for_revision", payload, headers)


api_client = ApiClient()
