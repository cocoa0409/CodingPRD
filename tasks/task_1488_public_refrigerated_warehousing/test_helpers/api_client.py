"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under the /api prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/api/customers", headers=headers, params=params)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"/api/customers/{customer_id}", payload, headers)

    # ------------------------------------------------------------------
    # Rate cards
    # ------------------------------------------------------------------
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/api/rate-cards", payload, headers)

    def get_rate_card(self, rate_card_id, headers):
        return self._request("GET", f"/api/rate-cards/{rate_card_id}", headers=headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/api/rate-cards", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Temperature zones
    # ------------------------------------------------------------------
    def create_zone(self, payload, headers):
        return self._request("POST", "/api/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/api/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/api/zones", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Inbound receipts
    # ------------------------------------------------------------------
    def create_inbound_receipt(self, payload, headers):
        return self._request("POST", "/api/inbound-receipts", payload, headers)

    def get_inbound_receipt(self, receipt_id, headers):
        return self._request(
            "GET", f"/api/inbound-receipts/{receipt_id}", headers=headers)

    def list_inbound_receipts(self, headers, params=None):
        return self._request("GET", "/api/inbound-receipts", headers=headers, params=params)

    def arrive_inbound_receipt(self, receipt_id, headers):
        return self._request(
            "POST", f"/api/inbound-receipts/{receipt_id}/arrive", {}, headers)

    def complete_inbound_receipt(self, receipt_id, payload, headers):
        return self._request(
            "POST", f"/api/inbound-receipts/{receipt_id}/complete", payload, headers)

    def cancel_inbound_receipt(self, receipt_id, headers):
        return self._request(
            "POST", f"/api/inbound-receipts/{receipt_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Lots and pallets
    # ------------------------------------------------------------------
    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/api/lots", headers=headers, params=params)

    def get_pallet(self, pallet_id, headers):
        return self._request("GET", f"/api/pallets/{pallet_id}", headers=headers)

    def list_pallets(self, headers, params=None):
        return self._request("GET", "/api/pallets", headers=headers, params=params)

    def release_pallet_quarantine(self, pallet_id, headers):
        return self._request(
            "POST", f"/api/pallets/{pallet_id}/release-quarantine", {}, headers)

    def dispose_pallet(self, pallet_id, headers):
        return self._request("POST", f"/api/pallets/{pallet_id}/dispose", {}, headers)

    # ------------------------------------------------------------------
    # Outbound orders
    # ------------------------------------------------------------------
    def create_outbound_order(self, payload, headers):
        return self._request("POST", "/api/outbound-orders", payload, headers)

    def get_outbound_order(self, order_id, headers):
        return self._request("GET", f"/api/outbound-orders/{order_id}", headers=headers)

    def list_outbound_orders(self, headers, params=None):
        return self._request("GET", "/api/outbound-orders", headers=headers, params=params)

    def submit_outbound_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/outbound-orders/{order_id}/submit", {}, headers)

    def allocate_outbound_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/outbound-orders/{order_id}/allocate", {}, headers)

    def amend_outbound_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/api/outbound-orders/{order_id}/amend", payload, headers)

    def ship_outbound_order(self, order_id, headers):
        return self._request("POST", f"/api/outbound-orders/{order_id}/ship", {}, headers)

    def cancel_outbound_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/outbound-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Allocations
    # ------------------------------------------------------------------
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/api/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/api/allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, headers):
        return self._request(
            "POST", f"/api/allocations/{allocation_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Blast-freeze cells and bookings
    # ------------------------------------------------------------------
    def create_blast_freeze_cell(self, payload, headers):
        return self._request("POST", "/api/blast-freeze-cells", payload, headers)

    def get_blast_freeze_cell(self, cell_id, headers):
        return self._request("GET", f"/api/blast-freeze-cells/{cell_id}", headers=headers)

    def list_blast_freeze_cells(self, headers, params=None):
        return self._request("GET", "/api/blast-freeze-cells", headers=headers, params=params)

    def create_blast_freeze_booking(self, payload, headers):
        return self._request("POST", "/api/blast-freeze-bookings", payload, headers)

    def get_blast_freeze_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/api/blast-freeze-bookings/{booking_id}", headers=headers)

    def list_blast_freeze_bookings(self, headers, params=None):
        return self._request(
            "GET", "/api/blast-freeze-bookings", headers=headers, params=params)

    def start_blast_freeze_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/api/blast-freeze-bookings/{booking_id}/start", {}, headers)

    def complete_blast_freeze_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/api/blast-freeze-bookings/{booking_id}/complete", {}, headers)

    def cancel_blast_freeze_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/api/blast-freeze-bookings/{booking_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Temperature excursions
    # ------------------------------------------------------------------
    def create_temperature_excursion(self, payload, headers):
        return self._request("POST", "/api/temperature-excursions", payload, headers)

    def get_temperature_excursion(self, excursion_id, headers):
        return self._request(
            "GET", f"/api/temperature-excursions/{excursion_id}", headers=headers)

    def list_temperature_excursions(self, headers, params=None):
        return self._request(
            "GET", "/api/temperature-excursions", headers=headers, params=params)

    def confirm_temperature_excursion(self, excursion_id, headers):
        return self._request(
            "POST", f"/api/temperature-excursions/{excursion_id}/confirm", {}, headers)

    def clear_temperature_excursion(self, excursion_id, headers):
        return self._request(
            "POST", f"/api/temperature-excursions/{excursion_id}/clear", {}, headers)

    # ------------------------------------------------------------------
    # Recalls
    # ------------------------------------------------------------------
    def create_recall(self, payload, headers):
        return self._request("POST", "/api/recalls", payload, headers)

    def get_recall(self, recall_id, headers):
        return self._request("GET", f"/api/recalls/{recall_id}", headers=headers)

    def list_recalls(self, headers, params=None):
        return self._request("GET", "/api/recalls", headers=headers, params=params)

    def activate_recall(self, recall_id, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/activate", {}, headers)

    def complete_recall(self, recall_id, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/complete", {}, headers)

    def cancel_recall(self, recall_id, headers):
        return self._request("POST", f"/api/recalls/{recall_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/review", {}, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/claims/{claim_id}/decide", payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/settle", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/reopen", {}, headers)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Invoices and billing
    # ------------------------------------------------------------------
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/dispute", {}, headers)

    def resolve_invoice_dispute(self, invoice_id, headers):
        return self._request(
            "POST", f"/api/invoices/{invoice_id}/resolve-dispute", {}, headers)

    def settle_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/settle", payload, headers)

    def run_billing(self, headers):
        return self._request("POST", "/api/billing/run", {}, headers)


api_client = ApiClient()
