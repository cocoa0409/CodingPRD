"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability, PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Stations ---
    def create_station(self, payload, headers):
        return self._request("POST", "/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/stations", headers=headers, params=params)

    # --- Format clocks ---
    def create_clock(self, payload, headers):
        return self._request("POST", "/clocks", payload, headers)

    def get_clock(self, clock_id, headers):
        return self._request("GET", f"/clocks/{clock_id}", headers=headers)

    def list_clocks(self, headers, params=None):
        return self._request("GET", "/clocks", headers=headers, params=params)

    def activate_clock(self, clock_id, headers):
        return self._request("POST", f"/clocks/{clock_id}/activate", {}, headers)

    def retire_clock(self, clock_id, headers):
        return self._request("POST", f"/clocks/{clock_id}/retire", {}, headers)

    # --- Music categories ---
    def create_music_category(self, payload, headers):
        return self._request("POST", "/music-categories", payload, headers)

    def get_music_category(self, category_id, headers):
        return self._request("GET", f"/music-categories/{category_id}", headers=headers)

    def list_music_categories(self, headers, params=None):
        return self._request("GET", "/music-categories", headers=headers, params=params)

    def retire_music_category(self, category_id, headers):
        return self._request("POST", f"/music-categories/{category_id}/retire", {}, headers)

    # --- Songs ---
    def create_song(self, payload, headers):
        return self._request("POST", "/songs", payload, headers)

    def get_song(self, song_id, headers):
        return self._request("GET", f"/songs/{song_id}", headers=headers)

    def list_songs(self, headers, params=None):
        return self._request("GET", "/songs", headers=headers, params=params)

    def retire_song(self, song_id, headers):
        return self._request("POST", f"/songs/{song_id}/retire", {}, headers)

    # --- Ratings books ---
    def create_ratings_book(self, payload, headers):
        return self._request("POST", "/ratings-books", payload, headers)

    def get_ratings_book(self, book_id, headers):
        return self._request("GET", f"/ratings-books/{book_id}", headers=headers)

    def list_ratings_books(self, headers, params=None):
        return self._request("GET", "/ratings-books", headers=headers, params=params)

    def publish_ratings_book(self, book_id, headers):
        return self._request("POST", f"/ratings-books/{book_id}/publish", {}, headers)

    # --- Rate card entries ---
    def create_rate_card_entry(self, payload, headers):
        return self._request("POST", "/rate-card-entries", payload, headers)

    def get_rate_card_entry(self, entry_id, headers):
        return self._request("GET", f"/rate-card-entries/{entry_id}", headers=headers)

    def list_rate_card_entries(self, headers, params=None):
        return self._request("GET", "/rate-card-entries", headers=headers, params=params)

    def retire_rate_card_entry(self, entry_id, headers):
        return self._request("POST", f"/rate-card-entries/{entry_id}/retire", {}, headers)

    # --- Syndication clearances ---
    def create_clearance(self, payload, headers):
        return self._request("POST", "/clearances", payload, headers)

    def get_clearance(self, clearance_id, headers):
        return self._request("GET", f"/clearances/{clearance_id}", headers=headers)

    def list_clearances(self, headers, params=None):
        return self._request("GET", "/clearances", headers=headers, params=params)

    def clear_clearance(self, clearance_id, headers):
        return self._request("POST", f"/clearances/{clearance_id}/clear", {}, headers)

    def disaffirm_clearance(self, clearance_id, headers):
        return self._request("POST", f"/clearances/{clearance_id}/disaffirm", {}, headers)

    # --- Trade agreements / ledger ---
    def create_trade_agreement(self, payload, headers):
        return self._request("POST", "/trade-agreements", payload, headers)

    def get_trade_agreement(self, agreement_id, headers):
        return self._request("GET", f"/trade-agreements/{agreement_id}", headers=headers)

    def list_trade_agreements(self, headers, params=None):
        return self._request("GET", "/trade-agreements", headers=headers, params=params)

    def suspend_trade_agreement(self, agreement_id, headers):
        return self._request("POST", f"/trade-agreements/{agreement_id}/suspend", {}, headers)

    def close_trade_agreement(self, agreement_id, headers):
        return self._request("POST", f"/trade-agreements/{agreement_id}/close", {}, headers)

    def append_ledger_entry(self, agreement_id, payload, headers):
        return self._request("POST", f"/trade-agreements/{agreement_id}/ledger-entries", payload, headers)

    def list_agreement_ledger_entries(self, agreement_id, headers, params=None):
        return self._request("GET", f"/trade-agreements/{agreement_id}/ledger-entries", headers=headers, params=params)

    def list_spot_ledger_entries(self, spot_id, headers, params=None):
        return self._request("GET", f"/spots/{spot_id}/ledger-entries", headers=headers, params=params)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/submit", {}, headers)

    def approve_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/approve", {}, headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reject", {}, headers)

    def activate_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/activate", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def complete_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/complete", {}, headers)

    # --- Daily logs ---
    def create_log(self, payload, headers):
        return self._request("POST", "/logs", payload, headers)

    def get_log(self, log_id, headers):
        return self._request("GET", f"/logs/{log_id}", headers=headers)

    def list_logs(self, headers, params=None):
        return self._request("GET", "/logs", headers=headers, params=params)

    def lock_log(self, log_id, payload, headers):
        return self._request("POST", f"/logs/{log_id}/lock", payload, headers)

    def place_music(self, log_id, payload, headers):
        return self._request("POST", f"/logs/{log_id}/music-placements", payload, headers)

    def as_run_import(self, log_id, payload, headers):
        return self._request("POST", f"/logs/{log_id}/as-run-import", payload, headers)

    def begin_reconciliation(self, log_id, headers):
        return self._request("POST", f"/logs/{log_id}/begin-reconciliation", {}, headers)

    def reopen_log(self, log_id, headers):
        return self._request("POST", f"/logs/{log_id}/reopen", {}, headers)

    def reconcile_log(self, log_id, headers):
        return self._request("POST", f"/logs/{log_id}/reconcile", {}, headers)

    def issue_affidavit(self, log_id, headers):
        return self._request("POST", f"/logs/{log_id}/issue-affidavit", {}, headers)

    def close_log(self, log_id, headers):
        return self._request("POST", f"/logs/{log_id}/close", {}, headers)

    # --- Spots ---
    def create_spot(self, payload, headers):
        return self._request("POST", "/spots", payload, headers)

    def get_spot(self, spot_id, headers):
        return self._request("GET", f"/spots/{spot_id}", headers=headers)

    def list_spots(self, headers, params=None):
        return self._request("GET", "/spots", headers=headers, params=params)

    def cancel_spot(self, spot_id, headers):
        return self._request("POST", f"/spots/{spot_id}/cancel", {}, headers)

    def reschedule_spot(self, spot_id, payload, headers):
        return self._request("POST", f"/spots/{spot_id}/reschedule", payload, headers)

    def issue_spot_credit(self, spot_id, payload, headers):
        return self._request("POST", f"/spots/{spot_id}/issue-credit", payload, headers)

    # --- Barter avails ---
    def create_barter_avail(self, payload, headers):
        return self._request("POST", "/barter-avails", payload, headers)

    def get_barter_avail(self, avail_id, headers):
        return self._request("GET", f"/barter-avails/{avail_id}", headers=headers)

    def list_barter_avails(self, headers, params=None):
        return self._request("GET", "/barter-avails", headers=headers, params=params)

    # --- Endorsement contracts ---
    def create_endorsement_contract(self, payload, headers):
        return self._request("POST", "/endorsement-contracts", payload, headers)

    def get_endorsement_contract(self, contract_id, headers):
        return self._request("GET", f"/endorsement-contracts/{contract_id}", headers=headers)

    def list_endorsement_contracts(self, headers, params=None):
        return self._request("GET", "/endorsement-contracts", headers=headers, params=params)

    def activate_endorsement_contract(self, contract_id, headers):
        return self._request("POST", f"/endorsement-contracts/{contract_id}/activate", {}, headers)

    def close_endorsement_contract(self, contract_id, headers):
        return self._request("POST", f"/endorsement-contracts/{contract_id}/close", {}, headers)

    def cancel_endorsement_contract(self, contract_id, headers):
        return self._request("POST", f"/endorsement-contracts/{contract_id}/cancel", {}, headers)

    # --- Live reads ---
    def create_live_read(self, payload, headers):
        return self._request("POST", "/live-reads", payload, headers)

    def get_live_read(self, live_read_id, headers):
        return self._request("GET", f"/live-reads/{live_read_id}", headers=headers)

    def list_live_reads(self, headers, params=None):
        return self._request("GET", "/live-reads", headers=headers, params=params)

    def reschedule_live_read(self, live_read_id, payload, headers):
        return self._request("POST", f"/live-reads/{live_read_id}/reschedule", payload, headers)

    def issue_live_read_credit(self, live_read_id, payload, headers):
        return self._request("POST", f"/live-reads/{live_read_id}/issue-credit", payload, headers)

    # --- Discrepancies ---
    def get_discrepancy(self, discrepancy_id, headers):
        return self._request("GET", f"/discrepancies/{discrepancy_id}", headers=headers)

    def list_discrepancies(self, headers, params=None):
        return self._request("GET", "/discrepancies", headers=headers, params=params)

    def resolve_discrepancy(self, discrepancy_id, payload, headers):
        return self._request("POST", f"/discrepancies/{discrepancy_id}/resolve", payload, headers)

    def waive_discrepancy(self, discrepancy_id, payload, headers):
        return self._request("POST", f"/discrepancies/{discrepancy_id}/waive", payload, headers)

    # --- Remote events ---
    def create_remote_event(self, payload, headers):
        return self._request("POST", "/remote-events", payload, headers)

    def get_remote_event(self, event_id, headers):
        return self._request("GET", f"/remote-events/{event_id}", headers=headers)

    def list_remote_events(self, headers, params=None):
        return self._request("GET", "/remote-events", headers=headers, params=params)

    def confirm_remote_event(self, event_id, headers):
        return self._request("POST", f"/remote-events/{event_id}/confirm", {}, headers)

    def cancel_remote_event(self, event_id, headers):
        return self._request("POST", f"/remote-events/{event_id}/cancel", {}, headers)

    def settle_remote_event(self, event_id, headers):
        return self._request("POST", f"/remote-events/{event_id}/settle", {}, headers)


api_client = ApiClient()
