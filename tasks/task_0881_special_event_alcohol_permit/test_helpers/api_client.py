"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/permits/venues", payload=payload, headers=headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/permits/venues/{venue_id}", headers=headers)

    # ---- Inspector ----
    def create_inspector(self, payload, headers):
        return self._request("POST", "/permits/inspectors", payload=payload, headers=headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/permits/inspectors/{inspector_id}", headers=headers)

    # ---- PermitApplication ----
    def create_application(self, payload, headers):
        return self._request("POST", "/permits/applications", payload=payload, headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/permits/applications", headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/permits/applications/{application_id}", headers=headers)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/submit", payload={}, headers=headers)

    def open_review(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/open-review", payload={}, headers=headers)

    def request_revisions(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/request-revisions", payload={}, headers=headers)

    def resubmit_application(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/resubmit", payload={}, headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/approve", payload={}, headers=headers)

    def deny_application(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/deny", payload={}, headers=headers)

    def issue_permit(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/issue-permit", payload={}, headers=headers)

    def close_application(self, application_id, headers):
        return self._request("POST", f"/permits/applications/{application_id}/close", payload={}, headers=headers)

    def create_payment(self, application_id, payload, headers):
        return self._request("POST", f"/permits/applications/{application_id}/payments", payload=payload, headers=headers)

    # ---- EventServer ----
    def create_server(self, payload, headers):
        return self._request("POST", "/permits/servers", payload=payload, headers=headers)

    def list_servers(self, headers, params=None):
        return self._request("GET", "/permits/servers", headers=headers, params=params)

    def get_server(self, server_id, headers):
        return self._request("GET", f"/permits/servers/{server_id}", headers=headers)

    def verify_server(self, server_id, headers):
        return self._request("POST", f"/permits/servers/{server_id}/verify", payload={}, headers=headers)

    # ---- InsurancePolicy ----
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/permits/insurance-policies", payload=payload, headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/permits/insurance-policies", headers=headers, params=params)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/permits/insurance-policies/{policy_id}", headers=headers)

    def accept_insurance_policy(self, policy_id, headers):
        return self._request("POST", f"/permits/insurance-policies/{policy_id}/accept", payload={}, headers=headers)

    # ---- SecurityPlan ----
    def create_security_plan(self, payload, headers):
        return self._request("POST", "/permits/security-plans", payload=payload, headers=headers)

    def list_security_plans(self, headers, params=None):
        return self._request("GET", "/permits/security-plans", headers=headers, params=params)

    def get_security_plan(self, plan_id, headers):
        return self._request("GET", f"/permits/security-plans/{plan_id}", headers=headers)

    def approve_security_plan(self, plan_id, headers):
        return self._request("POST", f"/permits/security-plans/{plan_id}/approve", payload={}, headers=headers)

    # ---- AgencyReview ----
    def list_agency_reviews(self, headers, params=None):
        return self._request("GET", "/permits/agency-reviews", headers=headers, params=params)

    def get_agency_review(self, review_id, headers):
        return self._request("GET", f"/permits/agency-reviews/{review_id}", headers=headers)

    def decide_agency_review(self, review_id, payload, headers):
        return self._request("POST", f"/permits/agency-reviews/{review_id}/decide", payload=payload, headers=headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/permits/inspections", payload=payload, headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/permits/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/permits/inspections/{inspection_id}", headers=headers)

    def record_inspection_result(self, inspection_id, payload, headers):
        return self._request("POST", f"/permits/inspections/{inspection_id}/record-result", payload=payload, headers=headers)

    # ---- Violation ----
    def create_violation(self, payload, headers):
        return self._request("POST", "/permits/violations", payload=payload, headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/permits/violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/permits/violations/{violation_id}", headers=headers)

    def contest_violation(self, violation_id, headers):
        return self._request("POST", f"/permits/violations/{violation_id}/contest", payload={}, headers=headers)

    def resolve_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/permits/violations/{violation_id}/resolve", payload=payload, headers=headers)

    # ---- LedgerEntry ----
    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/permits/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/permits/ledger-entries/{entry_id}", headers=headers)

    # ---- PostEventReport ----
    def create_report(self, payload, headers):
        return self._request("POST", "/permits/reports", payload=payload, headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/permits/reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/permits/reports/{report_id}", headers=headers)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", payload={"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
