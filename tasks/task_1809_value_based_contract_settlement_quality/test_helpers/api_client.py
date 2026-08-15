"""API client: one method per endpoint defined in the PRD (§4 table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/vbc/_clock/set_current_utc", payload, headers)

    # --- Program ---
    def create_program(self, payload, headers):
        return self._request("POST", "/vbc/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/vbc/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/vbc/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/vbc/programs/{program_id}/activate", {}, headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/vbc/programs/{program_id}/archive", {}, headers)

    # --- PracticeGroup ---
    def create_practice_group(self, payload, headers):
        return self._request("POST", "/vbc/practice-groups", payload, headers)

    def list_practice_groups(self, headers, params=None):
        return self._request("GET", "/vbc/practice-groups", headers=headers, params=params)

    def get_practice_group(self, group_id, headers):
        return self._request("GET", f"/vbc/practice-groups/{group_id}", headers=headers)

    def suspend_practice_group(self, group_id, payload, headers):
        return self._request("POST", f"/vbc/practice-groups/{group_id}/suspend", payload, headers)

    def reinstate_practice_group(self, group_id, headers):
        return self._request("POST", f"/vbc/practice-groups/{group_id}/reinstate", {}, headers)

    def terminate_practice_group(self, group_id, headers):
        return self._request("POST", f"/vbc/practice-groups/{group_id}/terminate", {}, headers)

    # --- Practice ---
    def create_practice(self, payload, headers):
        return self._request("POST", "/vbc/practices", payload, headers)

    def list_practices(self, headers, params=None):
        return self._request("GET", "/vbc/practices", headers=headers, params=params)

    def get_practice(self, practice_id, headers):
        return self._request("GET", f"/vbc/practices/{practice_id}", headers=headers)

    def deactivate_practice(self, practice_id, headers):
        return self._request("POST", f"/vbc/practices/{practice_id}/deactivate", {}, headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/vbc/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/vbc/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/vbc/members/{member_id}", headers=headers)

    def disenroll_member(self, member_id, headers):
        return self._request("POST", f"/vbc/members/{member_id}/disenroll", {}, headers)

    # --- EligibilitySpan ---
    def create_eligibility_span(self, payload, headers):
        return self._request("POST", "/vbc/eligibility-spans", payload, headers)

    def list_eligibility_spans(self, headers, params=None):
        return self._request("GET", "/vbc/eligibility-spans", headers=headers, params=params)

    def get_eligibility_span(self, span_id, headers):
        return self._request("GET", f"/vbc/eligibility-spans/{span_id}", headers=headers)

    def close_eligibility_span(self, span_id, headers):
        return self._request("POST", f"/vbc/eligibility-spans/{span_id}/close", {}, headers)

    # --- Contract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/vbc/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/vbc/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/vbc/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/vbc/contracts/{contract_id}/activate", {}, headers)

    def expire_contract(self, contract_id, headers):
        return self._request("POST", f"/vbc/contracts/{contract_id}/expire", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/vbc/contracts/{contract_id}/terminate", {}, headers)

    def renew_contract(self, contract_id, headers):
        return self._request("POST", f"/vbc/contracts/{contract_id}/renew", {}, headers)

    # --- PerformanceYear ---
    def create_performance_year(self, payload, headers):
        return self._request("POST", "/vbc/performance-years", payload, headers)

    def list_performance_years(self, headers, params=None):
        return self._request("GET", "/vbc/performance-years", headers=headers, params=params)

    def get_performance_year(self, year_id, headers):
        return self._request("GET", f"/vbc/performance-years/{year_id}", headers=headers)

    def open_attribution(self, year_id, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/open-attribution", {}, headers)

    def lock_attribution(self, year_id, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/lock-attribution", {}, headers)

    def begin_measurement(self, year_id, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/begin-measurement", {}, headers)

    def begin_reconciliation(self, year_id, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/begin-reconciliation", {}, headers)

    def reopen_attribution(self, year_id, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/reopen-attribution", {}, headers)

    def mark_year_settled(self, year_id, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/mark-settled", {}, headers)

    def close_year(self, year_id, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/close", {}, headers)

    # --- AttributionRun ---
    def create_attribution_run(self, year_id, payload, headers):
        return self._request("POST", f"/vbc/performance-years/{year_id}/attribution-runs", payload, headers)

    def list_attribution_runs(self, headers, params=None):
        return self._request("GET", "/vbc/attribution-runs", headers=headers, params=params)

    def get_attribution_run(self, run_id, headers):
        return self._request("GET", f"/vbc/attribution-runs/{run_id}", headers=headers)

    def compute_attribution_run(self, run_id, headers):
        return self._request("POST", f"/vbc/attribution-runs/{run_id}/compute", {}, headers)

    def lock_attribution_run(self, run_id, headers):
        return self._request("POST", f"/vbc/attribution-runs/{run_id}/lock", {}, headers)

    # --- AttributionRecord ---
    def create_attribution_record(self, run_id, payload, headers):
        return self._request("POST", f"/vbc/attribution-runs/{run_id}/records", payload, headers)

    def list_attribution_records(self, headers, params=None):
        return self._request("GET", "/vbc/attribution-records", headers=headers, params=params)

    def get_attribution_record(self, record_id, headers):
        return self._request("GET", f"/vbc/attribution-records/{record_id}", headers=headers)

    def exclude_attribution_record(self, record_id, headers):
        return self._request("POST", f"/vbc/attribution-records/{record_id}/exclude", {}, headers)

    def reinstate_attribution_record(self, record_id, headers):
        return self._request("POST", f"/vbc/attribution-records/{record_id}/reinstate", {}, headers)

    # --- RiskScore ---
    def create_risk_score(self, payload, headers):
        return self._request("POST", "/vbc/risk-scores", payload, headers)

    def list_risk_scores(self, headers, params=None):
        return self._request("GET", "/vbc/risk-scores", headers=headers, params=params)

    def get_risk_score(self, score_id, headers):
        return self._request("GET", f"/vbc/risk-scores/{score_id}", headers=headers)

    def finalize_risk_score(self, score_id, headers):
        return self._request("POST", f"/vbc/risk-scores/{score_id}/finalize", {}, headers)

    def supersede_risk_score(self, score_id, headers):
        return self._request("POST", f"/vbc/risk-scores/{score_id}/supersede", {}, headers)

    # --- ClaimRecord ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/vbc/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/vbc/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/vbc/claims/{claim_id}", headers=headers)

    def mark_claim_paid(self, claim_id, headers):
        return self._request("POST", f"/vbc/claims/{claim_id}/mark-paid", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/vbc/claims/{claim_id}/deny", {}, headers)

    def void_claim(self, claim_id, headers):
        return self._request("POST", f"/vbc/claims/{claim_id}/void", {}, headers)

    # --- QualityMeasureResult ---
    def create_quality_result(self, payload, headers):
        return self._request("POST", "/vbc/quality-measure-results", payload, headers)

    def list_quality_results(self, headers, params=None):
        return self._request("GET", "/vbc/quality-measure-results", headers=headers, params=params)

    def get_quality_result(self, result_id, headers):
        return self._request("GET", f"/vbc/quality-measure-results/{result_id}", headers=headers)

    def validate_quality_result(self, result_id, headers):
        return self._request("POST", f"/vbc/quality-measure-results/{result_id}/validate", {}, headers)

    def return_quality_result_for_correction(self, result_id, headers):
        return self._request(
            "POST", f"/vbc/quality-measure-results/{result_id}/return-for-correction", {}, headers
        )

    def lock_quality_result(self, result_id, headers):
        return self._request("POST", f"/vbc/quality-measure-results/{result_id}/lock", {}, headers)

    def exclude_quality_result(self, result_id, headers):
        return self._request("POST", f"/vbc/quality-measure-results/{result_id}/exclude", {}, headers)

    # --- InterimReport ---
    def create_interim_report(self, payload, headers):
        return self._request("POST", "/vbc/interim-reports", payload, headers)

    def list_interim_reports(self, headers, params=None):
        return self._request("GET", "/vbc/interim-reports", headers=headers, params=params)

    def get_interim_report(self, report_id, headers):
        return self._request("GET", f"/vbc/interim-reports/{report_id}", headers=headers)

    def publish_interim_report(self, report_id, headers):
        return self._request("POST", f"/vbc/interim-reports/{report_id}/publish", {}, headers)

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/vbc/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/vbc/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/vbc/settlements/{settlement_id}", headers=headers)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/vbc/settlements/{settlement_id}/finalize", {}, headers)

    def recalculate_settlement(self, settlement_id, headers):
        return self._request("POST", f"/vbc/settlements/{settlement_id}/recalculate", {}, headers)

    def authorize_distribution(self, settlement_id, headers):
        return self._request("POST", f"/vbc/settlements/{settlement_id}/authorize-distribution", {}, headers)

    # --- SettlementDispute ---
    def create_dispute(self, settlement_id, payload, headers):
        return self._request("POST", f"/vbc/settlements/{settlement_id}/disputes", payload, headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/vbc/settlement-disputes", headers=headers, params=params)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/vbc/settlement-disputes/{dispute_id}", headers=headers)

    def begin_dispute_review(self, dispute_id, headers):
        return self._request("POST", f"/vbc/settlement-disputes/{dispute_id}/begin-review", {}, headers)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/vbc/settlement-disputes/{dispute_id}/resolve", payload, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/vbc/settlement-disputes/{dispute_id}/withdraw", {}, headers)

    def expire_dispute(self, dispute_id, headers):
        return self._request("POST", f"/vbc/settlement-disputes/{dispute_id}/expire", {}, headers)

    # --- DistributionRemittance ---
    def list_remittances(self, headers, params=None):
        return self._request("GET", "/vbc/distribution-remittances", headers=headers, params=params)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/vbc/distribution-remittances/{remittance_id}", headers=headers)

    def approve_remittance(self, remittance_id, headers):
        return self._request("POST", f"/vbc/distribution-remittances/{remittance_id}/approve", {}, headers)

    def mark_remittance_paid(self, remittance_id, headers):
        return self._request("POST", f"/vbc/distribution-remittances/{remittance_id}/mark-paid", {}, headers)

    def return_remittance(self, remittance_id, headers):
        return self._request("POST", f"/vbc/distribution-remittances/{remittance_id}/return", {}, headers)

    def requeue_remittance(self, remittance_id, headers):
        return self._request("POST", f"/vbc/distribution-remittances/{remittance_id}/requeue", {}, headers)

    # --- RenewalAnalysis ---
    def create_renewal_analysis(self, contract_id, payload, headers):
        return self._request("POST", f"/vbc/contracts/{contract_id}/renewal-analyses", payload, headers)

    def list_renewal_analyses(self, headers, params=None):
        return self._request("GET", "/vbc/renewal-analyses", headers=headers, params=params)

    def get_renewal_analysis(self, analysis_id, headers):
        return self._request("GET", f"/vbc/renewal-analyses/{analysis_id}", headers=headers)

    def complete_renewal_analysis(self, analysis_id, headers):
        return self._request("POST", f"/vbc/renewal-analyses/{analysis_id}/complete", {}, headers)


api_client = ApiClient()
