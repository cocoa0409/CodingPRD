"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Brokerage ---
    def create_brokerage(self, payload, headers):
        return self._request("POST", "/brokerages", payload, headers)

    def get_brokerage(self, brokerage_id, headers):
        return self._request("GET", f"/brokerages/{brokerage_id}", headers=headers)

    # --- Broker ---
    def create_broker(self, payload, headers):
        return self._request("POST", "/brokers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/brokers/{broker_id}", headers=headers)

    def list_brokers(self, headers, params=None):
        return self._request("GET", "/brokers", headers=headers, params=params)

    def suspend_broker(self, broker_id, headers):
        return self._request("POST", f"/brokers/{broker_id}/suspend", {}, headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_property_spaces(self, property_id, headers, params=None):
        return self._request("GET", f"/properties/{property_id}/spaces", headers=headers, params=params)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    # --- Space ---
    def create_space(self, payload, headers):
        return self._request("POST", "/spaces", payload, headers)

    def get_space(self, space_id, headers):
        return self._request("GET", f"/spaces/{space_id}", headers=headers)

    def list_spaces(self, headers, params=None):
        return self._request("GET", "/spaces", headers=headers, params=params)

    def publish_space(self, space_id, headers):
        return self._request("POST", f"/spaces/{space_id}/publish", {}, headers)

    def withdraw_space(self, space_id, headers):
        return self._request("POST", f"/spaces/{space_id}/withdraw", {}, headers)

    # --- Listing ---
    def create_listing(self, payload, headers):
        return self._request("POST", "/listings", payload, headers)

    def get_listing(self, listing_id, headers):
        return self._request("GET", f"/listings/{listing_id}", headers=headers)

    def list_listings(self, headers, params=None):
        return self._request("GET", "/listings", headers=headers, params=params)

    def activate_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/activate", {}, headers)

    def withdraw_listing(self, listing_id, headers):
        return self._request("POST", f"/listings/{listing_id}/withdraw", {}, headers)

    # --- Requirement ---
    def create_requirement(self, payload, headers):
        return self._request("POST", "/requirements", payload, headers)

    def get_requirement(self, requirement_id, headers):
        return self._request("GET", f"/requirements/{requirement_id}", headers=headers)

    def list_requirements(self, headers, params=None):
        return self._request("GET", "/requirements", headers=headers, params=params)

    def list_requirement_matches(self, requirement_id, headers, params=None):
        return self._request("GET", f"/requirements/{requirement_id}/matches", headers=headers, params=params)

    def close_requirement(self, requirement_id, headers):
        return self._request("POST", f"/requirements/{requirement_id}/close", {}, headers)

    # --- Tour ---
    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/tours", headers=headers, params=params)

    def confirm_tour(self, tour_id, headers, payload=None):
        return self._request("POST", f"/tours/{tour_id}/confirm", payload if payload is not None else {}, headers)

    def complete_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/complete", {}, headers)

    def cancel_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/cancel", {}, headers)

    def no_show_tour(self, tour_id, headers):
        return self._request("POST", f"/tours/{tour_id}/no-show", {}, headers)

    # --- Deal ---
    def create_deal(self, payload, headers):
        return self._request("POST", "/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/deals", headers=headers, params=params)

    def create_proposal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/proposals", payload, headers)

    def list_deal_proposals(self, deal_id, headers, params=None):
        return self._request("GET", f"/deals/{deal_id}/proposals", headers=headers, params=params)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/proposals", headers=headers, params=params)

    def accept_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/accept", payload, headers)

    def lease_out_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/lease-out", payload, headers)

    def execute_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/execute", payload, headers)

    def kill_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/deals/{deal_id}/kill", payload, headers)

    # --- CommissionSplit (read-only ledger) ---
    def get_commission_split(self, split_id, headers):
        return self._request("GET", f"/commission-splits/{split_id}", headers=headers)

    def list_commission_splits(self, headers, params=None):
        return self._request("GET", "/commission-splits", headers=headers, params=params)

    # --- Comp (read-only market record) ---
    def get_comp(self, comp_id, headers):
        return self._request("GET", f"/comps/{comp_id}", headers=headers)

    def list_comps(self, headers, params=None):
        return self._request("GET", "/comps", headers=headers, params=params)

    # --- Test-driving clock control ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
