"""API client: one method per endpoint defined in the PRD (FOG Compliance Service).

Subclasses GenericApiClient; the base _request() handles the success/error envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers=headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_sites(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/sites",
                             headers=headers, params=params)

    def list_customer_contracts(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/contracts",
                             headers=headers, params=params)

    def close_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/close", {}, headers=headers)

    # ---- Site ----
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers=headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_site_equipment(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/equipment",
                             headers=headers, params=params)

    def list_site_compliance_reports(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/compliance-reports",
                             headers=headers, params=params)

    # ---- Equipment ----
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers=headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def list_equipment_work_orders(self, equipment_id, headers, params=None):
        return self._request("GET", f"/equipment/{equipment_id}/work-orders",
                             headers=headers, params=params)

    def decommission_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/decommission",
                             {}, headers=headers)

    # ---- ServiceContract ----
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/service-contracts", payload, headers=headers)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/service-contracts/{contract_id}", headers=headers)

    def transition_service_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/service-contracts/{contract_id}/transition",
                             payload, headers=headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/technicians", payload, headers=headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # ---- WorkOrder ----
    def create_work_order(self, payload, headers):
        return self._request("POST", "/work-orders", payload, headers=headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/work-orders", headers=headers, params=params)

    def list_work_order_manifests(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/pump-out-manifests",
                             headers=headers, params=params)

    def list_work_order_certificates(self, work_order_id, headers, params=None):
        return self._request("GET", f"/work-orders/{work_order_id}/hood-certificates",
                             headers=headers, params=params)

    def transition_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/transition",
                             payload, headers=headers)

    def complete_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/work-orders/{work_order_id}/complete",
                             payload, headers=headers)

    # ---- PumpOutManifest ----
    def create_manifest(self, payload, headers):
        return self._request("POST", "/pump-out-manifests", payload, headers=headers)

    def void_manifest(self, manifest_id, headers):
        return self._request("POST", f"/pump-out-manifests/{manifest_id}/void",
                             {}, headers=headers)

    # ---- HoodCertificate ----
    def create_hood_certificate(self, payload, headers):
        return self._request("POST", "/hood-certificates", payload, headers=headers)

    # ---- ComplianceReport ----
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/compliance-reports", payload, headers=headers)

    def submit_compliance_report(self, report_id, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/submit",
                             {}, headers=headers)

    def record_report_decision(self, report_id, payload, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/record-decision",
                             payload, headers=headers)

    def revise_compliance_report(self, report_id, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/revise",
                             {}, headers=headers)

    def transition_compliance_report(self, report_id, payload, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/transition",
                             payload, headers=headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers=headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/record-payment",
                             payload, headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers=headers)


api_client = ApiClient()
