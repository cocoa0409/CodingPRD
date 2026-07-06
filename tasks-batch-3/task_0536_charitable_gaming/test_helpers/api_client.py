"""API client: one method per endpoint defined in the Charitable Gaming PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Organization ───────────────────────────────────────────────
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/organizations/{org_id}", headers=headers)

    def list_organization_licenses(self, org_id, headers, params=None):
        return self._request("GET", f"/organizations/{org_id}/licenses", headers=headers, params=params)

    # ─── License ────────────────────────────────────────────────────
    def create_license(self, payload, headers):
        return self._request("POST", "/licenses", payload, headers)

    def get_license(self, license_id, headers):
        return self._request("GET", f"/licenses/{license_id}", headers=headers)

    def list_license_occasions(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/occasions", headers=headers, params=params)

    def list_license_financial_reports(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/financial-reports", headers=headers, params=params)

    def list_license_violations(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/violations", headers=headers, params=params)

    def list_license_renewals(self, license_id, headers, params=None):
        return self._request("GET", f"/licenses/{license_id}/renewals", headers=headers, params=params)

    def update_license(self, license_id, payload, headers):
        return self._request("PATCH", f"/licenses/{license_id}", payload, headers)

    def submit_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/submit", {}, headers)

    def approve_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/approve", {}, headers)

    def suspend_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/suspend", {}, headers)

    def reinstate_license(self, license_id, headers):
        return self._request("POST", f"/licenses/{license_id}/reinstate", {}, headers)

    # ─── Occasion ───────────────────────────────────────────────────
    def create_occasion(self, payload, headers):
        return self._request("POST", "/occasions", payload, headers)

    def get_occasion(self, occasion_id, headers):
        return self._request("GET", f"/occasions/{occasion_id}", headers=headers)

    def list_occasion_allocations(self, occasion_id, headers, params=None):
        return self._request("GET", f"/occasions/{occasion_id}/allocations", headers=headers, params=params)

    def hold_occasion(self, occasion_id, headers):
        return self._request("POST", f"/occasions/{occasion_id}/hold", {}, headers)

    def report_occasion(self, occasion_id, payload, headers):
        return self._request("POST", f"/occasions/{occasion_id}/report", payload, headers)

    def cancel_occasion(self, occasion_id, headers):
        return self._request("POST", f"/occasions/{occasion_id}/cancel", {}, headers)

    # ─── Supplier ───────────────────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/suppliers/{supplier_id}", headers=headers)

    def list_supplier_equipment(self, supplier_id, headers, params=None):
        return self._request("GET", f"/suppliers/{supplier_id}/equipment", headers=headers, params=params)

    def register_supplier(self, supplier_id, headers):
        return self._request("POST", f"/suppliers/{supplier_id}/register", {}, headers)

    # ─── Equipment ──────────────────────────────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def list_equipment_allocations(self, equipment_id, headers, params=None):
        return self._request("GET", f"/equipment/{equipment_id}/allocations", headers=headers, params=params)

    def retire_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/retire", {}, headers)

    # ─── EquipmentAllocation ────────────────────────────────────────
    def create_equipment_allocation(self, payload, headers):
        return self._request("POST", "/equipment-allocations", payload, headers)

    def get_equipment_allocation(self, allocation_id, headers):
        return self._request("GET", f"/equipment-allocations/{allocation_id}", headers=headers)

    def release_equipment_allocation(self, allocation_id, headers):
        return self._request("POST", f"/equipment-allocations/{allocation_id}/release", {}, headers)

    # ─── FinancialReport ────────────────────────────────────────────
    def create_financial_report(self, payload, headers):
        return self._request("POST", "/financial-reports", payload, headers)

    def get_financial_report(self, report_id, headers):
        return self._request("GET", f"/financial-reports/{report_id}", headers=headers)

    def submit_financial_report(self, report_id, headers):
        return self._request("POST", f"/financial-reports/{report_id}/submit", {}, headers)

    def accept_financial_report(self, report_id, headers):
        return self._request("POST", f"/financial-reports/{report_id}/accept", {}, headers)

    def reject_financial_report(self, report_id, headers):
        return self._request("POST", f"/financial-reports/{report_id}/reject", {}, headers)

    def revise_financial_report(self, report_id, headers):
        return self._request("POST", f"/financial-reports/{report_id}/revise", {}, headers)

    # ─── Violation ──────────────────────────────────────────────────
    def create_violation(self, payload, headers):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def waive_violation(self, violation_id, headers):
        return self._request("POST", f"/violations/{violation_id}/waive", {}, headers)

    # ─── Renewal ────────────────────────────────────────────────────
    def create_renewal(self, payload, headers):
        return self._request("POST", "/renewals", payload, headers)

    def get_renewal(self, renewal_id, headers):
        return self._request("GET", f"/renewals/{renewal_id}", headers=headers)

    def approve_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/approve", {}, headers)

    def deny_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/deny", {}, headers)

    # ─── Logical clock ──────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
