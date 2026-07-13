"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Onboarding ------------------------------------------------------
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers)

    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    # --- Properties ------------------------------------------------------
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def list_property_licenses(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/rental-licenses",
                             headers=headers, params=params)

    def list_property_complaints(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/complaints",
                             headers=headers, params=params)

    def list_property_notices(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/tenant-notices",
                             headers=headers, params=params)

    # --- Rental licenses -------------------------------------------------
    def create_license(self, payload, headers):
        return self._request("POST", "/rental-licenses", payload, headers)

    def pay_license(self, license_id, payload, headers):
        return self._request("POST", f"/rental-licenses/{license_id}/pay", payload, headers)

    def renew_license(self, license_id, payload, headers):
        return self._request("POST", f"/rental-licenses/{license_id}/renew", payload, headers)

    def refund_license(self, license_id, headers, payload=None):
        return self._request("POST", f"/rental-licenses/{license_id}/refund",
                             payload if payload is not None else {}, headers)

    # --- Complaints ------------------------------------------------------
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    # --- Inspections -----------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def begin_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/begin",
                             payload if payload is not None else {}, headers)

    def create_checklist_item(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/checklist-items",
                             payload, headers)

    def list_checklist_items(self, inspection_id, headers, params=None):
        return self._request("GET", f"/inspections/{inspection_id}/checklist-items",
                             headers=headers, params=params)

    def complete_inspection(self, inspection_id, headers, payload=None):
        return self._request("POST", f"/inspections/{inspection_id}/complete",
                             payload if payload is not None else {}, headers)

    # --- Violations ------------------------------------------------------
    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/violations", headers=headers, params=params)

    def submit_remediation(self, violation_id, payload, headers):
        return self._request("POST", f"/violations/{violation_id}/submit-remediation",
                             payload, headers)

    def escalate_violation(self, violation_id, headers, payload=None):
        return self._request("POST", f"/violations/{violation_id}/escalate",
                             payload if payload is not None else {}, headers)

    # --- Tenant notices --------------------------------------------------
    def create_notice(self, payload, headers):
        return self._request("POST", "/tenant-notices", payload, headers)

    def acknowledge_notice(self, notice_id, headers, payload=None):
        return self._request("POST", f"/tenant-notices/{notice_id}/acknowledge",
                             payload if payload is not None else {}, headers)

    # --- Condemnation orders ---------------------------------------------
    def create_condemnation_order(self, payload, headers):
        return self._request("POST", "/condemnation-orders", payload, headers)

    def get_condemnation_order(self, order_id, headers):
        return self._request("GET", f"/condemnation-orders/{order_id}", headers=headers)

    def list_condemnation_orders(self, headers, params=None):
        return self._request("GET", "/condemnation-orders", headers=headers, params=params)

    def issue_condemnation_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/condemnation-orders/{order_id}/issue",
                             payload if payload is not None else {}, headers)

    # --- Logical clock (test-driving) ------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
