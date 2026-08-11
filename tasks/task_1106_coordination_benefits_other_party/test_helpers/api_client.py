"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Rule configs ----
    def create_rule_config(self, payload, headers):
        return self._request("POST", "/cob/rule-configs", payload, headers)

    def list_rule_configs(self, headers, params=None):
        return self._request("GET", "/cob/rule-configs", headers=headers, params=params)

    def get_rule_config(self, config_id, headers):
        return self._request("GET", f"/cob/rule-configs/{config_id}", headers=headers)

    # ---- Providers ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/cob/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/cob/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/cob/providers", headers=headers, params=params)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/cob/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/cob/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/cob/members", headers=headers, params=params)

    def disenroll_member(self, member_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/disenroll", {}, headers)

    def list_dependents(self, member_id, headers, params=None):
        return self._request("GET", f"/cob/members/{member_id}/dependents", headers=headers, params=params)

    # ---- Coverages ----
    def create_coverage(self, member_id, payload, headers):
        return self._request("POST", f"/cob/members/{member_id}/coverages", payload, headers)

    def list_coverages(self, member_id, headers, params=None):
        return self._request("GET", f"/cob/members/{member_id}/coverages", headers=headers, params=params)

    def get_coverage(self, member_id, coverage_id, headers):
        return self._request("GET", f"/cob/members/{member_id}/coverages/{coverage_id}", headers=headers)

    def verify_coverage(self, member_id, coverage_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/coverages/{coverage_id}/verify", {}, headers)

    def reject_coverage(self, member_id, coverage_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/coverages/{coverage_id}/reject", {}, headers)

    # ---- Other coverage leads ----
    def create_lead(self, member_id, payload, headers):
        return self._request("POST", f"/cob/members/{member_id}/other-coverage-leads", payload, headers)

    def list_leads(self, member_id, headers, params=None):
        return self._request("GET", f"/cob/members/{member_id}/other-coverage-leads", headers=headers, params=params)

    def get_lead(self, member_id, lead_id, headers):
        return self._request("GET", f"/cob/members/{member_id}/other-coverage-leads/{lead_id}", headers=headers)

    def mark_lead_duplicate(self, member_id, lead_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/other-coverage-leads/{lead_id}/mark-duplicate", {}, headers)

    def reject_lead(self, member_id, lead_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/other-coverage-leads/{lead_id}/reject", {}, headers)

    # ---- Member surveys ----
    def create_survey(self, member_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/member-surveys", {}, headers)

    def list_surveys(self, member_id, headers, params=None):
        return self._request("GET", f"/cob/members/{member_id}/member-surveys", headers=headers, params=params)

    def get_survey(self, member_id, survey_id, headers):
        return self._request("GET", f"/cob/members/{member_id}/member-surveys/{survey_id}", headers=headers)

    def respond_survey(self, member_id, survey_id, payload, headers):
        return self._request("POST", f"/cob/members/{member_id}/member-surveys/{survey_id}/respond", payload, headers)

    # ---- MSP questionnaires ----
    def create_msp_questionnaire(self, member_id, payload, headers):
        return self._request("POST", f"/cob/members/{member_id}/msp-questionnaires", payload, headers)

    def list_msp_questionnaires(self, member_id, headers, params=None):
        return self._request("GET", f"/cob/members/{member_id}/msp-questionnaires", headers=headers, params=params)

    def get_msp_questionnaire(self, member_id, questionnaire_id, headers):
        return self._request("GET", f"/cob/members/{member_id}/msp-questionnaires/{questionnaire_id}", headers=headers)

    def adjudicate_msp_questionnaire(self, member_id, questionnaire_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/msp-questionnaires/{questionnaire_id}/adjudicate", {}, headers)

    def void_msp_questionnaire(self, member_id, questionnaire_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/msp-questionnaires/{questionnaire_id}/void", {}, headers)

    # ---- Primacy determinations ----
    def create_primacy_determination(self, member_id, payload, headers):
        return self._request("POST", f"/cob/members/{member_id}/primacy-determinations", payload, headers)

    def list_primacy_determinations(self, member_id, headers, params=None):
        return self._request("GET", f"/cob/members/{member_id}/primacy-determinations", headers=headers, params=params)

    def get_primacy_determination(self, member_id, determination_id, headers):
        return self._request("GET", f"/cob/members/{member_id}/primacy-determinations/{determination_id}", headers=headers)

    def finalize_primacy_determination(self, member_id, determination_id, headers):
        return self._request("POST", f"/cob/members/{member_id}/primacy-determinations/{determination_id}/finalize", {}, headers)

    # ---- Claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/cob/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/cob/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/cob/claims", headers=headers, params=params)

    def add_claim_line(self, claim_id, payload, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/lines", payload, headers)

    def list_claim_lines(self, claim_id, headers, params=None):
        return self._request("GET", f"/cob/claims/{claim_id}/lines", headers=headers, params=params)

    def adjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/adjudicate", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/pay", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/reopen", {}, headers)

    def readjudicate_claim(self, claim_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/readjudicate", {}, headers)

    def repay_claim(self, claim_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/repay", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/close", {}, headers)

    # ---- Claim adjustments ----
    def create_adjustment(self, claim_id, payload, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/adjustments", payload, headers)

    def list_adjustments(self, claim_id, headers, params=None):
        return self._request("GET", f"/cob/claims/{claim_id}/adjustments", headers=headers, params=params)

    def get_adjustment(self, claim_id, adjustment_id, headers):
        return self._request("GET", f"/cob/claims/{claim_id}/adjustments/{adjustment_id}", headers=headers)

    def apply_adjustment(self, claim_id, adjustment_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/adjustments/{adjustment_id}/apply", {}, headers)

    def void_adjustment(self, claim_id, adjustment_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/adjustments/{adjustment_id}/void", {}, headers)

    # ---- Recovery requests ----
    def create_recovery_request(self, claim_id, payload, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/recovery-requests", payload, headers)

    def list_recovery_requests(self, claim_id, headers, params=None):
        return self._request("GET", f"/cob/claims/{claim_id}/recovery-requests", headers=headers, params=params)

    def get_recovery_request(self, claim_id, recovery_id, headers):
        return self._request("GET", f"/cob/claims/{claim_id}/recovery-requests/{recovery_id}", headers=headers)

    def issue_recovery_request(self, claim_id, recovery_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/recovery-requests/{recovery_id}/issue", {}, headers)

    def escalate_recovery_request(self, claim_id, recovery_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/recovery-requests/{recovery_id}/escalate", {}, headers)

    def write_off_recovery_request(self, claim_id, recovery_id, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/recovery-requests/{recovery_id}/write-off", {}, headers)

    # ---- Reimbursements ----
    def post_reimbursement(self, claim_id, recovery_id, payload, headers):
        return self._request("POST", f"/cob/claims/{claim_id}/recovery-requests/{recovery_id}/reimbursements", payload, headers)

    def list_reimbursements(self, claim_id, recovery_id, headers, params=None):
        return self._request("GET", f"/cob/claims/{claim_id}/recovery-requests/{recovery_id}/reimbursements", headers=headers, params=params)

    # ---- Savings periods ----
    def create_savings_period(self, payload, headers):
        return self._request("POST", "/cob/savings-periods", payload, headers)

    def get_savings_period(self, period_id, headers):
        return self._request("GET", f"/cob/savings-periods/{period_id}", headers=headers)

    def list_savings_periods(self, headers, params=None):
        return self._request("GET", "/cob/savings-periods", headers=headers, params=params)

    def close_savings_period(self, period_id, headers):
        return self._request("POST", f"/cob/savings-periods/{period_id}/close", {}, headers)

    # ---- Top-level reverse lookups ----
    def get_primacy_determination_toplevel(self, determination_id, headers):
        return self._request("GET", f"/cob/primacy-determinations/{determination_id}", headers=headers)

    def list_primacy_determinations_toplevel(self, headers, params=None):
        return self._request("GET", "/cob/primacy-determinations", headers=headers, params=params)

    def get_adjustment_toplevel(self, adjustment_id, headers):
        return self._request("GET", f"/cob/adjustments/{adjustment_id}", headers=headers)

    def list_adjustments_toplevel(self, headers, params=None):
        return self._request("GET", "/cob/adjustments", headers=headers, params=params)

    def get_recovery_request_toplevel(self, recovery_id, headers):
        return self._request("GET", f"/cob/recovery-requests/{recovery_id}", headers=headers)

    def list_recovery_requests_toplevel(self, headers, params=None):
        return self._request("GET", "/cob/recovery-requests", headers=headers, params=params)

    def get_reimbursement_toplevel(self, reimbursement_id, headers):
        return self._request("GET", f"/cob/reimbursements/{reimbursement_id}", headers=headers)

    def list_reimbursements_toplevel(self, headers, params=None):
        return self._request("GET", "/cob/reimbursements", headers=headers, params=params)

    # ---- Logical clock (test-driving capability, PRD §2.6) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/cob/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
