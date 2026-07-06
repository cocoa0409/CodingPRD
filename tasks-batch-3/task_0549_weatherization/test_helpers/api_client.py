"""API client: one method per Weatherization endpoint.

Subclasses ``GenericApiClient``; the base ``_request()`` handles the HTTP call,
envelope parsing, and header injection.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Dwelling
    def create_dwelling(self, payload, headers):
        return self._request("POST", "/weatherization/dwellings", payload, headers)

    def get_dwelling(self, dwelling_id, headers):
        return self._request("GET", f"/weatherization/dwellings/{dwelling_id}", headers=headers)

    # ---- WapApplication
    def create_wap_application(self, payload, headers):
        return self._request("POST", "/weatherization/wap-applications", payload, headers)

    def get_wap_application(self, wap_application_id, headers):
        return self._request("GET", f"/weatherization/wap-applications/{wap_application_id}", headers=headers)

    def list_wap_applications(self, headers, params=None):
        return self._request("GET", "/weatherization/wap-applications", headers=headers, params=params)

    # ---- Job
    def create_job(self, payload, headers):
        return self._request("POST", "/weatherization/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/weatherization/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/weatherization/jobs", headers=headers, params=params)

    def complete_install(self, job_id, headers):
        return self._request("POST", f"/weatherization/jobs/{job_id}/complete-install", {}, headers)

    def verify_job(self, job_id, payload, headers):
        return self._request("POST", f"/weatherization/jobs/{job_id}/verify", payload, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/weatherization/jobs/{job_id}/cancel", {}, headers)

    # ---- EnergyAudit
    def create_audit(self, payload, headers):
        return self._request("POST", "/weatherization/audits", payload, headers)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/weatherization/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/weatherization/audits", headers=headers, params=params)

    def submit_audit(self, audit_id, headers):
        return self._request("POST", f"/weatherization/audits/{audit_id}/submit", {}, headers)

    def decide_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/weatherization/audits/{audit_id}/decide", payload, headers)

    # ---- DiagnosticTest
    def create_diagnostic_test(self, payload, headers):
        return self._request("POST", "/weatherization/diagnostic-tests", payload, headers)

    def get_diagnostic_test(self, diagnostic_test_id, headers):
        return self._request("GET", f"/weatherization/diagnostic-tests/{diagnostic_test_id}", headers=headers)

    def list_diagnostic_tests(self, headers, params=None):
        return self._request("GET", "/weatherization/diagnostic-tests", headers=headers, params=params)

    # ---- ScopeItem
    def create_scope_item(self, payload, headers):
        return self._request("POST", "/weatherization/scope-items", payload, headers)

    def get_scope_item(self, scope_item_id, headers):
        return self._request("GET", f"/weatherization/scope-items/{scope_item_id}", headers=headers)

    def list_scope_items(self, headers, params=None):
        return self._request("GET", "/weatherization/scope-items", headers=headers, params=params)

    def decide_scope_item(self, scope_item_id, payload, headers):
        return self._request("POST", f"/weatherization/scope-items/{scope_item_id}/decide", payload, headers)

    def mark_installed(self, scope_item_id, payload, headers):
        return self._request("POST", f"/weatherization/scope-items/{scope_item_id}/mark-installed", payload, headers)

    # ---- Crew
    def create_crew(self, payload, headers):
        return self._request("POST", "/weatherization/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/weatherization/crews/{crew_id}", headers=headers)

    # ---- CrewAssignment
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/weatherization/crew-assignments", payload, headers)

    def get_crew_assignment(self, crew_assignment_id, headers):
        return self._request("GET", f"/weatherization/crew-assignments/{crew_assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/weatherization/crew-assignments", headers=headers, params=params)

    def cancel_crew_assignment(self, crew_assignment_id, headers):
        return self._request("POST", f"/weatherization/crew-assignments/{crew_assignment_id}/cancel", {}, headers)

    # ---- RebateClaim
    def create_rebate_claim(self, payload, headers):
        return self._request("POST", "/weatherization/rebate-claims", payload, headers)

    def get_rebate_claim(self, rebate_claim_id, headers):
        return self._request("GET", f"/weatherization/rebate-claims/{rebate_claim_id}", headers=headers)

    def list_rebate_claims(self, headers, params=None):
        return self._request("GET", "/weatherization/rebate-claims", headers=headers, params=params)

    def submit_rebate_claim(self, rebate_claim_id, headers):
        return self._request("POST", f"/weatherization/rebate-claims/{rebate_claim_id}/submit", {}, headers)

    def decide_rebate_claim(self, rebate_claim_id, payload, headers):
        return self._request("POST", f"/weatherization/rebate-claims/{rebate_claim_id}/decide", payload, headers)

    def void_rebate_claim(self, rebate_claim_id, headers):
        return self._request("POST", f"/weatherization/rebate-claims/{rebate_claim_id}/void", {}, headers)

    # ---- FinancingPlan
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/weatherization/financing-plans", payload, headers)

    def get_financing_plan(self, financing_plan_id, headers):
        return self._request("GET", f"/weatherization/financing-plans/{financing_plan_id}", headers=headers)

    def list_financing_plans(self, headers, params=None):
        return self._request("GET", "/weatherization/financing-plans", headers=headers, params=params)

    def respond_financing_plan(self, financing_plan_id, payload, headers):
        return self._request("POST", f"/weatherization/financing-plans/{financing_plan_id}/respond", payload, headers)


api_client = ApiClient()
