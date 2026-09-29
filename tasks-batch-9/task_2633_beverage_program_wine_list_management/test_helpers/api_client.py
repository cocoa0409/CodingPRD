"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/beverage-program"


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Venues ------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", f"{PREFIX}/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/venues", headers=headers, params=params)

    # --- Cellar bins -------------------------------------------------------
    def create_cellar_bin(self, venue_id, payload, headers):
        return self._request("POST", f"{PREFIX}/venues/{venue_id}/cellar-bins",
                             payload, headers)

    def get_cellar_bin(self, bin_id, headers):
        return self._request("GET", f"{PREFIX}/cellar-bins/{bin_id}", headers=headers)

    def list_cellar_bins(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cellar-bins", headers=headers, params=params)

    # --- Distributors ------------------------------------------------------
    def create_distributor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"{PREFIX}/distributors/{distributor_id}", headers=headers)

    def list_distributors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/distributors", headers=headers, params=params)

    def create_compliance_review(self, distributor_id, payload, headers):
        return self._request("POST", f"{PREFIX}/distributors/{distributor_id}/compliance-reviews",
                             payload, headers)

    # --- Wines -------------------------------------------------------------
    def create_wine(self, payload, headers):
        return self._request("POST", f"{PREFIX}/wines", payload, headers)

    def get_wine(self, wine_id, headers):
        return self._request("GET", f"{PREFIX}/wines/{wine_id}", headers=headers)

    def list_wines(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wines", headers=headers, params=params)

    # --- Allocation offers -------------------------------------------------
    def create_allocation_offer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/allocation-offers", payload, headers)

    def get_allocation_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/allocation-offers/{offer_id}", headers=headers)

    def list_allocation_offers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/allocation-offers", headers=headers, params=params)

    def create_allocation_claim(self, offer_id, payload, headers):
        return self._request("POST", f"{PREFIX}/allocation-offers/{offer_id}/claims",
                             payload, headers)

    def allocate_offer(self, offer_id, headers):
        return self._request("POST", f"{PREFIX}/allocation-offers/{offer_id}/allocate",
                             {}, headers)

    # --- Allocation claims -------------------------------------------------
    def get_allocation_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/allocation-claims/{claim_id}", headers=headers)

    def list_allocation_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/allocation-claims", headers=headers, params=params)

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/allocation-claims/{claim_id}/withdraw",
                             {}, headers)

    def receive_claim(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/allocation-claims/{claim_id}/receive",
                             payload, headers)

    # --- Inventory lots ----------------------------------------------------
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"{PREFIX}/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inventory-lots", headers=headers, params=params)

    # --- Depletion ledger --------------------------------------------------
    def get_depletion_entry(self, depletion_entry_id, headers):
        return self._request("GET", f"{PREFIX}/depletion-entries/{depletion_entry_id}",
                             headers=headers)

    def list_depletion_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/depletion-entries", headers=headers, params=params)

    # --- Wine lists --------------------------------------------------------
    def create_wine_list(self, venue_id, payload, headers):
        return self._request("POST", f"{PREFIX}/venues/{venue_id}/wine-lists", payload, headers)

    def get_wine_list(self, wine_list_id, headers):
        return self._request("GET", f"{PREFIX}/wine-lists/{wine_list_id}", headers=headers)

    def list_wine_lists(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wine-lists", headers=headers, params=params)

    # --- List versions -----------------------------------------------------
    def create_list_version(self, wine_list_id, payload, headers):
        return self._request("POST", f"{PREFIX}/wine-lists/{wine_list_id}/versions",
                             payload, headers)

    def get_list_version(self, list_version_id, headers):
        return self._request("GET", f"{PREFIX}/list-versions/{list_version_id}", headers=headers)

    def list_list_versions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/list-versions", headers=headers, params=params)

    def submit_list_version(self, list_version_id, headers):
        return self._request("POST", f"{PREFIX}/list-versions/{list_version_id}/submit",
                             {}, headers)

    def request_changes_list_version(self, list_version_id, payload, headers):
        return self._request("POST", f"{PREFIX}/list-versions/{list_version_id}/request-changes",
                             payload, headers)

    def publish_list_version(self, list_version_id, headers):
        return self._request("POST", f"{PREFIX}/list-versions/{list_version_id}/publish",
                             {}, headers)

    def mark_reprinted_list_version(self, list_version_id, headers):
        return self._request("POST", f"{PREFIX}/list-versions/{list_version_id}/mark-reprinted",
                             {}, headers)

    def archive_list_version(self, list_version_id, headers):
        return self._request("POST", f"{PREFIX}/list-versions/{list_version_id}/archive",
                             {}, headers)

    # --- List entries ------------------------------------------------------
    def create_list_entry(self, list_version_id, payload, headers):
        return self._request("POST", f"{PREFIX}/list-versions/{list_version_id}/entries",
                             payload, headers)

    def get_list_entry(self, list_entry_id, headers):
        return self._request("GET", f"{PREFIX}/list-entries/{list_entry_id}", headers=headers)

    def list_list_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/list-entries", headers=headers, params=params)

    def patch_list_entry(self, list_entry_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/list-entries/{list_entry_id}", payload, headers)

    # --- By-the-glass slots ------------------------------------------------
    def create_btg_slot(self, payload, headers):
        return self._request("POST", f"{PREFIX}/btg-slots", payload, headers)

    def get_btg_slot(self, btg_slot_id, headers):
        return self._request("GET", f"{PREFIX}/btg-slots/{btg_slot_id}", headers=headers)

    def list_btg_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/btg-slots", headers=headers, params=params)

    def close_btg_slot(self, btg_slot_id, payload, headers):
        return self._request("POST", f"{PREFIX}/btg-slots/{btg_slot_id}/close", payload, headers)

    # --- Spoilage write-offs ----------------------------------------------
    def create_spoilage_write_off(self, payload, headers):
        return self._request("POST", f"{PREFIX}/spoilage-write-offs", payload, headers)

    def get_spoilage_write_off(self, write_off_id, headers):
        return self._request("GET", f"{PREFIX}/spoilage-write-offs/{write_off_id}", headers=headers)

    def list_spoilage_write_offs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/spoilage-write-offs", headers=headers, params=params)

    def approve_write_off(self, write_off_id, headers):
        return self._request("POST", f"{PREFIX}/spoilage-write-offs/{write_off_id}/approve",
                             {}, headers)

    def reject_write_off(self, write_off_id, payload, headers):
        return self._request("POST", f"{PREFIX}/spoilage-write-offs/{write_off_id}/reject",
                             payload, headers)

    def reverse_write_off(self, write_off_id, payload, headers):
        return self._request("POST", f"{PREFIX}/spoilage-write-offs/{write_off_id}/reverse",
                             payload, headers)

    # --- Wine dinner events ------------------------------------------------
    def create_wine_dinner_event(self, payload, headers):
        return self._request("POST", f"{PREFIX}/wine-dinner-events", payload, headers)

    def get_wine_dinner_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/wine-dinner-events/{event_id}", headers=headers)

    def list_wine_dinner_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wine-dinner-events", headers=headers, params=params)

    def price_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/wine-dinner-events/{event_id}/price", {}, headers)

    def confirm_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/wine-dinner-events/{event_id}/confirm", {}, headers)

    def settle_event(self, event_id, headers):
        return self._request("POST", f"{PREFIX}/wine-dinner-events/{event_id}/settle", {}, headers)

    def void_event_settlement(self, event_id, payload, headers):
        return self._request("POST", f"{PREFIX}/wine-dinner-events/{event_id}/void-settlement",
                             payload, headers)

    def cancel_event(self, event_id, payload, headers):
        return self._request("POST", f"{PREFIX}/wine-dinner-events/{event_id}/cancel",
                             payload, headers)

    # --- Cost governance ---------------------------------------------------
    def create_pour_cost_run(self, venue_id, payload, headers):
        return self._request("POST", f"{PREFIX}/venues/{venue_id}/pour-cost-runs", payload, headers)

    def get_pour_cost_report(self, venue_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}/pour-cost-report",
                             headers=headers, params=params)

    def get_par_report(self, venue_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}/par-report",
                             headers=headers, params=params)

    def get_variance_investigation(self, investigation_id, headers):
        return self._request("GET", f"{PREFIX}/variance-investigations/{investigation_id}",
                             headers=headers)

    def list_variance_investigations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/variance-investigations",
                             headers=headers, params=params)

    def escalate_investigation(self, investigation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/variance-investigations/{investigation_id}/escalate",
                             payload, headers)

    def resolve_investigation(self, investigation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/variance-investigations/{investigation_id}/resolve",
                             payload, headers)

    def quote_corkage(self, venue_id, payload, headers):
        return self._request("POST", f"{PREFIX}/venues/{venue_id}/corkage-charges", payload, headers)


api_client = ApiClient()
