"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Employers ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/api/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/api/employers/{employer_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/api/employers", headers=headers, params=params)

    def suspend_employer(self, employer_id, headers):
        return self._request("POST", f"/api/employers/{employer_id}/suspend", {}, headers)

    def reactivate_employer(self, employer_id, headers):
        return self._request("POST", f"/api/employers/{employer_id}/reactivate", {}, headers)

    # --- Benefit plans & tiers ---
    def create_benefit_plan(self, payload, headers):
        return self._request("POST", "/api/benefit-plans", payload, headers)

    def get_benefit_plan(self, plan_id, headers):
        return self._request("GET", f"/api/benefit-plans/{plan_id}", headers=headers)

    def list_benefit_plans(self, headers, params=None):
        return self._request("GET", "/api/benefit-plans", headers=headers, params=params)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/api/benefit-plans/{plan_id}/activate", {}, headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/api/benefit-plans/{plan_id}/retire", {}, headers)

    def put_plan_tiers(self, plan_id, payload, headers):
        return self._request("PUT", f"/api/benefit-plans/{plan_id}/tiers", payload, headers)

    def list_plan_tiers(self, plan_id, headers):
        return self._request("GET", f"/api/benefit-plans/{plan_id}/tiers", headers=headers)

    # --- Members & dependents ---
    def create_member(self, payload, headers):
        return self._request("POST", "/api/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/api/members", headers=headers, params=params)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/reinstate", {}, headers)

    def terminate_member(self, member_id, headers):
        return self._request("POST", f"/api/members/{member_id}/terminate", {}, headers)

    def add_dependent(self, member_id, payload, headers):
        return self._request("POST", f"/api/members/{member_id}/dependents", payload, headers)

    def list_dependents(self, member_id, headers):
        return self._request("GET", f"/api/members/{member_id}/dependents", headers=headers)

    def deactivate_dependent(self, dependent_id, headers):
        return self._request("POST", f"/api/dependents/{dependent_id}/deactivate", {}, headers)

    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/api/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/api/providers/{provider_id}", headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/api/providers", headers=headers, params=params)

    def activate_provider(self, provider_id, headers):
        return self._request("POST", f"/api/providers/{provider_id}/activate", {}, headers)

    def suspend_provider(self, provider_id, headers):
        return self._request("POST", f"/api/providers/{provider_id}/suspend", {}, headers)

    def reinstate_provider(self, provider_id, headers):
        return self._request("POST", f"/api/providers/{provider_id}/reinstate", {}, headers)

    def terminate_provider(self, provider_id, headers):
        return self._request("POST", f"/api/providers/{provider_id}/terminate", {}, headers)

    def put_provider_contract(self, provider_id, payload, headers):
        return self._request("PUT", f"/api/providers/{provider_id}/contract", payload, headers)

    # --- Enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/api/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/api/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/api/enrollments", headers=headers, params=params)

    def close_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/close", {}, headers)

    def get_enrollment_allowance(self, enrollment_id, headers):
        return self._request("GET", f"/api/enrollments/{enrollment_id}/allowance", headers=headers)

    # --- Visits ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/api/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/api/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/api/visits", headers=headers, params=params)

    def verify_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/verify", {}, headers)

    def reject_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/reject", {}, headers)

    def void_visit(self, visit_id, headers):
        return self._request("POST", f"/api/visits/{visit_id}/void", {}, headers)

    # --- Claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def start_review(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/start-review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/api/claims/{claim_id}/reject", payload or {}, headers)

    def request_info(self, claim_id, headers, payload=None):
        return self._request("POST", f"/api/claims/{claim_id}/request-info", payload or {}, headers)

    def resubmit_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/api/claims/{claim_id}/resubmit", payload or {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/pay", {}, headers)

    def reverse_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/api/claims/{claim_id}/reverse", payload or {}, headers)

    # --- Funding ---
    def create_funding_account(self, payload, headers):
        return self._request("POST", "/api/funding-accounts", payload, headers)

    def get_funding_account(self, account_id, headers):
        return self._request("GET", f"/api/funding-accounts/{account_id}", headers=headers)

    def list_funding_accounts(self, headers, params=None):
        return self._request("GET", "/api/funding-accounts", headers=headers, params=params)

    def deposit_funding(self, account_id, payload, headers):
        return self._request("POST", f"/api/funding-accounts/{account_id}/deposits", payload, headers)

    def list_funding_entries(self, account_id, headers):
        return self._request("GET", f"/api/funding-accounts/{account_id}/entries", headers=headers)

    def suspend_funding_account(self, account_id, headers):
        return self._request("POST", f"/api/funding-accounts/{account_id}/suspend", {}, headers)

    def reactivate_funding_account(self, account_id, headers):
        return self._request("POST", f"/api/funding-accounts/{account_id}/reactivate", {}, headers)

    def list_claim_funding_entries(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}/funding-entries", headers=headers)

    # --- Fraud flags ---
    def get_fraud_flag(self, flag_id, headers):
        return self._request("GET", f"/api/fraud-flags/{flag_id}", headers=headers)

    def list_fraud_flags(self, headers, params=None):
        return self._request("GET", "/api/fraud-flags", headers=headers, params=params)

    def confirm_fraud_flag(self, flag_id, headers):
        return self._request("POST", f"/api/fraud-flags/{flag_id}/confirm", {}, headers)

    def clear_fraud_flag(self, flag_id, headers):
        return self._request("POST", f"/api/fraud-flags/{flag_id}/clear", {}, headers)

    # --- Statements ---
    def create_statement(self, payload, headers):
        return self._request("POST", "/api/statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/api/statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/api/statements", headers=headers, params=params)

    def finalize_statement(self, statement_id, headers):
        return self._request("POST", f"/api/statements/{statement_id}/finalize", {}, headers)

    def reopen_statement(self, statement_id, headers, payload=None):
        return self._request("POST", f"/api/statements/{statement_id}/reopen", payload or {}, headers)

    def deliver_statement(self, statement_id, headers):
        return self._request("POST", f"/api/statements/{statement_id}/deliver", {}, headers)

    # --- Reports ---
    def get_utilization_report(self, headers, params=None):
        return self._request("GET", "/api/reports/utilization", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
