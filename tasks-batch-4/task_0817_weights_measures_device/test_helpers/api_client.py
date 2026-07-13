"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Establishment ----
    def create_establishment(self, payload, headers):
        return self._request("POST", "/establishments", payload, headers=headers)

    def get_establishment(self, establishment_id, headers):
        return self._request("GET", f"/establishments/{establishment_id}", headers=headers)

    def suspend_establishment(self, establishment_id, headers, payload=None):
        return self._request("POST", f"/establishments/{establishment_id}/suspend", payload or {}, headers=headers)

    def reinstate_establishment(self, establishment_id, headers, payload=None):
        return self._request("POST", f"/establishments/{establishment_id}/reinstate", payload or {}, headers=headers)

    # ---- Inspector ----
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers=headers)

    # ---- Device ----
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers=headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def retire_device(self, device_id, headers, payload=None):
        return self._request("POST", f"/devices/{device_id}/retire", payload or {}, headers=headers)

    # ---- Inspection ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers=headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/start", {}, headers=headers)

    def finalize_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/finalize", {}, headers=headers)

    def create_test_reading(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/test-readings", payload, headers=headers)

    def list_test_readings(self, inspection_id, headers, params=None):
        return self._request("GET", f"/inspections/{inspection_id}/test-readings", headers=headers, params=params)

    def create_audit_item(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/audit-items", payload, headers=headers)

    def list_audit_items(self, inspection_id, headers, params=None):
        return self._request("GET", f"/inspections/{inspection_id}/audit-items", headers=headers, params=params)

    # ---- Complaint ----
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers=headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", payload, headers=headers)

    # ---- Seal ----
    def get_seal(self, seal_id, headers):
        return self._request("GET", f"/seals/{seal_id}", headers=headers)

    def list_seals(self, headers, params=None):
        return self._request("GET", "/seals", headers=headers, params=params)

    # ---- CondemnationOrder ----
    def get_condemnation(self, condemnation_id, headers):
        return self._request("GET", f"/condemnations/{condemnation_id}", headers=headers)

    def list_condemnations(self, headers, params=None):
        return self._request("GET", "/condemnations", headers=headers, params=params)

    # ---- Penalty ----
    def get_penalty(self, penalty_id, headers):
        return self._request("GET", f"/penalties/{penalty_id}", headers=headers)

    def list_penalties(self, headers, params=None):
        return self._request("GET", "/penalties", headers=headers, params=params)

    def pay_penalty(self, penalty_id, headers):
        return self._request("POST", f"/penalties/{penalty_id}/pay", {}, headers=headers)

    def waive_penalty(self, penalty_id, headers, payload=None):
        return self._request("POST", f"/penalties/{penalty_id}/waive", payload or {}, headers=headers)

    # ---- FeeInvoice ----
    def get_fee_invoice(self, fee_invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{fee_invoice_id}", headers=headers)

    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def pay_fee_invoice(self, fee_invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{fee_invoice_id}/pay", {}, headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
