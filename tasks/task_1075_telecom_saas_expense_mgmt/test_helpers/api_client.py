"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Vendor ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    def list_vendor_contracts(self, vendor_id, headers, params=None):
        return self._request("GET", f"/vendors/{vendor_id}/contracts", headers=headers, params=params)

    # ---- Contract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def renew_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/renew", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", {}, headers)

    def list_contract_services(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/services", headers=headers, params=params)

    def list_contract_invoices(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/invoices", headers=headers, params=params)

    def get_savings_summary(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/savings-summary", headers=headers)

    # ---- Service ----
    def create_service(self, payload, headers):
        return self._request("POST", "/services", payload, headers)

    def get_service(self, service_id, headers):
        return self._request("GET", f"/services/{service_id}", headers=headers)

    def create_recommendation(self, service_id, payload, headers):
        return self._request("POST", f"/services/{service_id}/recommendations", payload, headers)

    def list_service_recommendations(self, service_id, headers, params=None):
        return self._request("GET", f"/services/{service_id}/recommendations", headers=headers, params=params)

    # ---- Recommendation actions ----
    def implement_recommendation(self, rec_id, headers):
        return self._request("POST", f"/recommendations/{rec_id}/implement", {}, headers)

    def reject_recommendation(self, rec_id, headers):
        return self._request("POST", f"/recommendations/{rec_id}/reject", {}, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def create_line_item(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/line-items", payload, headers)

    def review_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/review", {}, headers)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/approve", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    # ---- InvoiceLineItem ----
    def get_line_item(self, line_id, headers):
        return self._request("GET", f"/invoice-line-items/{line_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/invoice-line-items", headers=headers, params=params)

    def list_line_item_disputes(self, line_id, headers, params=None):
        return self._request("GET", f"/invoice-line-items/{line_id}/disputes", headers=headers, params=params)

    def list_line_item_allocations(self, line_id, headers, params=None):
        return self._request("GET", f"/invoice-line-items/{line_id}/allocations", headers=headers, params=params)

    def create_dispute(self, line_id, payload, headers):
        return self._request("POST", f"/invoice-line-items/{line_id}/disputes", payload, headers)

    def create_allocations(self, line_id, payload, headers):
        return self._request("POST", f"/invoice-line-items/{line_id}/allocations", payload, headers)

    # ---- Dispute actions ----
    def respond_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/respond", payload, headers)

    def resubmit_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resubmit", payload, headers)

    def accept_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/accept", {}, headers)

    def withdraw_dispute(self, dispute_id, headers):
        return self._request("POST", f"/disputes/{dispute_id}/withdraw", {}, headers)

    # ---- Credit ----
    def get_credit(self, credit_id, headers):
        return self._request("GET", f"/credits/{credit_id}", headers=headers)

    def list_credits(self, headers, params=None):
        return self._request("GET", "/credits", headers=headers, params=params)

    # ---- CostCenter ----
    def create_cost_center(self, payload, headers):
        return self._request("POST", "/cost-centers", payload, headers)

    def get_cost_center(self, cc_id, headers):
        return self._request("GET", f"/cost-centers/{cc_id}", headers=headers)

    def freeze_cost_center(self, cc_id, headers):
        return self._request("POST", f"/cost-centers/{cc_id}/freeze", {}, headers)

    def list_cost_center_allocations(self, cc_id, headers, params=None):
        return self._request("GET", f"/cost-centers/{cc_id}/allocations", headers=headers, params=params)

    # ---- Allocation actions ----
    def approve_allocation(self, alloc_id, headers):
        return self._request("POST", f"/allocations/{alloc_id}/approve", {}, headers)


api_client = ApiClient()
