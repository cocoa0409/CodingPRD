"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/aog/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/aog/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/aog/customers/{customer_id}", headers=headers)

    def post_credit_adjustment(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/aog/customers/{customer_id}/credit-adjustments", payload, headers
        )

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/aog/customers/{customer_id}/suspend", {}, headers)

    def reactivate_customer(self, customer_id, headers):
        return self._request("POST", f"/aog/customers/{customer_id}/reactivate", {}, headers)

    def list_ledger_entries(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/aog/customers/{customer_id}/ledger-entries",
            headers=headers, params=params,
        )

    # --- PartMaster / InventoryUnit ---
    def create_part(self, payload, headers):
        return self._request("POST", "/aog/parts", payload, headers)

    def list_parts(self, headers, params=None):
        return self._request("GET", "/aog/parts", headers=headers, params=params)

    def get_part(self, part_id, headers):
        return self._request("GET", f"/aog/parts/{part_id}", headers=headers)

    def create_inventory_unit(self, payload, headers):
        return self._request("POST", "/aog/inventory-units", payload, headers)

    def list_inventory_units(self, headers, params=None):
        return self._request("GET", "/aog/inventory-units", headers=headers, params=params)

    def get_inventory_unit(self, unit_id, headers):
        return self._request("GET", f"/aog/inventory-units/{unit_id}", headers=headers)

    def certify_trace(self, unit_id, payload, headers):
        return self._request(
            "POST", f"/aog/inventory-units/{unit_id}/certify-trace", payload, headers
        )

    # --- AogRequest ---
    def create_aog_request(self, payload, headers):
        return self._request("POST", "/aog/aog-requests", payload, headers)

    def list_aog_requests(self, headers, params=None):
        return self._request("GET", "/aog/aog-requests", headers=headers, params=params)

    def get_aog_request(self, request_id, headers):
        return self._request("GET", f"/aog/aog-requests/{request_id}", headers=headers)

    def source_search(self, request_id, headers):
        return self._request(
            "POST", f"/aog/aog-requests/{request_id}/source-search", {}, headers
        )

    def escalate_aog_request(self, request_id, headers):
        return self._request(
            "POST", f"/aog/aog-requests/{request_id}/escalate", {}, headers
        )

    def cancel_aog_request(self, request_id, headers):
        return self._request(
            "POST", f"/aog/aog-requests/{request_id}/cancel", {}, headers
        )

    def list_request_quotes(self, request_id, headers, params=None):
        return self._request(
            "GET", f"/aog/aog-requests/{request_id}/quotes",
            headers=headers, params=params,
        )

    # --- Quote ---
    def create_quote(self, payload, headers):
        return self._request("POST", "/aog/quotes", payload, headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/aog/quotes", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/aog/quotes/{quote_id}", headers=headers)

    def issue_quote(self, quote_id, headers):
        return self._request("POST", f"/aog/quotes/{quote_id}/issue", {}, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/aog/quotes/{quote_id}/accept", payload, headers)

    def reject_quote(self, quote_id, headers):
        return self._request("POST", f"/aog/quotes/{quote_id}/reject", {}, headers)

    def revise_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/aog/quotes/{quote_id}/revise", payload, headers)

    def cancel_quote(self, quote_id, headers):
        return self._request("POST", f"/aog/quotes/{quote_id}/cancel", {}, headers)

    # --- SalesOrder / OrderLine ---
    def list_orders(self, headers, params=None):
        return self._request("GET", "/aog/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/aog/orders/{order_id}", headers=headers)

    def post_compliance_decision(self, order_id, payload, headers):
        return self._request(
            "POST", f"/aog/orders/{order_id}/compliance-decision", payload, headers
        )

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/aog/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/aog/order-lines/{line_id}", headers=headers)

    def allocate_order_line(self, line_id, payload, headers):
        return self._request(
            "POST", f"/aog/order-lines/{line_id}/allocate", payload, headers
        )

    def release_order_line(self, line_id, headers):
        return self._request("POST", f"/aog/order-lines/{line_id}/release", {}, headers)

    # --- Shipment / CharterSlot ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/aog/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/aog/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/aog/shipments/{shipment_id}", headers=headers)

    def tender_shipment(self, shipment_id, payload, headers):
        return self._request(
            "POST", f"/aog/shipments/{shipment_id}/tender", payload, headers
        )

    def deliver_shipment(self, shipment_id, headers):
        return self._request(
            "POST", f"/aog/shipments/{shipment_id}/deliver", {}, headers
        )

    def create_charter_slot(self, payload, headers):
        return self._request("POST", "/aog/charter-slots", payload, headers)

    def list_charter_slots(self, headers, params=None):
        return self._request("GET", "/aog/charter-slots", headers=headers, params=params)

    def get_charter_slot(self, slot_id, headers):
        return self._request("GET", f"/aog/charter-slots/{slot_id}", headers=headers)

    def release_charter_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/aog/charter-slots/{slot_id}/release", {}, headers
        )

    # --- CoreReturn ---
    def list_core_returns(self, headers, params=None):
        return self._request("GET", "/aog/core-returns", headers=headers, params=params)

    def get_core_return(self, core_id, headers):
        return self._request("GET", f"/aog/core-returns/{core_id}", headers=headers)

    def receive_core_return(self, core_id, payload, headers):
        return self._request(
            "POST", f"/aog/core-returns/{core_id}/receive", payload, headers
        )

    def inspect_core_return(self, core_id, payload, headers):
        return self._request(
            "POST", f"/aog/core-returns/{core_id}/inspect", payload, headers
        )

    def waive_core_penalty(self, core_id, payload, headers):
        return self._request(
            "POST", f"/aog/core-returns/{core_id}/waive-penalty", payload, headers
        )

    # --- LoanAgreement ---
    def create_loan(self, payload, headers):
        return self._request("POST", "/aog/loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/aog/loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/aog/loans/{loan_id}", headers=headers)

    def return_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/aog/loans/{loan_id}/return", payload, headers)

    # --- WarrantyClaim ---
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/aog/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/aog/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/aog/warranty-claims/{claim_id}", headers=headers)

    def review_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/aog/warranty-claims/{claim_id}/review", payload, headers
        )

    def approve_warranty_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/aog/warranty-claims/{claim_id}/approve", {}, headers
        )

    def reject_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/aog/warranty-claims/{claim_id}/reject", payload, headers
        )

    # --- ReturnAuthorization ---
    def create_return_authorization(self, payload, headers):
        return self._request("POST", "/aog/return-authorizations", payload, headers)

    def list_return_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/aog/return-authorizations", headers=headers, params=params
        )

    def get_return_authorization(self, rma_id, headers):
        return self._request(
            "GET", f"/aog/return-authorizations/{rma_id}", headers=headers
        )

    def receive_return_authorization(self, rma_id, payload, headers):
        return self._request(
            "POST", f"/aog/return-authorizations/{rma_id}/receive", payload, headers
        )

    # --- Test-driving endpoints (logical clock and operations sweep) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_sweeps(self, headers):
        return self._request("POST", "/_system/run-sweeps", {}, headers)


api_client = ApiClient()
