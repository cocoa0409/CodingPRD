"""API client: one method per endpoint defined in the PRD (§4)."""
import time

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD endpoint client with connection-level retry hardening.

    Under per-test-server isolation the server is rebooted on the SAME port
    before every test. On a loaded host running many suites in lockstep, a
    fresh connection can race the kernel's teardown of the previous server
    incarnation's sockets (TIME_WAIT tuple collisions), surfacing as
    ConnectionResetError / RemoteDisconnected BEFORE the request reaches the
    server. These are transport artifacts, not application behavior, so
    connection-level failures are retried a few times. HTTP responses (any
    status) are never retried, and a genuinely dead server still fails after
    the retry budget, so no assertion semantics change.
    """

    _CONNECT_RETRIES = 4

    def _request(self, method, path, payload=None, headers=None, params=None):
        last_exc = None
        for attempt in range(self._CONNECT_RETRIES):
            try:
                return super()._request(method, path, payload=payload,
                                        headers=headers, params=params)
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                time.sleep(0.05 * (attempt + 1))
        raise last_exc

    # --- Configuration entities -------------------------------------------

    def create_vessel(self, payload, headers):
        return self._request("POST", "/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/vessels/{vessel_id}", headers=headers)

    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def create_catch_area(self, payload, headers):
        return self._request("POST", "/catch-areas", payload, headers)

    def get_catch_area(self, catch_area_id, headers):
        return self._request("GET", f"/catch-areas/{catch_area_id}", headers=headers)

    def create_species(self, payload, headers):
        return self._request("POST", "/species", payload, headers)

    def get_species(self, species_id, headers):
        return self._request("GET", f"/species/{species_id}", headers=headers)

    # --- MarketQuote -------------------------------------------------------

    def create_market_quote(self, payload, headers):
        return self._request("POST", "/market-quotes", payload, headers)

    def list_market_quotes(self, headers, params=None):
        return self._request("GET", "/market-quotes", headers=headers, params=params)

    def get_market_quote(self, quote_id, headers):
        return self._request("GET", f"/market-quotes/{quote_id}", headers=headers)

    def publish_market_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/market-quotes/{quote_id}/publish", payload, headers)

    def approve_volatility(self, quote_id, headers):
        return self._request("POST", f"/market-quotes/{quote_id}/approve-volatility", {}, headers)

    def reject_volatility(self, quote_id, headers):
        return self._request("POST", f"/market-quotes/{quote_id}/reject-volatility", {}, headers)

    # --- DockTicket --------------------------------------------------------

    def create_dock_ticket(self, payload, headers):
        return self._request("POST", "/dock-tickets", payload, headers)

    def list_dock_tickets(self, headers, params=None):
        return self._request("GET", "/dock-tickets", headers=headers, params=params)

    def get_dock_ticket(self, ticket_id, headers):
        return self._request("GET", f"/dock-tickets/{ticket_id}", headers=headers)

    def land_dock_ticket(self, ticket_id, headers):
        return self._request("POST", f"/dock-tickets/{ticket_id}/land", {}, headers)

    def settle_dock_ticket(self, ticket_id, headers):
        return self._request("POST", f"/dock-tickets/{ticket_id}/settle", {}, headers)

    def pay_dock_ticket(self, ticket_id, headers):
        return self._request("POST", f"/dock-tickets/{ticket_id}/pay", {}, headers)

    def void_dock_ticket(self, ticket_id, headers):
        return self._request("POST", f"/dock-tickets/{ticket_id}/void", {}, headers)

    def request_regrade(self, ticket_id, headers):
        return self._request("POST", f"/dock-tickets/{ticket_id}/request-regrade", {}, headers)

    # --- LandingLine -------------------------------------------------------

    def create_landing_line(self, payload, headers):
        return self._request("POST", "/landing-lines", payload, headers)

    def list_landing_lines(self, headers, params=None):
        return self._request("GET", "/landing-lines", headers=headers, params=params)

    def get_landing_line(self, line_id, headers):
        return self._request("GET", f"/landing-lines/{line_id}", headers=headers)

    # --- GradeAssessment ---------------------------------------------------

    def create_grade_assessment(self, payload, headers):
        return self._request("POST", "/grade-assessments", payload, headers)

    def finalize_grade_assessment(self, assessment_id, headers):
        return self._request("POST", f"/grade-assessments/{assessment_id}/finalize", {}, headers)

    def list_grade_assessments(self, headers, params=None):
        return self._request("GET", "/grade-assessments", headers=headers, params=params)

    def get_grade_assessment(self, assessment_id, headers):
        return self._request("GET", f"/grade-assessments/{assessment_id}", headers=headers)

    # --- InventoryLot ------------------------------------------------------

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/inventory-lots", headers=headers, params=params)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def freeze_inventory_lot(self, lot_id, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/freeze", {}, headers)

    def write_off_inventory_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/inventory-lots/{lot_id}/write-off", payload, headers)

    # --- SalesOrder --------------------------------------------------------

    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def submit_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/submit", {}, headers)

    def confirm_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/confirm", {}, headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel", {}, headers)

    def invoice_sales_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/invoice", {}, headers)

    # --- OrderLine ---------------------------------------------------------

    def create_order_line(self, payload, headers):
        return self._request("POST", "/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    # --- Allocation --------------------------------------------------------

    def create_allocation(self, payload, headers):
        return self._request("POST", "/allocations", payload, headers)

    def commit_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/commit", {}, headers)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/release", {}, headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    # --- Shipment ----------------------------------------------------------

    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def book_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/book", {}, headers)

    def tender_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/tender", payload, headers)

    def depart_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/depart", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel", {}, headers)

    # --- ImportDocument ----------------------------------------------------

    def create_import_document(self, payload, headers):
        return self._request("POST", "/import-documents", payload, headers)

    def list_import_documents(self, headers, params=None):
        return self._request("GET", "/import-documents", headers=headers, params=params)

    def get_import_document(self, doc_id, headers):
        return self._request("GET", f"/import-documents/{doc_id}", headers=headers)

    def submit_import_document(self, doc_id, headers):
        return self._request("POST", f"/import-documents/{doc_id}/submit", {}, headers)

    def clear_import_document(self, doc_id, headers):
        return self._request("POST", f"/import-documents/{doc_id}/clear", {}, headers)

    def reject_import_document(self, doc_id, headers):
        return self._request("POST", f"/import-documents/{doc_id}/reject", {}, headers)

    # --- InspectionHold ----------------------------------------------------

    def create_inspection_hold(self, payload, headers):
        return self._request("POST", "/inspection-holds", payload, headers)

    def list_inspection_holds(self, headers, params=None):
        return self._request("GET", "/inspection-holds", headers=headers, params=params)

    def get_inspection_hold(self, hold_id, headers):
        return self._request("GET", f"/inspection-holds/{hold_id}", headers=headers)

    def release_inspection_hold(self, hold_id, headers):
        return self._request("POST", f"/inspection-holds/{hold_id}/release", {}, headers)

    def condemn_inspection_hold(self, hold_id, headers):
        return self._request("POST", f"/inspection-holds/{hold_id}/condemn", {}, headers)

    # --- SubstitutionApproval ----------------------------------------------

    def create_substitution_approval(self, payload, headers):
        return self._request("POST", "/substitution-approvals", payload, headers)

    def list_substitution_approvals(self, headers, params=None):
        return self._request("GET", "/substitution-approvals", headers=headers, params=params)

    def get_substitution_approval(self, substitution_id, headers):
        return self._request("GET", f"/substitution-approvals/{substitution_id}", headers=headers)

    def approve_substitution(self, substitution_id, headers):
        return self._request("POST", f"/substitution-approvals/{substitution_id}/approve", {}, headers)

    def reject_substitution(self, substitution_id, headers):
        return self._request("POST", f"/substitution-approvals/{substitution_id}/reject", {}, headers)

    def apply_substitution(self, substitution_id, headers):
        return self._request("POST", f"/substitution-approvals/{substitution_id}/apply", {}, headers)

    # --- Logical clock (PRD §2.6) ------------------------------------------

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
