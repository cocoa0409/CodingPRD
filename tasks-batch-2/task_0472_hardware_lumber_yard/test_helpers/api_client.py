"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Vendor ───────────────────────────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def deactivate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/deactivate", headers=headers)

    # ─── Product ──────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def adjust_stock(self, product_id, payload, headers):
        return self._request("POST", f"/products/{product_id}/adjust-stock", payload, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/discontinue", headers=headers)

    # ─── ContractorAccount ────────────────────────────────────────────────
    def create_contractor_account(self, payload, headers):
        return self._request("POST", "/contractor-accounts", payload, headers)

    def get_contractor_account(self, account_id, headers):
        return self._request("GET", f"/contractor-accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/contractor-accounts/{account_id}/suspend", headers=headers)

    def list_account_loyalty_ledger(self, account_id, headers, params=None):
        return self._request("GET", f"/contractor-accounts/{account_id}/loyalty-ledger",
                             headers=headers, params=params)

    def list_account_invoices(self, account_id, headers, params=None):
        return self._request("GET", f"/contractor-accounts/{account_id}/invoices",
                             headers=headers, params=params)

    # ─── SalesOrder + OrderLine ───────────────────────────────────────────
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/lines", payload, headers)

    def list_order_lines_for_order(self, order_id, headers, params=None):
        return self._request("GET", f"/sales-orders/{order_id}/lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def place_order(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/place", payload, headers)

    def fulfill_order(self, order_id, payload, headers):
        return self._request("POST", f"/sales-orders/{order_id}/fulfill", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/cancel", headers=headers)

    def invoice_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/invoice", headers=headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/pay", headers=headers)

    def void_invoice(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/void-invoice", headers=headers)

    # ─── Invoice ──────────────────────────────────────────────────────────
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    # ─── LoyaltyLedger ────────────────────────────────────────────────────
    def get_loyalty_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/loyalty-ledger/{entry_id}", headers=headers)

    def list_loyalty_ledger(self, headers, params=None):
        return self._request("GET", "/loyalty-ledger", headers=headers, params=params)

    # ─── RentalAsset + RentalAgreement ────────────────────────────────────
    def create_rental_asset(self, payload, headers):
        return self._request("POST", "/rental-assets", payload, headers)

    def get_rental_asset(self, asset_id, headers):
        return self._request("GET", f"/rental-assets/{asset_id}", headers=headers)

    def set_maintenance(self, asset_id, payload, headers):
        return self._request("POST", f"/rental-assets/{asset_id}/set-maintenance", payload, headers)

    def create_rental_agreement(self, payload, headers):
        return self._request("POST", "/rental-agreements", payload, headers)

    def get_rental_agreement(self, agreement_id, headers):
        return self._request("GET", f"/rental-agreements/{agreement_id}", headers=headers)

    def list_rental_agreements(self, headers, params=None):
        return self._request("GET", "/rental-agreements", headers=headers, params=params)

    def check_out_rental(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/check-out", headers=headers)

    def return_rental(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/return", headers=headers)

    def cancel_rental(self, agreement_id, headers):
        return self._request("POST", f"/rental-agreements/{agreement_id}/cancel", headers=headers)

    # ─── ServiceStation + ServiceTicket ───────────────────────────────────
    def create_service_station(self, payload, headers):
        return self._request("POST", "/service-stations", payload, headers)

    def get_service_station(self, station_id, headers):
        return self._request("GET", f"/service-stations/{station_id}", headers=headers)

    def set_offline(self, station_id, payload, headers):
        return self._request("POST", f"/service-stations/{station_id}/set-offline", payload, headers)

    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/service-tickets", headers=headers, params=params)

    def start_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/start", headers=headers)

    def complete_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/complete", headers=headers)

    def cancel_ticket(self, ticket_id, headers):
        return self._request("POST", f"/service-tickets/{ticket_id}/cancel", headers=headers)

    # ─── SpecialOrder ─────────────────────────────────────────────────────
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def quote_special_order(self, order_id, payload, headers):
        return self._request("POST", f"/special-orders/{order_id}/quote", payload, headers)

    def request_revision(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/request-revision", headers=headers)

    def confirm_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/confirm", headers=headers)

    def receive_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/receive", headers=headers)

    def cancel_special_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/cancel", headers=headers)

    # ─── PurchaseOrder ────────────────────────────────────────────────────
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def submit_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/submit", headers=headers)

    def receive_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/receive", headers=headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", headers=headers)

    # ─── Logical clock (test-driving) ─────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
