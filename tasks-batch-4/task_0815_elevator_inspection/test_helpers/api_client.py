"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_period_index, headers):
        return self._request("POST", "/_clock/set", {"to_period_index": to_period_index}, headers)

    # ---- Owners ----
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ---- Inspectors ----
    def create_inspector(self, payload, headers):
        return self._request("POST", "/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"/inspectors/{inspector_id}", headers=headers)

    def list_inspectors(self, headers, params=None):
        return self._request("GET", "/inspectors", headers=headers, params=params)

    # ---- Devices ----
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def activate_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/activate", {}, headers)

    def decommission_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/decommission", {}, headers)

    # ---- Inspections ----
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    def assign_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/assign", payload, headers)

    def start_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/start", {}, headers)

    def complete_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/inspections/{inspection_id}/complete", payload, headers)

    def cancel_inspection(self, inspection_id, headers):
        return self._request("POST", f"/inspections/{inspection_id}/cancel", {}, headers)

    # ---- Deficiencies ----
    def get_deficiency(self, deficiency_id, headers):
        return self._request("GET", f"/deficiencies/{deficiency_id}", headers=headers)

    def list_deficiencies(self, headers, params=None):
        return self._request("GET", "/deficiencies", headers=headers, params=params)

    def resolve_deficiency(self, deficiency_id, headers):
        return self._request("POST", f"/deficiencies/{deficiency_id}/resolve", {}, headers)

    # ---- Citations ----
    def create_citation(self, payload, headers):
        return self._request("POST", "/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/citations", headers=headers, params=params)

    def pay_citation(self, citation_id, headers):
        return self._request("POST", f"/citations/{citation_id}/pay", {}, headers)

    def contest_citation(self, citation_id, headers):
        return self._request("POST", f"/citations/{citation_id}/contest", {}, headers)

    def resolve_contest(self, citation_id, payload, headers):
        return self._request("POST", f"/citations/{citation_id}/resolve-contest", payload, headers)

    # ---- Certificates ----
    def create_certificate(self, payload, headers):
        return self._request("POST", "/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def post_certificate(self, certificate_id, headers):
        return self._request("POST", f"/certificates/{certificate_id}/post", {}, headers)

    # ---- Out-of-service orders ----
    def create_oos_order(self, payload, headers):
        return self._request("POST", "/out-of-service-orders", payload, headers)

    def get_oos_order(self, oos_id, headers):
        return self._request("GET", f"/out-of-service-orders/{oos_id}", headers=headers)

    def list_oos_orders(self, headers, params=None):
        return self._request("GET", "/out-of-service-orders", headers=headers, params=params)

    def lift_oos_order(self, oos_id, headers):
        return self._request("POST", f"/out-of-service-orders/{oos_id}/lift", {}, headers)

    # ---- Fee invoices ----
    def create_fee_invoice(self, payload, headers):
        return self._request("POST", "/fee-invoices", payload, headers)

    def get_fee_invoice(self, invoice_id, headers):
        return self._request("GET", f"/fee-invoices/{invoice_id}", headers=headers)

    def list_fee_invoices(self, headers, params=None):
        return self._request("GET", "/fee-invoices", headers=headers, params=params)

    def pay_fee_invoice(self, invoice_id, headers):
        return self._request("POST", f"/fee-invoices/{invoice_id}/pay", {}, headers)

    # ---- Accident reports ----
    def create_accident_report(self, payload, headers):
        return self._request("POST", "/accident-reports", payload, headers)

    def get_accident_report(self, report_id, headers):
        return self._request("GET", f"/accident-reports/{report_id}", headers=headers)

    def list_accident_reports(self, headers, params=None):
        return self._request("GET", "/accident-reports", headers=headers, params=params)

    def open_investigation(self, report_id, payload, headers):
        return self._request("POST", f"/accident-reports/{report_id}/open-investigation", payload, headers)

    def close_investigation(self, report_id, payload, headers):
        return self._request("POST", f"/accident-reports/{report_id}/close", payload, headers)


api_client = ApiClient()
