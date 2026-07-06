"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ─── ClientSite ───────────────────────────────────────────────────────────
    def create_client_site(self, payload, headers):
        return self._request("POST", "/api/client-sites", payload, headers)

    def get_client_site(self, site_id, headers):
        return self._request("GET", f"/api/client-sites/{site_id}", headers=headers)

    def list_client_sites(self, headers, params=None):
        return self._request("GET", "/api/client-sites", headers=headers, params=params)

    def suspend_client_site(self, site_id, headers):
        return self._request("POST", f"/api/client-sites/{site_id}/suspend", headers=headers)

    def reactivate_client_site(self, site_id, headers):
        return self._request("POST", f"/api/client-sites/{site_id}/reactivate", headers=headers)

    # ─── Employee ─────────────────────────────────────────────────────────────
    def create_employee(self, payload, headers):
        return self._request("POST", "/api/employees", payload, headers)

    def get_employee(self, emp_id, headers):
        return self._request("GET", f"/api/employees/{emp_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/api/employees", headers=headers, params=params)

    def terminate_employee(self, emp_id, headers):
        return self._request("POST", f"/api/employees/{emp_id}/terminate", headers=headers)

    # ─── MenuCycle ────────────────────────────────────────────────────────────
    def create_menu_cycle(self, payload, headers):
        return self._request("POST", "/api/menu-cycles", payload, headers)

    def get_menu_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/menu-cycles/{cycle_id}", headers=headers)

    def list_menu_cycles(self, headers, params=None):
        return self._request("GET", "/api/menu-cycles", headers=headers, params=params)

    def publish_menu_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/menu-cycles/{cycle_id}/publish", headers=headers)

    # ─── MenuItem ─────────────────────────────────────────────────────────────
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/api/menu-items", payload, headers)

    def get_menu_item(self, item_id, headers):
        return self._request("GET", f"/api/menu-items/{item_id}", headers=headers)

    def list_menu_items(self, headers, params=None):
        return self._request("GET", "/api/menu-items", headers=headers, params=params)

    # ─── CateringVenue ────────────────────────────────────────────────────────
    def create_catering_venue(self, payload, headers):
        return self._request("POST", "/api/catering-venues", payload, headers)

    def get_catering_venue(self, venue_id, headers):
        return self._request("GET", f"/api/catering-venues/{venue_id}", headers=headers)

    def list_catering_venues(self, headers, params=None):
        return self._request("GET", "/api/catering-venues", headers=headers, params=params)

    # ─── ServiceSession ───────────────────────────────────────────────────────
    def create_service_session(self, payload, headers):
        return self._request("POST", "/api/service-sessions", payload, headers)

    def get_service_session(self, session_id, headers):
        return self._request("GET", f"/api/service-sessions/{session_id}", headers=headers)

    def list_service_sessions(self, headers, params=None):
        return self._request("GET", "/api/service-sessions", headers=headers, params=params)

    def lock_forecast(self, session_id, headers):
        return self._request("POST", f"/api/service-sessions/{session_id}/lock-forecast", headers=headers)

    def open_session(self, session_id, headers):
        return self._request("POST", f"/api/service-sessions/{session_id}/open", headers=headers)

    def close_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/service-sessions/{session_id}/close", payload, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/api/service-sessions/{session_id}/cancel", headers=headers)

    # ─── BadgeTransaction (POS) ───────────────────────────────────────────────
    def create_badge_transaction(self, payload, headers):
        return self._request("POST", "/api/badge-transactions", payload, headers)

    def get_badge_transaction(self, txn_id, headers):
        return self._request("GET", f"/api/badge-transactions/{txn_id}", headers=headers)

    def list_badge_transactions(self, headers, params=None):
        return self._request("GET", "/api/badge-transactions", headers=headers, params=params)

    def void_badge_transaction(self, txn_id, headers):
        return self._request("POST", f"/api/badge-transactions/{txn_id}/void", headers=headers)

    # ─── Vendor ───────────────────────────────────────────────────────────────
    def create_vendor(self, payload, headers):
        return self._request("POST", "/api/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/api/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/api/vendors", headers=headers, params=params)

    # ─── PurchaseOrder ────────────────────────────────────────────────────────
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/api/purchase-orders", payload, headers)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/api/purchase-orders/{po_id}", headers=headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/api/purchase-orders", headers=headers, params=params)

    def issue_purchase_order(self, po_id, headers):
        return self._request("POST", f"/api/purchase-orders/{po_id}/issue", headers=headers)

    def receive_purchase_order(self, po_id, headers):
        return self._request("POST", f"/api/purchase-orders/{po_id}/receive", headers=headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/api/purchase-orders/{po_id}/cancel", headers=headers)

    # ─── InventoryLot ─────────────────────────────────────────────────────────
    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/api/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/api/inventory-lots", headers=headers, params=params)

    # ─── WasteEvent ───────────────────────────────────────────────────────────
    def create_waste_event(self, payload, headers):
        return self._request("POST", "/api/waste-events", payload, headers)

    def get_waste_event(self, waste_id, headers):
        return self._request("GET", f"/api/waste-events/{waste_id}", headers=headers)

    def list_waste_events(self, headers, params=None):
        return self._request("GET", "/api/waste-events", headers=headers, params=params)

    # ─── CateringOrder ────────────────────────────────────────────────────────
    def create_catering_order(self, payload, headers):
        return self._request("POST", "/api/catering-orders", payload, headers)

    def get_catering_order(self, order_id, headers):
        return self._request("GET", f"/api/catering-orders/{order_id}", headers=headers)

    def list_catering_orders(self, headers, params=None):
        return self._request("GET", "/api/catering-orders", headers=headers, params=params)

    def submit_catering_order(self, order_id, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/submit", headers=headers)

    def review_catering_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/review", payload, headers)

    def revise_catering_order(self, order_id, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/revise", headers=headers)

    def confirm_catering_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/confirm", payload, headers)

    def fulfill_catering_order(self, order_id, payload, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/fulfill", payload, headers)

    def invoice_catering_order(self, order_id, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/invoice", headers=headers)

    def cancel_catering_order(self, order_id, headers):
        return self._request("POST", f"/api/catering-orders/{order_id}/cancel", headers=headers)

    # ─── VendorInvoice ────────────────────────────────────────────────────────
    def create_vendor_invoice(self, payload, headers):
        return self._request("POST", "/api/vendor-invoices", payload, headers)

    def get_vendor_invoice(self, inv_id, headers):
        return self._request("GET", f"/api/vendor-invoices/{inv_id}", headers=headers)

    def list_vendor_invoices(self, headers, params=None):
        return self._request("GET", "/api/vendor-invoices", headers=headers, params=params)

    def match_vendor_invoice(self, inv_id, headers):
        return self._request("POST", f"/api/vendor-invoices/{inv_id}/match", headers=headers)

    def resolve_vendor_invoice(self, inv_id, payload, headers):
        return self._request("POST", f"/api/vendor-invoices/{inv_id}/resolve", payload, headers)

    def resubmit_vendor_invoice(self, inv_id, payload, headers):
        return self._request("POST", f"/api/vendor-invoices/{inv_id}/resubmit", payload, headers)

    def pay_vendor_invoice(self, inv_id, headers):
        return self._request("POST", f"/api/vendor-invoices/{inv_id}/pay", headers=headers)

    # ─── SatisfactionSurvey ───────────────────────────────────────────────────
    def create_satisfaction_survey(self, payload, headers):
        return self._request("POST", "/api/satisfaction-surveys", payload, headers)

    def get_satisfaction_survey(self, survey_id, headers):
        return self._request("GET", f"/api/satisfaction-surveys/{survey_id}", headers=headers)

    def list_satisfaction_surveys(self, headers, params=None):
        return self._request("GET", "/api/satisfaction-surveys", headers=headers, params=params)


api_client = ApiClient()
