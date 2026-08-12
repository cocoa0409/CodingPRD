"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/api/products", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Dealer stations
    # ------------------------------------------------------------------
    def create_dealer_station(self, payload, headers):
        return self._request("POST", "/api/dealer-stations", payload, headers)

    def list_dealer_stations(self, headers, params=None):
        return self._request("GET", "/api/dealer-stations", headers=headers, params=params)

    def get_dealer_station(self, station_id, headers):
        return self._request("GET", f"/api/dealer-stations/{station_id}", headers=headers)

    def patch_dealer_station(self, station_id, payload, headers):
        return self._request("PATCH", f"/api/dealer-stations/{station_id}", payload, headers)

    def activate_dealer_station(self, station_id, headers):
        return self._request("POST", f"/api/dealer-stations/{station_id}/activate", headers=headers)

    def suspend_dealer_station(self, station_id, headers):
        return self._request("POST", f"/api/dealer-stations/{station_id}/suspend", headers=headers)

    def reactivate_dealer_station(self, station_id, headers):
        return self._request("POST", f"/api/dealer-stations/{station_id}/reactivate", headers=headers)

    def terminate_dealer_station(self, station_id, headers):
        return self._request("POST", f"/api/dealer-stations/{station_id}/terminate", headers=headers)

    def restore_credit(self, station_id, headers):
        return self._request("POST", f"/api/dealer-stations/{station_id}/restore-credit", headers=headers)

    # ------------------------------------------------------------------
    # Supply agreements
    # ------------------------------------------------------------------
    def create_supply_agreement(self, payload, headers):
        return self._request("POST", "/api/supply-agreements", payload, headers)

    def list_supply_agreements(self, headers, params=None):
        return self._request("GET", "/api/supply-agreements", headers=headers, params=params)

    def get_supply_agreement(self, agreement_id, headers):
        return self._request("GET", f"/api/supply-agreements/{agreement_id}", headers=headers)

    def patch_supply_agreement(self, agreement_id, payload, headers):
        return self._request("PATCH", f"/api/supply-agreements/{agreement_id}", payload, headers)

    def activate_supply_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/supply-agreements/{agreement_id}/activate", headers=headers)

    def start_renewal(self, agreement_id, headers):
        return self._request("POST", f"/api/supply-agreements/{agreement_id}/start-renewal", headers=headers)

    def renew_supply_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/api/supply-agreements/{agreement_id}/renew", payload, headers)

    def terminate_supply_agreement(self, agreement_id, headers):
        return self._request("POST", f"/api/supply-agreements/{agreement_id}/terminate", headers=headers)

    def get_buyout_quote(self, agreement_id, headers):
        return self._request("GET", f"/api/supply-agreements/{agreement_id}/buyout-quote", headers=headers)

    def initiate_buyout(self, agreement_id, headers):
        return self._request("POST", f"/api/supply-agreements/{agreement_id}/initiate-buyout", headers=headers)

    def execute_buyout(self, agreement_id, headers):
        return self._request("POST", f"/api/supply-agreements/{agreement_id}/execute-buyout", headers=headers)

    def cancel_buyout(self, agreement_id, headers):
        return self._request("POST", f"/api/supply-agreements/{agreement_id}/cancel-buyout", headers=headers)

    # ------------------------------------------------------------------
    # Rack price postings
    # ------------------------------------------------------------------
    def create_rack_price_posting(self, payload, headers):
        return self._request("POST", "/api/rack-price-postings", payload, headers)

    def list_rack_price_postings(self, headers, params=None):
        return self._request("GET", "/api/rack-price-postings", headers=headers, params=params)

    def get_rack_price_posting(self, posting_id, headers):
        return self._request("GET", f"/api/rack-price-postings/{posting_id}", headers=headers)

    def post_rack_price_posting(self, posting_id, headers):
        return self._request("POST", f"/api/rack-price-postings/{posting_id}/post", headers=headers)

    def supersede_rack_price_posting(self, posting_id, payload, headers):
        return self._request("POST", f"/api/rack-price-postings/{posting_id}/supersede", payload, headers)

    def discard_rack_price_posting(self, posting_id, headers):
        return self._request("POST", f"/api/rack-price-postings/{posting_id}/discard", headers=headers)

    # ------------------------------------------------------------------
    # Storage tanks / trucks
    # ------------------------------------------------------------------
    def create_storage_tank(self, payload, headers):
        return self._request("POST", "/api/storage-tanks", payload, headers)

    def list_storage_tanks(self, headers, params=None):
        return self._request("GET", "/api/storage-tanks", headers=headers, params=params)

    def get_storage_tank(self, tank_id, headers):
        return self._request("GET", f"/api/storage-tanks/{tank_id}", headers=headers)

    def gauge_storage_tank(self, tank_id, payload, headers):
        return self._request("POST", f"/api/storage-tanks/{tank_id}/gauge", payload, headers)

    def create_truck(self, payload, headers):
        return self._request("POST", "/api/trucks", payload, headers)

    def list_trucks(self, headers, params=None):
        return self._request("GET", "/api/trucks", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Transport drops
    # ------------------------------------------------------------------
    def create_transport_drop(self, payload, headers):
        return self._request("POST", "/api/transport-drops", payload, headers)

    def list_transport_drops(self, headers, params=None):
        return self._request("GET", "/api/transport-drops", headers=headers, params=params)

    def get_transport_drop(self, drop_id, headers):
        return self._request("GET", f"/api/transport-drops/{drop_id}", headers=headers)

    def schedule_transport_drop(self, drop_id, headers):
        return self._request("POST", f"/api/transport-drops/{drop_id}/schedule", headers=headers)

    def dispatch_transport_drop(self, drop_id, headers):
        return self._request("POST", f"/api/transport-drops/{drop_id}/dispatch", headers=headers)

    def deliver_transport_drop(self, drop_id, payload, headers):
        return self._request("POST", f"/api/transport-drops/{drop_id}/deliver", payload, headers)

    def fail_transport_drop(self, drop_id, payload, headers):
        return self._request("POST", f"/api/transport-drops/{drop_id}/fail", payload, headers)

    def replan_transport_drop(self, drop_id, payload, headers):
        return self._request("POST", f"/api/transport-drops/{drop_id}/replan", payload, headers)

    def reconcile_transport_drop(self, drop_id, headers):
        return self._request("POST", f"/api/transport-drops/{drop_id}/reconcile", headers=headers)

    def cancel_transport_drop(self, drop_id, headers):
        return self._request("POST", f"/api/transport-drops/{drop_id}/cancel", headers=headers)

    # ------------------------------------------------------------------
    # Meter readings
    # ------------------------------------------------------------------
    def create_meter_reading(self, payload, headers):
        return self._request("POST", "/api/meter-readings", payload, headers)

    def list_meter_readings(self, headers, params=None):
        return self._request("GET", "/api/meter-readings", headers=headers, params=params)

    def get_meter_reading(self, reading_id, headers):
        return self._request("GET", f"/api/meter-readings/{reading_id}", headers=headers)

    # ------------------------------------------------------------------
    # Loss events
    # ------------------------------------------------------------------
    def create_loss_event(self, payload, headers):
        return self._request("POST", "/api/loss-events", payload, headers)

    def list_loss_events(self, headers, params=None):
        return self._request("GET", "/api/loss-events", headers=headers, params=params)

    def get_loss_event(self, loss_id, headers):
        return self._request("GET", f"/api/loss-events/{loss_id}", headers=headers)

    def verify_loss_event(self, loss_id, headers):
        return self._request("POST", f"/api/loss-events/{loss_id}/verify", headers=headers)

    def dispute_loss_event(self, loss_id, headers):
        return self._request("POST", f"/api/loss-events/{loss_id}/dispute", headers=headers)

    def write_off_loss_event(self, loss_id, headers):
        return self._request("POST", f"/api/loss-events/{loss_id}/write-off", headers=headers)

    def void_loss_event(self, loss_id, headers):
        return self._request("POST", f"/api/loss-events/{loss_id}/void", headers=headers)

    # ------------------------------------------------------------------
    # Inventory reconciliations
    # ------------------------------------------------------------------
    def create_inventory_reconciliation(self, payload, headers):
        return self._request("POST", "/api/inventory-reconciliations", payload, headers)

    def list_inventory_reconciliations(self, headers, params=None):
        return self._request("GET", "/api/inventory-reconciliations", headers=headers, params=params)

    def get_inventory_reconciliation(self, recon_id, headers):
        return self._request("GET", f"/api/inventory-reconciliations/{recon_id}", headers=headers)

    def resolve_inventory_reconciliation(self, recon_id, payload, headers):
        return self._request("POST", f"/api/inventory-reconciliations/{recon_id}/resolve", payload, headers)

    # ------------------------------------------------------------------
    # Invoices / EFT drafts
    # ------------------------------------------------------------------
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", headers=headers)

    def create_eft_draft(self, payload, headers):
        return self._request("POST", "/api/eft-drafts", payload, headers)

    def list_eft_drafts(self, headers, params=None):
        return self._request("GET", "/api/eft-drafts", headers=headers, params=params)

    def get_eft_draft(self, draft_id, headers):
        return self._request("GET", f"/api/eft-drafts/{draft_id}", headers=headers)

    def execute_eft_draft(self, draft_id, payload, headers):
        return self._request("POST", f"/api/eft-drafts/{draft_id}/execute", payload, headers)

    def retry_eft_draft(self, draft_id, payload, headers):
        return self._request("POST", f"/api/eft-drafts/{draft_id}/retry", payload, headers)

    def cancel_eft_draft(self, draft_id, headers):
        return self._request("POST", f"/api/eft-drafts/{draft_id}/cancel", headers=headers)

    # ------------------------------------------------------------------
    # Tax remittances
    # ------------------------------------------------------------------
    def create_tax_remittance(self, payload, headers):
        return self._request("POST", "/api/tax-remittances", payload, headers)

    def list_tax_remittances(self, headers, params=None):
        return self._request("GET", "/api/tax-remittances", headers=headers, params=params)

    def get_tax_remittance(self, remittance_id, headers):
        return self._request("GET", f"/api/tax-remittances/{remittance_id}", headers=headers)

    def file_tax_remittance(self, remittance_id, headers):
        return self._request("POST", f"/api/tax-remittances/{remittance_id}/file", headers=headers)

    def pay_tax_remittance(self, remittance_id, headers):
        return self._request("POST", f"/api/tax-remittances/{remittance_id}/pay", headers=headers)

    # ------------------------------------------------------------------
    # Brand compliance audits
    # ------------------------------------------------------------------
    def create_brand_compliance_audit(self, payload, headers):
        return self._request("POST", "/api/brand-compliance-audits", payload, headers)

    def list_brand_compliance_audits(self, headers, params=None):
        return self._request("GET", "/api/brand-compliance-audits", headers=headers, params=params)

    def get_brand_compliance_audit(self, audit_id, headers):
        return self._request("GET", f"/api/brand-compliance-audits/{audit_id}", headers=headers)


api_client = ApiClient()
