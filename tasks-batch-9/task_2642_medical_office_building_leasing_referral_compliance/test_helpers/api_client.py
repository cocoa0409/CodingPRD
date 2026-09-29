"""API client: one method per endpoint the PRD declares."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Buildings, suites and shared spaces -------------------------------
    def create_building(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/buildings", payload, headers)

    def get_building(self, building_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/buildings/{building_id}", headers=headers)

    def set_mix_freeze(self, building_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/buildings/{building_id}/mix-freeze", payload, headers)

    def create_suite(self, building_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/buildings/{building_id}/suites", payload, headers)

    def list_building_suites(self, building_id: str, headers: Dict[str, str],
                             params: Optional[Dict] = None):
        return self._request("GET", f"/buildings/{building_id}/suites",
                             headers=headers, params=params)

    def get_suite(self, suite_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/suites/{suite_id}", headers=headers)

    def create_shared_space(self, building_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/buildings/{building_id}/shared-spaces", payload, headers)

    def list_building_shared_spaces(self, building_id: str, headers: Dict[str, str],
                                    params: Optional[Dict] = None):
        return self._request("GET", f"/buildings/{building_id}/shared-spaces",
                             headers=headers, params=params)

    # --- Tenants -----------------------------------------------------------
    def create_tenant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/tenants", payload, headers)

    def get_tenant(self, tenant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/tenants/{tenant_id}", headers=headers)

    def list_tenant_compliance_cases(self, tenant_id: str, headers: Dict[str, str],
                                     params: Optional[Dict] = None):
        return self._request("GET", f"/tenants/{tenant_id}/compliance-cases",
                             headers=headers, params=params)

    # --- Lease lifecycle ---------------------------------------------------
    def create_lease(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def patch_lease(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/leases/{lease_id}", payload, headers)

    def withdraw_lease(self, lease_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"/leases/{lease_id}", headers=headers)

    def submit_fmv_review(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/submit-fmv-review", payload, headers)

    def lease_compliance_decision(self, lease_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/compliance-decisions", payload, headers)

    def certify_fmv(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/certify-fmv", payload, headers)

    def record_attestation(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/compliance-attestations", payload, headers)

    def execute_lease(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/execute", payload, headers)

    def commence_lease(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/commence", payload, headers)

    def terminate_lease(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/terminate", payload, headers)

    def set_after_hours_authorization(self, lease_id: str, payload: Dict[str, Any],
                                      headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/after-hours-authorization",
                             payload, headers)

    # --- Appraisals --------------------------------------------------------
    def create_appraisal(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/appraisals", payload, headers)

    def list_lease_appraisals(self, lease_id: str, headers: Dict[str, str],
                              params: Optional[Dict] = None):
        return self._request("GET", f"/leases/{lease_id}/appraisals", headers=headers, params=params)

    def decide_appraisal(self, appraisal_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/appraisals/{appraisal_id}/decision", payload, headers)

    # --- Tenant improvement ------------------------------------------------
    def create_ti_project(self, lease_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/ti-projects", payload, headers)

    def get_ti_project(self, project_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ti-projects/{project_id}", headers=headers)

    def list_ti_projects(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ti-projects", headers=headers, params=params)

    def create_ti_line_item(self, project_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/ti-projects/{project_id}/line-items", payload, headers)

    def list_ti_line_items(self, project_id: str, headers: Dict[str, str],
                           params: Optional[Dict] = None):
        return self._request("GET", f"/ti-projects/{project_id}/line-items",
                             headers=headers, params=params)

    def transition_ti_project(self, project_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", f"/ti-projects/{project_id}/transitions", payload, headers)

    def review_ti_project(self, project_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", f"/ti-projects/{project_id}/reviews", payload, headers)

    def complete_ti_project(self, project_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/ti-projects/{project_id}/complete", payload, headers)

    # --- Rent --------------------------------------------------------------
    def create_rent_invoice(self, lease_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request("POST", f"/leases/{lease_id}/rent-invoices", payload, headers)

    def list_lease_rent_invoices(self, lease_id: str, headers: Dict[str, str],
                                 params: Optional[Dict] = None):
        return self._request("GET", f"/leases/{lease_id}/rent-invoices",
                             headers=headers, params=params)

    def pay_rent_invoice(self, invoice_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", f"/rent-invoices/{invoice_id}/payments", payload, headers)

    def write_off_rent_invoice(self, invoice_id: str, payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request("POST", f"/rent-invoices/{invoice_id}/write-off", payload, headers)

    # --- Compliance cases --------------------------------------------------
    def create_compliance_case(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/compliance-cases", payload, headers)

    def transition_compliance_case(self, case_id: str, payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request("POST", f"/compliance-cases/{case_id}/transitions", payload, headers)

    # --- Shared space bookings --------------------------------------------
    def create_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/shared-space-bookings", payload, headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/shared-space-bookings", headers=headers, params=params)

    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/shared-space-bookings/{booking_id}", headers=headers)

    def cancel_booking(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/shared-space-bookings/{booking_id}/cancel",
                             payload, headers)

    # --- Parking -----------------------------------------------------------
    def create_parking_allocation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/parking-allocations", payload, headers)

    def list_parking_allocations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/parking-allocations", headers=headers, params=params)

    def get_parking_allocation(self, allocation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/parking-allocations/{allocation_id}", headers=headers)

    def revoke_parking_allocation(self, allocation_id: str, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", f"/parking-allocations/{allocation_id}/revoke",
                             payload, headers)

    # --- Logical clock and daily close ------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily_close(self, headers: Dict[str, str], payload: Optional[Dict] = None):
        return self._request("POST", "/_ops/run-daily-close", payload or {}, headers)


api_client = ApiClient()
