"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Engagement lifecycle ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/plan-audit/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/plan-audit/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/plan-audit/engagements/{engagement_id}", headers=headers)

    def activate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/activate", {}, headers)

    def begin_testing(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/begin_testing", {}, headers)

    def begin_fieldwork(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/begin_fieldwork", {}, headers)

    def attach_audit_report(self, engagement_id, payload, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/attach_audit_report", payload, headers)

    def issue_report(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/issue_report", {}, headers)

    def reopen_data_collection(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/reopen_data_collection", {}, headers)

    def reopen_fieldwork(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/reopen_fieldwork", {}, headers)

    def complete_engagement(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/complete", {}, headers)

    def recompute_participant_count(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/recompute_participant_count", {}, headers)

    def late_deposit_scan(self, engagement_id, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/late-deposit-scan", {}, headers)

    def compute_fee_disclosure(self, engagement_id, payload, headers):
        return self._request("POST", f"/plan-audit/engagements/{engagement_id}/compute-fee-disclosure", payload, headers)

    # --- Participants ---
    def create_participant(self, payload, headers):
        return self._request("POST", "/plan-audit/participants", payload, headers)

    def bulk_import_participants(self, payload, headers):
        return self._request("POST", "/plan-audit/participants/bulk-import", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/plan-audit/participants", headers=headers, params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/plan-audit/participants/{participant_id}", headers=headers)

    def update_participant(self, participant_id, payload, headers):
        return self._request("PATCH", f"/plan-audit/participants/{participant_id}", payload, headers)

    # --- Contributions & trust ---
    def create_contribution(self, payload, headers):
        return self._request("POST", "/plan-audit/contributions", payload, headers)

    def list_contributions(self, headers, params=None):
        return self._request("GET", "/plan-audit/contributions", headers=headers, params=params)

    def get_contribution(self, contribution_id, headers):
        return self._request("GET", f"/plan-audit/contributions/{contribution_id}", headers=headers)

    def match_contribution(self, contribution_id, payload, headers):
        return self._request("POST", f"/plan-audit/contributions/{contribution_id}/match", payload, headers)

    def unmatch_contribution(self, contribution_id, headers):
        return self._request("POST", f"/plan-audit/contributions/{contribution_id}/unmatch", {}, headers)

    def create_trust_statement(self, payload, headers):
        return self._request("POST", "/plan-audit/trust-statements", payload, headers)

    def list_trust_statements(self, headers, params=None):
        return self._request("GET", "/plan-audit/trust-statements", headers=headers, params=params)

    def get_trust_statement(self, statement_id, headers):
        return self._request("GET", f"/plan-audit/trust-statements/{statement_id}", headers=headers)

    def reconcile_trust_statement(self, statement_id, headers):
        return self._request("POST", f"/plan-audit/trust-statements/{statement_id}/reconcile", {}, headers)

    def resolve_trust_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/plan-audit/trust-statements/{statement_id}/resolve", payload, headers)

    # --- Nondiscrimination testing ---
    def create_test_result(self, payload, headers):
        return self._request("POST", "/plan-audit/test-results", payload, headers)

    def list_test_results(self, headers, params=None):
        return self._request("GET", "/plan-audit/test-results", headers=headers, params=params)

    def get_test_result(self, result_id, headers):
        return self._request("GET", f"/plan-audit/test-results/{result_id}", headers=headers)

    def finalize_test_result(self, result_id, headers):
        return self._request("POST", f"/plan-audit/test-results/{result_id}/finalize", {}, headers)

    # --- Late contribution assessments ---
    def list_late_contribution_assessments(self, headers, params=None):
        return self._request("GET", "/plan-audit/late-contribution-assessments", headers=headers, params=params)

    def get_late_contribution_assessment(self, assessment_id, headers):
        return self._request("GET", f"/plan-audit/late-contribution-assessments/{assessment_id}", headers=headers)

    def confirm_late_contribution_assessment(self, assessment_id, headers):
        return self._request("POST", f"/plan-audit/late-contribution-assessments/{assessment_id}/confirm", {}, headers)

    def dismiss_late_contribution_assessment(self, assessment_id, payload, headers):
        return self._request("POST", f"/plan-audit/late-contribution-assessments/{assessment_id}/dismiss", payload, headers)

    # --- Findings ---
    def create_finding(self, payload, headers):
        return self._request("POST", "/plan-audit/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/plan-audit/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/plan-audit/findings/{finding_id}", headers=headers)

    def acknowledge_finding(self, finding_id, headers):
        return self._request("POST", f"/plan-audit/findings/{finding_id}/acknowledge", {}, headers)

    def waive_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/plan-audit/findings/{finding_id}/waive", payload, headers)

    def verify_close_finding(self, finding_id, headers):
        return self._request("POST", f"/plan-audit/findings/{finding_id}/verify_close", {}, headers)

    # --- Corrective actions ---
    def create_corrective_action(self, payload, headers):
        return self._request("POST", "/plan-audit/corrective-actions", payload, headers)

    def list_corrective_actions(self, headers, params=None):
        return self._request("GET", "/plan-audit/corrective-actions", headers=headers, params=params)

    def get_corrective_action(self, action_id, headers):
        return self._request("GET", f"/plan-audit/corrective-actions/{action_id}", headers=headers)

    def approve_corrective_action(self, action_id, headers):
        return self._request("POST", f"/plan-audit/corrective-actions/{action_id}/approve", {}, headers)

    def execute_corrective_action(self, action_id, headers):
        return self._request("POST", f"/plan-audit/corrective-actions/{action_id}/execute", {}, headers)

    def verify_corrective_action(self, action_id, headers):
        return self._request("POST", f"/plan-audit/corrective-actions/{action_id}/verify", {}, headers)

    def void_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/plan-audit/corrective-actions/{action_id}/void", payload, headers)

    # --- Service provider fees ---
    def create_service_provider_fee(self, payload, headers):
        return self._request("POST", "/plan-audit/service-provider-fees", payload, headers)

    def list_service_provider_fees(self, headers, params=None):
        return self._request("GET", "/plan-audit/service-provider-fees", headers=headers, params=params)

    def get_service_provider_fee(self, fee_id, headers):
        return self._request("GET", f"/plan-audit/service-provider-fees/{fee_id}", headers=headers)

    # --- Form 5500 filing & schedules ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/plan-audit/filings", payload, headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/plan-audit/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/plan-audit/filings/{filing_id}", headers=headers)

    def create_schedule_entry(self, payload, headers):
        return self._request("POST", "/plan-audit/schedule-entries", payload, headers)

    def list_schedule_entries(self, headers, params=None):
        return self._request("GET", "/plan-audit/schedule-entries", headers=headers, params=params)

    def get_schedule_entry(self, entry_id, headers):
        return self._request("GET", f"/plan-audit/schedule-entries/{entry_id}", headers=headers)

    def verify_schedule_entry(self, entry_id, headers):
        return self._request("POST", f"/plan-audit/schedule-entries/{entry_id}/verify", {}, headers)

    def mark_schedules_complete(self, filing_id, headers):
        return self._request("POST", f"/plan-audit/filings/{filing_id}/mark_schedules_complete", {}, headers)

    def mark_ready(self, filing_id, headers):
        return self._request("POST", f"/plan-audit/filings/{filing_id}/mark_ready", {}, headers)

    def submit_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/plan-audit/filings/{filing_id}/submit", payload, headers)

    def record_disposition(self, filing_id, payload, headers):
        return self._request("POST", f"/plan-audit/filings/{filing_id}/record_disposition", payload, headers)

    def reopen_filing(self, filing_id, headers):
        return self._request("POST", f"/plan-audit/filings/{filing_id}/reopen", {}, headers)

    def amend_filing(self, filing_id, payload, headers):
        return self._request("POST", f"/plan-audit/filings/{filing_id}/amendments", payload, headers)

    # --- Filing extensions ---
    def create_filing_extension(self, payload, headers):
        return self._request("POST", "/plan-audit/filing-extensions", payload, headers)

    def list_filing_extensions(self, headers, params=None):
        return self._request("GET", "/plan-audit/filing-extensions", headers=headers, params=params)

    def get_filing_extension(self, extension_id, headers):
        return self._request("GET", f"/plan-audit/filing-extensions/{extension_id}", headers=headers)

    # --- Correction program filings ---
    def create_correction_program_filing(self, payload, headers):
        return self._request("POST", "/plan-audit/correction-program-filings", payload, headers)

    def list_correction_program_filings(self, headers, params=None):
        return self._request("GET", "/plan-audit/correction-program-filings", headers=headers, params=params)

    def get_correction_program_filing(self, cpf_id, headers):
        return self._request("GET", f"/plan-audit/correction-program-filings/{cpf_id}", headers=headers)

    def submit_correction_program_filing(self, cpf_id, headers):
        return self._request("POST", f"/plan-audit/correction-program-filings/{cpf_id}/submit", {}, headers)

    def record_decision(self, cpf_id, payload, headers):
        return self._request("POST", f"/plan-audit/correction-program-filings/{cpf_id}/record_decision", payload, headers)

    # --- Logical clock (test-driving endpoint) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
