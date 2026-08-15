"""API client: one method per endpoint defined in PRD §4.

All endpoints are mounted under the /coop prefix. Methods return raw
requests.Response objects so tests can assert on status codes directly.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Co-op bootstrap & clock ---
    def bootstrap(self, payload, headers):
        return self._request("POST", "/coop/bootstrap", payload, headers)

    def get_coop(self, headers):
        return self._request("GET", "/coop", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/coop/_clock/set_current_utc", payload, headers)

    def close_quarter(self, headers):
        return self._request("POST", "/coop/close_quarter", {}, headers)

    # --- Members ---
    def create_member(self, payload, headers):
        return self._request("POST", "/coop/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/coop/members", headers=headers, params=params)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/activate", {}, headers)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/suspend", {}, headers)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/reinstate", {}, headers)

    def churn_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/churn", {}, headers)

    # --- Suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/coop/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/coop/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/coop/suppliers", headers=headers, params=params)

    def onboard_supplier(self, supplier_id, headers):
        return self._request("POST", f"/coop/suppliers/{supplier_id}/onboard", {}, headers)

    def deactivate_supplier(self, supplier_id, headers):
        return self._request("POST", f"/coop/suppliers/{supplier_id}/deactivate", {}, headers)

    # --- Supplier programs ---
    def create_supplier_program(self, supplier_id, payload, headers):
        return self._request(
            "POST", f"/coop/suppliers/{supplier_id}/supplier-programs", payload, headers
        )

    def get_supplier_program(self, program_id, headers):
        return self._request("GET", f"/coop/supplier-programs/{program_id}", headers=headers)

    def list_supplier_programs(self, headers, params=None):
        return self._request("GET", "/coop/supplier-programs", headers=headers, params=params)

    def amend_supplier_program(self, program_id, payload, headers):
        return self._request("PUT", f"/coop/supplier-programs/{program_id}", payload, headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/coop/supplier-programs/{program_id}/open", {}, headers)

    def close_program_to_new(self, program_id, headers):
        return self._request(
            "POST", f"/coop/supplier-programs/{program_id}/close_to_new", {}, headers
        )

    def reopen_program(self, program_id, headers):
        return self._request("POST", f"/coop/supplier-programs/{program_id}/reopen", {}, headers)

    def terminate_program(self, program_id, headers):
        return self._request(
            "POST", f"/coop/supplier-programs/{program_id}/terminate", {}, headers
        )

    # --- Enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/coop/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/coop/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/coop/enrollments", headers=headers, params=params)

    def exit_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/coop/enrollments/{enrollment_id}/exit", {}, headers)

    # --- Purchase reports ---
    def submit_purchase_report(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/coop/enrollments/{enrollment_id}/purchase-reports", payload, headers
        )

    def get_purchase_report(self, report_id, headers):
        return self._request("GET", f"/coop/purchase-reports/{report_id}", headers=headers)

    def list_enrollment_purchase_reports(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/coop/enrollments/{enrollment_id}/purchase-reports",
            headers=headers,
            params=params,
        )

    def list_purchase_reports(self, headers, params=None):
        return self._request("GET", "/coop/purchase-reports", headers=headers, params=params)

    def list_report_volume_audits(self, report_id, headers, params=None):
        return self._request(
            "GET",
            f"/coop/purchase-reports/{report_id}/volume-audits",
            headers=headers,
            params=params,
        )

    def flag_purchase_report(self, report_id, headers):
        return self._request("POST", f"/coop/purchase-reports/{report_id}/flag", {}, headers)

    def revise_purchase_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/coop/purchase-reports/{report_id}/revise", payload, headers
        )

    # --- Volume audits ---
    def create_volume_audit(self, payload, headers):
        return self._request("POST", "/coop/volume-audits", payload, headers)

    def get_volume_audit(self, audit_id, headers):
        return self._request("GET", f"/coop/volume-audits/{audit_id}", headers=headers)

    def list_volume_audits(self, headers, params=None):
        return self._request("GET", "/coop/volume-audits", headers=headers, params=params)

    def begin_fieldwork(self, audit_id, headers):
        return self._request(
            "POST", f"/coop/volume-audits/{audit_id}/begin_fieldwork", {}, headers
        )

    def issue_findings(self, audit_id, headers):
        return self._request(
            "POST", f"/coop/volume-audits/{audit_id}/issue_findings", {}, headers
        )

    def accept_findings(self, audit_id, headers):
        return self._request(
            "POST", f"/coop/volume-audits/{audit_id}/accept_findings", {}, headers
        )

    def appeal_audit(self, audit_id, headers):
        return self._request("POST", f"/coop/volume-audits/{audit_id}/appeal", {}, headers)

    def reopen_fieldwork(self, audit_id, headers):
        return self._request(
            "POST", f"/coop/volume-audits/{audit_id}/reopen_fieldwork", {}, headers
        )

    def resolve_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/coop/volume-audits/{audit_id}/resolve", payload, headers)

    # --- Rebate accruals ---
    def get_rebate_accrual(self, accrual_id, headers):
        return self._request("GET", f"/coop/rebate-accruals/{accrual_id}", headers=headers)

    def list_rebate_accruals(self, headers, params=None):
        return self._request("GET", "/coop/rebate-accruals", headers=headers, params=params)

    # --- Quarterly distributions ---
    def create_distribution(self, headers):
        return self._request("POST", "/coop/distributions", {}, headers)

    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/coop/distributions/{distribution_id}", headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/coop/distributions", headers=headers, params=params)

    def calculate_distribution(self, distribution_id, payload, headers):
        return self._request(
            "POST", f"/coop/distributions/{distribution_id}/calculate", payload, headers
        )

    def approve_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/coop/distributions/{distribution_id}/approve", {}, headers
        )

    def disburse_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/coop/distributions/{distribution_id}/disburse", {}, headers
        )

    def reconcile_distribution(self, distribution_id, headers):
        return self._request(
            "POST", f"/coop/distributions/{distribution_id}/reconcile", {}, headers
        )

    # --- Clawback cases ---
    def get_clawback_case(self, case_id, headers):
        return self._request("GET", f"/coop/clawback-cases/{case_id}", headers=headers)

    def list_clawback_cases(self, headers, params=None):
        return self._request("GET", "/coop/clawback-cases", headers=headers, params=params)

    def notify_clawback(self, case_id, headers):
        return self._request("POST", f"/coop/clawback-cases/{case_id}/notify", {}, headers)

    def dispute_clawback(self, case_id, payload, headers):
        return self._request("POST", f"/coop/clawback-cases/{case_id}/dispute", payload, headers)

    def resolve_clawback(self, case_id, headers):
        return self._request("POST", f"/coop/clawback-cases/{case_id}/resolve", {}, headers)

    def waive_clawback(self, case_id, headers):
        return self._request("POST", f"/coop/clawback-cases/{case_id}/waive", {}, headers)

    # --- Holdback releases ---
    def get_holdback_release(self, release_id, headers):
        return self._request("GET", f"/coop/holdback-releases/{release_id}", headers=headers)

    def list_holdback_releases(self, headers, params=None):
        return self._request("GET", "/coop/holdback-releases", headers=headers, params=params)


api_client = ApiClient()
