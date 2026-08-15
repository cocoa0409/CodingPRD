"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving / platform ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/telerad/_clock/set_current_utc", payload, headers)

    def seed_finalized_studies(self, payload, headers):
        return self._request("POST", "/telerad/_seed/finalized-studies", payload, headers)

    # ---- ClientHospital ----
    def create_hospital(self, payload, headers):
        return self._request("POST", "/telerad/hospitals", payload, headers)

    def get_hospital(self, hospital_id, headers):
        return self._request("GET", f"/telerad/hospitals/{hospital_id}", headers=headers)

    def list_hospitals(self, headers, params=None):
        return self._request("GET", "/telerad/hospitals", headers=headers, params=params)

    def activate_hospital(self, hospital_id, headers):
        return self._request("POST", f"/telerad/hospitals/{hospital_id}/activate", {}, headers)

    def suspend_hospital(self, hospital_id, headers):
        return self._request("POST", f"/telerad/hospitals/{hospital_id}/suspend", {}, headers)

    # ---- Radiologist ----
    def create_radiologist(self, payload, headers):
        return self._request("POST", "/telerad/radiologists", payload, headers)

    def get_radiologist(self, radiologist_id, headers):
        return self._request("GET", f"/telerad/radiologists/{radiologist_id}", headers=headers)

    def list_radiologists(self, headers, params=None):
        return self._request("GET", "/telerad/radiologists", headers=headers, params=params)

    def patch_radiologist(self, radiologist_id, payload, headers):
        return self._request("PATCH", f"/telerad/radiologists/{radiologist_id}", payload, headers)

    # ---- CoverageShift ----
    def create_shift(self, payload, headers):
        return self._request("POST", "/telerad/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/telerad/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/telerad/shifts", headers=headers, params=params)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/telerad/shifts/{shift_id}/cancel", {}, headers)

    # ---- RoutingPolicy ----
    def create_routing_policy(self, payload, headers):
        return self._request("POST", "/telerad/routing-policies", payload, headers)

    def get_routing_policy(self, policy_id, headers):
        return self._request("GET", f"/telerad/routing-policies/{policy_id}", headers=headers)

    def list_routing_policies(self, headers, params=None):
        return self._request("GET", "/telerad/routing-policies", headers=headers, params=params)

    # ---- CredentialGrant ----
    def create_credential_grant(self, payload, headers):
        return self._request("POST", "/telerad/credential-grants", payload, headers)

    def get_credential_grant(self, grant_id, headers):
        return self._request("GET", f"/telerad/credential-grants/{grant_id}", headers=headers)

    def list_credential_grants(self, headers, params=None):
        return self._request("GET", "/telerad/credential-grants", headers=headers, params=params)

    def grant_credential(self, grant_id, headers):
        return self._request("POST", f"/telerad/credential-grants/{grant_id}/grant", {}, headers)

    def suspend_credential(self, grant_id, headers):
        return self._request("POST", f"/telerad/credential-grants/{grant_id}/suspend", {}, headers)

    def reinstate_credential(self, grant_id, headers):
        return self._request("POST", f"/telerad/credential-grants/{grant_id}/reinstate", {}, headers)

    def revoke_credential(self, grant_id, headers):
        return self._request("POST", f"/telerad/credential-grants/{grant_id}/revoke", {}, headers)

    def renew_credential(self, grant_id, payload, headers):
        return self._request("POST", f"/telerad/credential-grants/{grant_id}/renew", payload, headers)

    # ---- Study ----
    def create_study(self, payload, headers):
        return self._request("POST", "/telerad/studies", payload, headers)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/telerad/studies/{study_id}", headers=headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/telerad/studies", headers=headers, params=params)

    def route_study(self, study_id, headers):
        return self._request("POST", f"/telerad/studies/{study_id}/route", {}, headers)

    def cancel_study(self, study_id, headers):
        return self._request("POST", f"/telerad/studies/{study_id}/cancel", {}, headers)

    def request_addendum(self, study_id, headers):
        return self._request("POST", f"/telerad/studies/{study_id}/request-addendum", {}, headers)

    # ---- Assignment ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/telerad/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/telerad/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/telerad/assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"/telerad/assignments/{assignment_id}/accept", {}, headers)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/telerad/assignments/{assignment_id}/release", {}, headers)

    # ---- Report ----
    def create_report(self, payload, headers):
        return self._request("POST", "/telerad/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/telerad/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/telerad/reports", headers=headers, params=params)

    def sign_report(self, report_id, headers):
        return self._request("POST", f"/telerad/reports/{report_id}/sign", {}, headers)

    # ---- DiscrepancyCase ----
    def create_discrepancy_case(self, payload, headers):
        return self._request("POST", "/telerad/discrepancy-cases", payload, headers)

    def get_discrepancy_case(self, case_id, headers):
        return self._request("GET", f"/telerad/discrepancy-cases/{case_id}", headers=headers)

    def list_discrepancy_cases(self, headers, params=None):
        return self._request("GET", "/telerad/discrepancy-cases", headers=headers, params=params)

    def open_peer_review(self, case_id, headers):
        return self._request("POST", f"/telerad/discrepancy-cases/{case_id}/open-peer-review", {}, headers)

    def close_no_action(self, case_id, headers):
        return self._request("POST", f"/telerad/discrepancy-cases/{case_id}/close-no-action", {}, headers)

    def escalate_case(self, case_id, headers):
        return self._request("POST", f"/telerad/discrepancy-cases/{case_id}/escalate", {}, headers)

    def reconcile_case(self, case_id, payload, headers):
        return self._request("POST", f"/telerad/discrepancy-cases/{case_id}/reconcile", payload, headers)

    # ---- CriticalResultNotice ----
    def get_critical_notice(self, notice_id, headers):
        return self._request("GET", f"/telerad/critical-notices/{notice_id}", headers=headers)

    def list_critical_notices(self, headers, params=None):
        return self._request("GET", "/telerad/critical-notices", headers=headers, params=params)

    def record_notification(self, notice_id, payload, headers):
        return self._request("POST", f"/telerad/critical-notices/{notice_id}/record-notification", payload, headers)

    def confirm_readback(self, notice_id, payload, headers):
        return self._request("POST", f"/telerad/critical-notices/{notice_id}/confirm-readback", payload, headers)

    def escalate_notice(self, notice_id, headers):
        return self._request("POST", f"/telerad/critical-notices/{notice_id}/escalate", {}, headers)

    # ---- BillingPeriod / Invoice ----
    def create_billing_period(self, payload, headers):
        return self._request("POST", "/telerad/billing-periods", payload, headers)

    def get_billing_period(self, period_id, headers):
        return self._request("GET", f"/telerad/billing-periods/{period_id}", headers=headers)

    def list_billing_periods(self, headers, params=None):
        return self._request("GET", "/telerad/billing-periods", headers=headers, params=params)

    def close_billing_period(self, period_id, headers):
        return self._request("POST", f"/telerad/billing-periods/{period_id}/close", {}, headers)

    def reopen_billing_period(self, period_id, headers):
        return self._request("POST", f"/telerad/billing-periods/{period_id}/reopen", {}, headers)

    def generate_invoice(self, period_id, payload, headers):
        return self._request("POST", f"/telerad/billing-periods/{period_id}/generate-invoice", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/telerad/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/telerad/invoices", headers=headers, params=params)


api_client = ApiClient()
