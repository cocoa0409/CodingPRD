"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Brokerage ---
    def create_brokerage(self, payload, headers=None):
        return self._request("POST", "/brokerages", payload, headers=headers)

    def get_brokerage(self, brokerage_id, headers=None):
        return self._request("GET", f"/brokerages/{brokerage_id}", headers=headers)

    # --- Agent ---
    def create_agent(self, payload, headers=None):
        return self._request("POST", "/agents", payload, headers=headers)

    def get_agent(self, agent_id, headers=None):
        return self._request("GET", f"/agents/{agent_id}", headers=headers)

    def list_brokerage_agents(self, brokerage_id, headers=None, params=None):
        return self._request("GET", f"/brokerages/{brokerage_id}/agents", headers=headers, params=params)

    def suspend_agent(self, agent_id, headers=None):
        return self._request("POST", f"/agents/{agent_id}/suspend", {}, headers=headers)

    # --- Buyer ---
    def create_buyer(self, payload, headers=None):
        return self._request("POST", "/buyers", payload, headers=headers)

    def get_buyer(self, buyer_id, headers=None):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    def list_agent_buyers(self, agent_id, headers=None, params=None):
        return self._request("GET", f"/agents/{agent_id}/buyers", headers=headers, params=params)

    # --- Listing ---
    def create_listing(self, payload, headers=None):
        return self._request("POST", "/listings", payload, headers=headers)

    def get_listing(self, listing_id, headers=None):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers=None, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def activate_listing(self, listing_id, headers=None):
        return self._request("POST", f"/listings/{listing_id}/activate", {}, headers=headers)

    def withdraw_listing(self, listing_id, headers=None):
        return self._request("POST", f"/listings/{listing_id}/withdraw", {}, headers=headers)

    def close_listing(self, listing_id, payload, headers=None):
        return self._request("POST", f"/listings/{listing_id}/close", payload, headers=headers)

    def get_net_sheet(self, listing_id, headers=None):
        return self._request("GET", f"/listings/{listing_id}/net-sheet", headers=headers)

    def get_commission_ledger(self, listing_id, headers=None, params=None):
        return self._request("GET", f"/listings/{listing_id}/commission-ledger", headers=headers, params=params)

    # --- Lockbox ---
    def create_lockbox(self, listing_id, payload, headers=None):
        return self._request("POST", f"/listings/{listing_id}/lockboxes", payload, headers=headers)

    def get_lockbox(self, lockbox_id, headers=None):
        return self._request("GET", f"/lockboxes/{lockbox_id}", headers=headers)

    def list_listing_lockboxes(self, listing_id, headers=None, params=None):
        return self._request("GET", f"/listings/{listing_id}/lockboxes", headers=headers, params=params)

    def disable_lockbox(self, lockbox_id, headers=None):
        return self._request("POST", f"/lockboxes/{lockbox_id}/disable", {}, headers=headers)

    # --- ShowingAppointment ---
    def create_showing(self, lockbox_id, payload, headers=None):
        return self._request("POST", f"/lockboxes/{lockbox_id}/showings", payload, headers=headers)

    def get_showing(self, showing_id, headers=None):
        return self._request("GET", f"/showings/{showing_id}", headers=headers)

    def list_lockbox_showings(self, lockbox_id, headers=None, params=None):
        return self._request("GET", f"/lockboxes/{lockbox_id}/showings", headers=headers, params=params)

    def list_showings(self, headers=None, params=None):
        return self._request("GET", "/showings", headers=headers, params=params)

    def confirm_showing(self, showing_id, headers=None):
        return self._request("POST", f"/showings/{showing_id}/confirm", {}, headers=headers)

    def cancel_showing(self, showing_id, headers=None):
        return self._request("POST", f"/showings/{showing_id}/cancel", {}, headers=headers)

    def complete_showing(self, showing_id, headers=None):
        return self._request("POST", f"/showings/{showing_id}/complete", {}, headers=headers)

    def no_show_showing(self, showing_id, headers=None):
        return self._request("POST", f"/showings/{showing_id}/no-show", {}, headers=headers)

    # --- Offer / Counter ---
    def create_offer(self, listing_id, payload, headers=None):
        return self._request("POST", f"/listings/{listing_id}/offers", payload, headers=headers)

    def get_offer(self, offer_id, headers=None):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_listing_offers(self, listing_id, headers=None, params=None):
        return self._request("GET", f"/listings/{listing_id}/offers", headers=headers, params=params)

    def list_offers(self, headers=None, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def counter_offer(self, offer_id, payload, headers=None):
        return self._request("POST", f"/offers/{offer_id}/counter", payload, headers=headers)

    def list_offer_counters(self, offer_id, headers=None, params=None):
        return self._request("GET", f"/offers/{offer_id}/counters", headers=headers, params=params)

    def get_counter(self, counter_id, headers=None):
        return self._request("GET", f"/counters/{counter_id}", headers=headers)

    def list_counters(self, headers=None, params=None):
        return self._request("GET", "/counters", headers=headers, params=params)

    def accept_offer(self, offer_id, payload, headers=None):
        return self._request("POST", f"/offers/{offer_id}/accept", payload, headers=headers)

    def reject_offer(self, offer_id, headers=None):
        return self._request("POST", f"/offers/{offer_id}/reject", {}, headers=headers)

    def withdraw_offer(self, offer_id, headers=None):
        return self._request("POST", f"/offers/{offer_id}/withdraw", {}, headers=headers)

    # --- Contingency ---
    def get_contingency(self, contingency_id, headers=None):
        return self._request("GET", f"/contingencies/{contingency_id}", headers=headers)

    def list_offer_contingencies(self, offer_id, headers=None, params=None):
        return self._request("GET", f"/offers/{offer_id}/contingencies", headers=headers, params=params)

    def resolve_contingency(self, contingency_id, payload=None, headers=None):
        return self._request("POST", f"/contingencies/{contingency_id}/resolve", payload or {}, headers=headers)

    def waive_contingency(self, contingency_id, headers=None):
        return self._request("POST", f"/contingencies/{contingency_id}/waive", {}, headers=headers)

    def fail_contingency(self, contingency_id, headers=None):
        return self._request("POST", f"/contingencies/{contingency_id}/fail", {}, headers=headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set", payload, headers=headers)


api_client = ApiClient()
