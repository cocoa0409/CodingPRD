"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical show clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Venues and union jurisdictions
    # ------------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def create_jurisdiction(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/union-jurisdictions",
                             payload, headers)

    def list_jurisdictions(self, venue_id, headers, params=None):
        return self._request("GET", f"/venues/{venue_id}/union-jurisdictions",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Warehouses
    # ------------------------------------------------------------------
    def create_warehouse(self, payload, headers):
        return self._request("POST", "/warehouses", payload, headers)

    def get_warehouse(self, warehouse_id, headers):
        return self._request("GET", f"/warehouses/{warehouse_id}", headers=headers)

    def run_storage_billing(self, warehouse_id, payload, headers):
        return self._request("POST", f"/warehouses/{warehouse_id}/storage-billing-runs",
                             payload, headers)

    # ------------------------------------------------------------------
    # Shows
    # ------------------------------------------------------------------
    def create_show(self, payload, headers):
        return self._request("POST", "/shows", payload, headers)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/shows", headers=headers, params=params)

    def set_show_status(self, show_id, payload, headers):
        return self._request("POST", f"/shows/{show_id}/status", payload, headers)

    # ------------------------------------------------------------------
    # Exhibitors
    # ------------------------------------------------------------------
    def create_exhibitor(self, payload, headers):
        return self._request("POST", "/exhibitors", payload, headers)

    def get_exhibitor(self, exhibitor_id, headers):
        return self._request("GET", f"/exhibitors/{exhibitor_id}", headers=headers)

    def set_exhibitor_status(self, exhibitor_id, payload, headers):
        return self._request("POST", f"/exhibitors/{exhibitor_id}/status",
                             payload, headers)

    # ------------------------------------------------------------------
    # Booths
    # ------------------------------------------------------------------
    def create_booth(self, payload, headers):
        return self._request("POST", "/booths", payload, headers)

    def get_booth(self, booth_id, headers):
        return self._request("GET", f"/booths/{booth_id}", headers=headers)

    def list_booths(self, headers, params=None):
        return self._request("GET", "/booths", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Exhibit assets
    # ------------------------------------------------------------------
    def create_exhibit_asset(self, payload, headers):
        return self._request("POST", "/exhibit-assets", payload, headers)

    def get_exhibit_asset(self, asset_id, headers):
        return self._request("GET", f"/exhibit-assets/{asset_id}", headers=headers)

    def list_exhibit_assets(self, headers, params=None):
        return self._request("GET", "/exhibit-assets", headers=headers, params=params)

    def asset_lifecycle(self, asset_id, payload, headers):
        return self._request("POST", f"/exhibit-assets/{asset_id}/lifecycle",
                             payload, headers)

    # ------------------------------------------------------------------
    # Exhibit designs
    # ------------------------------------------------------------------
    def create_exhibit_design(self, payload, headers):
        return self._request("POST", "/exhibit-designs", payload, headers)

    def get_exhibit_design(self, design_id, headers):
        return self._request("GET", f"/exhibit-designs/{design_id}", headers=headers)

    def list_exhibit_designs(self, headers, params=None):
        return self._request("GET", "/exhibit-designs", headers=headers, params=params)

    def quote_design(self, design_id, payload, headers):
        return self._request("POST", f"/exhibit-designs/{design_id}/quote",
                             payload, headers)

    def decide_design(self, design_id, payload, headers):
        return self._request("POST", f"/exhibit-designs/{design_id}/decision",
                             payload, headers)

    def release_design(self, design_id, headers):
        return self._request("POST", f"/exhibit-designs/{design_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Service orders
    # ------------------------------------------------------------------
    def create_service_order(self, payload, headers):
        return self._request("POST", "/service-orders", payload, headers)

    def get_service_order(self, order_id, headers):
        return self._request("GET", f"/service-orders/{order_id}", headers=headers)

    def list_service_orders(self, headers, params=None):
        return self._request("GET", "/service-orders", headers=headers, params=params)

    def list_service_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/service-orders/{order_id}/lines",
                             headers=headers, params=params)

    def service_order_fulfillment(self, order_id, payload, headers):
        return self._request("POST", f"/service-orders/{order_id}/fulfillment",
                             payload, headers)

    # ------------------------------------------------------------------
    # Crates
    # ------------------------------------------------------------------
    def create_crate(self, payload, headers):
        return self._request("POST", "/crates", payload, headers)

    def get_crate(self, crate_id, headers):
        return self._request("GET", f"/crates/{crate_id}", headers=headers)

    def list_crates(self, headers, params=None):
        return self._request("GET", "/crates", headers=headers, params=params)

    def warehouse_check_in(self, crate_id, payload, headers):
        return self._request("POST", f"/crates/{crate_id}/warehouse-check-in",
                             payload, headers)

    def move_crate(self, crate_id, payload, headers):
        return self._request("POST", f"/crates/{crate_id}/movements", payload, headers)

    # ------------------------------------------------------------------
    # Drayage shipments
    # ------------------------------------------------------------------
    def create_drayage_shipment(self, payload, headers):
        return self._request("POST", "/drayage-shipments", payload, headers)

    def get_drayage_shipment(self, shipment_id, headers):
        return self._request("GET", f"/drayage-shipments/{shipment_id}", headers=headers)

    def list_drayage_shipments(self, headers, params=None):
        return self._request("GET", "/drayage-shipments", headers=headers, params=params)

    def set_shipment_hold(self, shipment_id, payload, headers):
        return self._request("POST", f"/drayage-shipments/{shipment_id}/hold",
                             payload, headers)

    # ------------------------------------------------------------------
    # Labor calls
    # ------------------------------------------------------------------
    def create_labor_call(self, payload, headers):
        return self._request("POST", "/labor-calls", payload, headers)

    def get_labor_call(self, call_id, headers):
        return self._request("GET", f"/labor-calls/{call_id}", headers=headers)

    def list_labor_calls(self, headers, params=None):
        return self._request("GET", "/labor-calls", headers=headers, params=params)

    def dispatch_labor_call(self, call_id, headers):
        return self._request("POST", f"/labor-calls/{call_id}/dispatch", {}, headers)

    def check_in_labor_call(self, call_id, payload, headers):
        return self._request("POST", f"/labor-calls/{call_id}/check-in", payload, headers)

    def complete_labor_call(self, call_id, payload, headers):
        return self._request("POST", f"/labor-calls/{call_id}/completion",
                             payload, headers)

    def cancel_labor_call(self, call_id, payload, headers):
        return self._request("POST", f"/labor-calls/{call_id}/cancel", payload, headers)

    # ------------------------------------------------------------------
    # Change orders
    # ------------------------------------------------------------------
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def submit_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/submit",
                             {}, headers)

    def review_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/review",
                             payload, headers)

    def apply_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/apply",
                             payload, headers)

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Damage claims
    # ------------------------------------------------------------------
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/damage-claims", payload, headers)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/damage-claims/{claim_id}", headers=headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/damage-claims", headers=headers, params=params)

    def open_claim_investigation(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/investigation",
                             {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/adjudication",
                             payload, headers)

    def appeal_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/appeal", payload, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/damage-claims/{claim_id}/settlement", {}, headers)

    # ------------------------------------------------------------------
    # Refurbishment work orders
    # ------------------------------------------------------------------
    def create_refurb_work_order(self, payload, headers):
        return self._request("POST", "/refurb-work-orders", payload, headers)

    def get_refurb_work_order(self, refurb_id, headers):
        return self._request("GET", f"/refurb-work-orders/{refurb_id}", headers=headers)

    def list_refurb_work_orders(self, headers, params=None):
        return self._request("GET", "/refurb-work-orders", headers=headers, params=params)

    def refurb_progress(self, refurb_id, payload, headers):
        return self._request("POST", f"/refurb-work-orders/{refurb_id}/progress",
                             payload, headers)

    # ------------------------------------------------------------------
    # Lead capture licences
    # ------------------------------------------------------------------
    def create_lead_capture_license(self, payload, headers):
        return self._request("POST", "/lead-capture-licenses", payload, headers)

    def list_booth_lead_capture_licenses(self, booth_id, headers, params=None):
        return self._request("GET", f"/booths/{booth_id}/lead-capture-licenses",
                             headers=headers, params=params)

    def ingest_lead_batch(self, license_id, payload, headers):
        return self._request("POST", f"/lead-capture-licenses/{license_id}/lead-batches",
                             payload, headers)


api_client = ApiClient()
