"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/eap/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ---- EmployerContract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/eap/contracts", payload, headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/eap/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/eap/contracts/{contract_id}", headers=headers)

    def get_contract_utilization(self, contract_id, headers, params=None):
        return self._request("GET", f"/eap/contracts/{contract_id}/utilization",
                             headers=headers, params=params)

    def suspend_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/eap/contracts/{contract_id}/suspend",
                             payload, headers=headers)

    def reinstate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/eap/contracts/{contract_id}/reinstate",
                             payload, headers=headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/eap/contracts/{contract_id}/terminate",
                             payload, headers=headers)

    def create_report(self, contract_id, payload, headers):
        return self._request("POST", f"/eap/contracts/{contract_id}/reports",
                             payload, headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/eap/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/eap/reports/{report_id}", headers=headers)

    # ---- BenefitPlan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/eap/plans", payload, headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/eap/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/eap/plans/{plan_id}", headers=headers)

    def publish_plan(self, plan_id, headers):
        return self._request("POST", f"/eap/plans/{plan_id}/publish",
                             {}, headers=headers)

    # ---- Employee ----
    def create_employee(self, payload, headers):
        return self._request("POST", "/eap/employees", payload, headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/eap/employees", headers=headers, params=params)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/eap/employees/{employee_id}", headers=headers)

    def set_eligibility(self, employee_id, payload, headers):
        return self._request("POST", f"/eap/employees/{employee_id}/eligibility",
                             payload, headers=headers)

    # ---- Dependent ----
    def create_dependent(self, payload, headers):
        return self._request("POST", "/eap/dependents", payload, headers=headers)

    def list_dependents(self, headers, params=None):
        return self._request("GET", "/eap/dependents", headers=headers, params=params)

    def get_dependent(self, dependent_id, headers):
        return self._request("GET", f"/eap/dependents/{dependent_id}", headers=headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", "/eap/cases", payload, headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/eap/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/eap/cases/{case_id}", headers=headers)

    def authorize_case(self, case_id, payload, headers):
        return self._request("POST", f"/eap/cases/{case_id}/authorize",
                             payload, headers=headers)

    def revoke_case(self, case_id, headers):
        return self._request("POST", f"/eap/cases/{case_id}/revoke",
                             {}, headers=headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/eap/cases/{case_id}/close",
                             {}, headers=headers)

    # ---- CounselingSession ----
    def create_session(self, case_id, payload, headers):
        return self._request("POST", f"/eap/cases/{case_id}/sessions",
                             payload, headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/eap/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/eap/sessions/{session_id}", headers=headers)

    def set_session_status(self, session_id, payload, headers):
        return self._request("POST", f"/eap/sessions/{session_id}/status",
                             payload, headers=headers)

    # ---- Provider ----
    def create_provider(self, payload, headers):
        return self._request("POST", "/eap/providers", payload, headers=headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/eap/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/eap/providers/{provider_id}", headers=headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/eap/referrals", payload, headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/eap/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/eap/referrals/{referral_id}", headers=headers)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/eap/referrals/{referral_id}/accept",
                             {}, headers=headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/eap/referrals/{referral_id}/decline",
                             {}, headers=headers)

    def reassign_referral(self, referral_id, headers):
        return self._request("POST", f"/eap/referrals/{referral_id}/reassign",
                             {}, headers=headers)

    def complete_referral(self, referral_id, headers):
        return self._request("POST", f"/eap/referrals/{referral_id}/complete",
                             {}, headers=headers)

    def cancel_referral(self, referral_id, headers):
        return self._request("POST", f"/eap/referrals/{referral_id}/cancel",
                             {}, headers=headers)

    # ---- CrisisContact ----
    def create_crisis_contact(self, payload, headers):
        return self._request("POST", "/eap/crisis-contacts", payload, headers=headers)

    def list_crisis_contacts(self, headers, params=None):
        return self._request("GET", "/eap/crisis-contacts", headers=headers, params=params)

    def get_crisis_contact(self, crisis_id, headers):
        return self._request("GET", f"/eap/crisis-contacts/{crisis_id}", headers=headers)

    def triage_crisis_contact(self, crisis_id, payload, headers):
        return self._request("POST", f"/eap/crisis-contacts/{crisis_id}/triage",
                             payload, headers=headers)

    def escalate_crisis_contact(self, crisis_id, payload, headers):
        return self._request("POST", f"/eap/crisis-contacts/{crisis_id}/escalate",
                             payload, headers=headers)

    def resolve_crisis_contact(self, crisis_id, headers):
        return self._request("POST", f"/eap/crisis-contacts/{crisis_id}/resolve",
                             {}, headers=headers)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/eap/claims", payload, headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/eap/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/eap/claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/eap/claims/{claim_id}/review",
                             {}, headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/eap/claims/{claim_id}/approve",
                             {}, headers=headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/eap/claims/{claim_id}/reject",
                             {}, headers=headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/eap/claims/{claim_id}/resubmit",
                             payload, headers=headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/eap/claims/{claim_id}/pay",
                             {}, headers=headers)

    # ---- WellnessActivity ----
    def create_wellness_activity(self, payload, headers):
        return self._request("POST", "/eap/wellness-activities", payload, headers=headers)

    def list_wellness_activities(self, headers, params=None):
        return self._request("GET", "/eap/wellness-activities", headers=headers, params=params)

    def get_wellness_activity(self, activity_id, headers):
        return self._request("GET", f"/eap/wellness-activities/{activity_id}", headers=headers)


api_client = ApiClient()
