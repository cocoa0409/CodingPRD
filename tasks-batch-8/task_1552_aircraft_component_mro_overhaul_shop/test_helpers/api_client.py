"""API client: one method per endpoint defined in the PRD (§4 address map)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/mro"


class ApiClient(GenericApiClient):
    # ---------------- logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # ---------------- customers ----------------
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    # ---------------- part catalog & directives ----------------
    def create_part(self, payload, headers):
        return self._request("POST", f"{PREFIX}/part-catalog", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"{PREFIX}/part-catalog/{part_id}", headers=headers)

    def create_directive(self, part_id, payload, headers):
        return self._request("POST", f"{PREFIX}/part-catalog/{part_id}/directives", payload, headers)

    def list_directives(self, part_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/part-catalog/{part_id}/directives", headers=headers, params=params)

    def list_part_units(self, part_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/part-catalog/{part_id}/units", headers=headers, params=params)

    # ---------------- component units ----------------
    def create_unit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/units", headers=headers, params=params)

    def list_customer_units(self, customer_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}/units", headers=headers, params=params)

    def list_unit_traceability(self, unit_id, headers):
        return self._request("GET", f"{PREFIX}/units/{unit_id}/traceability", headers=headers)

    # ---------------- work orders ----------------
    def create_work_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}", headers=headers)

    def list_customer_work_orders(self, customer_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}/work-orders", headers=headers, params=params)

    def list_unit_work_orders(self, unit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/units/{unit_id}/work-orders", headers=headers, params=params)

    def teardown_complete(self, work_order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/teardown-complete", payload or {}, headers)

    def create_discrepancy(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/discrepancies", payload, headers)

    def list_discrepancies(self, work_order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}/discrepancies", headers=headers, params=params)

    def disposition_discrepancy(self, discrepancy_id, payload, headers):
        return self._request("POST", f"{PREFIX}/discrepancies/{discrepancy_id}/disposition", payload, headers)

    def submit_quote(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/quote", payload, headers)

    def approve_quote(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/quote-approval", payload, headers)

    def decline_quote(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/quote-decline", payload, headers)

    def complete_repair(self, work_order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/complete-repair", payload or {}, headers)

    def record_test_results(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/test-results", payload, headers)

    def release_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/release", payload or {}, headers)

    def close_work_order(self, work_order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/close", payload or {}, headers)

    # ---------------- directive compliance ----------------
    def record_directive_compliance(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/directive-compliance", payload, headers)

    def list_directive_compliances(self, work_order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}/directive-compliances", headers=headers, params=params)

    # ---------------- parts requisitions ----------------
    def create_parts_requisition(self, work_order_id, payload, headers):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/parts-requisitions", payload, headers)

    def list_parts_requisitions(self, work_order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}/parts-requisitions", headers=headers, params=params)

    def source_approval(self, requisition_id, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-requisitions/{requisition_id}/source-approval", payload, headers)

    def pma_approval(self, requisition_id, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-requisitions/{requisition_id}/pma-approval", payload, headers)

    def receive_requisition(self, requisition_id, payload, headers):
        return self._request("POST", f"{PREFIX}/parts-requisitions/{requisition_id}/receive", payload, headers)

    def issue_requisition(self, requisition_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/parts-requisitions/{requisition_id}/issue", payload or {}, headers)

    # ---------------- test cells & bookings ----------------
    def create_test_cell(self, payload, headers):
        return self._request("POST", f"{PREFIX}/test-cells", payload, headers)

    def get_test_cell(self, test_cell_id, headers):
        return self._request("GET", f"{PREFIX}/test-cells/{test_cell_id}", headers=headers)

    def create_booking(self, test_cell_id, payload, headers):
        return self._request("POST", f"{PREFIX}/test-cells/{test_cell_id}/bookings", payload, headers)

    def list_cell_bookings(self, test_cell_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/test-cells/{test_cell_id}/bookings", headers=headers, params=params)

    def list_work_order_bookings(self, work_order_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/test-cell-bookings/{booking_id}/cancel", payload or {}, headers)

    # ---------------- 8130 certificate ----------------
    def get_work_order_certificate(self, work_order_id, headers):
        return self._request("GET", f"{PREFIX}/work-orders/{work_order_id}/certificate", headers=headers)

    # ---------------- rotable exchange pool ----------------
    def create_exchange_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exchange-agreements", payload, headers)

    def get_exchange_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/exchange-agreements/{agreement_id}", headers=headers)

    def list_exchange_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/exchange-agreements", headers=headers, params=params)

    def fulfill_exchange(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/exchange-agreements/{agreement_id}/fulfill", payload or {}, headers)

    def core_return_exchange(self, agreement_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exchange-agreements/{agreement_id}/core-return", payload, headers)

    # ---------------- lease units ----------------
    def create_lease_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/lease-agreements", payload, headers)

    def get_lease_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/lease-agreements/{agreement_id}", headers=headers)

    def list_lease_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/lease-agreements", headers=headers, params=params)

    def return_lease(self, agreement_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/lease-agreements/{agreement_id}/return", payload or {}, headers)

    # ---------------- warranty ----------------
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/warranty-claims", headers=headers, params=params)

    def review_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/warranty-claims/{claim_id}/review", payload, headers)

    # ---------------- invoices ----------------
    def generate_invoice(self, work_order_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/work-orders/{work_order_id}/invoice", payload or {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/pay", payload, headers)


api_client = ApiClient()
