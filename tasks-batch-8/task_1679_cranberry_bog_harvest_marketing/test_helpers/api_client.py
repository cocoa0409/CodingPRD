"""API client: one method per endpoint defined in the PRD (§4).

All endpoints are mounted under the /coop prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/coop/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------
    def create_season(self, payload, headers):
        return self._request("POST", "/coop/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/coop/seasons/{season_id}", headers=headers)

    def open_season(self, season_id, headers):
        return self._request("POST", f"/coop/seasons/{season_id}/open", {}, headers)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/coop/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", headers=headers)

    def transition_member(self, member_id, payload, headers):
        return self._request("POST", f"/coop/members/{member_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Member quotas
    # ------------------------------------------------------------------
    def get_quota(self, quota_id, headers):
        return self._request("GET", f"/coop/quotas/{quota_id}", headers=headers)

    def list_quotas(self, headers, params=None):
        return self._request("GET", "/coop/quotas", headers=headers, params=params)

    def patch_quota(self, quota_id, payload, headers):
        return self._request("PATCH", f"/coop/quotas/{quota_id}", payload, headers)

    # ------------------------------------------------------------------
    # Bogs
    # ------------------------------------------------------------------
    def create_bog(self, payload, headers):
        return self._request("POST", "/coop/bogs", payload, headers)

    def get_bog(self, bog_id, headers):
        return self._request("GET", f"/coop/bogs/{bog_id}", headers=headers)

    def list_bogs(self, headers, params=None):
        return self._request("GET", "/coop/bogs", headers=headers, params=params)

    def transition_bog(self, bog_id, payload, headers):
        return self._request("POST", f"/coop/bogs/{bog_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Yield estimates
    # ------------------------------------------------------------------
    def create_yield_estimate(self, payload, headers):
        return self._request("POST", "/coop/yield-estimates", payload, headers)

    def get_yield_estimate(self, estimate_id, headers):
        return self._request("GET", f"/coop/yield-estimates/{estimate_id}",
                             headers=headers)

    def list_yield_estimates(self, headers, params=None):
        return self._request("GET", "/coop/yield-estimates", headers=headers,
                             params=params)

    def transition_yield_estimate(self, estimate_id, payload, headers):
        return self._request("POST", f"/coop/yield-estimates/{estimate_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Receiving stations
    # ------------------------------------------------------------------
    def create_station(self, payload, headers):
        return self._request("POST", "/coop/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/coop/stations/{station_id}", headers=headers)

    # ------------------------------------------------------------------
    # Harvest tickets
    # ------------------------------------------------------------------
    def create_harvest_ticket(self, payload, headers):
        return self._request("POST", "/coop/harvest-tickets", payload, headers)

    def get_harvest_ticket(self, ticket_id, headers):
        return self._request("GET", f"/coop/harvest-tickets/{ticket_id}",
                             headers=headers)

    def list_harvest_tickets(self, headers, params=None):
        return self._request("GET", "/coop/harvest-tickets", headers=headers,
                             params=params)

    def transition_harvest_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/coop/harvest-tickets/{ticket_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Frost events
    # ------------------------------------------------------------------
    def create_frost_event(self, payload, headers):
        return self._request("POST", "/coop/frost-events", payload, headers)

    def get_frost_event(self, event_id, headers):
        return self._request("GET", f"/coop/frost-events/{event_id}", headers=headers)

    def list_frost_events(self, headers, params=None):
        return self._request("GET", "/coop/frost-events", headers=headers,
                             params=params)

    def transition_frost_event(self, event_id, payload, headers):
        return self._request("POST", f"/coop/frost-events/{event_id}/transition",
                             payload, headers)

    # ------------------------------------------------------------------
    # Pools
    # ------------------------------------------------------------------
    def create_pool(self, payload, headers):
        return self._request("POST", "/coop/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/coop/pools/{pool_id}", headers=headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/coop/pools", headers=headers, params=params)

    def patch_pool(self, pool_id, payload, headers):
        return self._request("PATCH", f"/coop/pools/{pool_id}", payload, headers)

    def transition_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/coop/pools/{pool_id}/transition",
                             payload, headers)

    def settle_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/coop/pools/{pool_id}/settle", payload, headers)

    # ------------------------------------------------------------------
    # Deliveries
    # ------------------------------------------------------------------
    def create_delivery(self, payload, headers):
        return self._request("POST", "/coop/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/coop/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/coop/deliveries", headers=headers, params=params)

    def receive_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/coop/deliveries/{delivery_id}/receive",
                             payload, headers)

    def grade_delivery(self, delivery_id, payload, headers):
        return self._request("POST", f"/coop/deliveries/{delivery_id}/grade",
                             payload, headers)

    def accept_delivery(self, delivery_id, headers):
        return self._request("POST", f"/coop/deliveries/{delivery_id}/accept",
                             {}, headers)

    def dispute_delivery(self, delivery_id, headers):
        return self._request("POST", f"/coop/deliveries/{delivery_id}/dispute",
                             {}, headers)

    def void_delivery(self, delivery_id, headers):
        return self._request("POST", f"/coop/deliveries/{delivery_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Patronage distributions
    # ------------------------------------------------------------------
    def get_distribution(self, distribution_id, headers):
        return self._request("GET", f"/coop/distributions/{distribution_id}",
                             headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request("GET", "/coop/distributions", headers=headers,
                             params=params)

    def transition_distribution(self, distribution_id, payload, headers):
        return self._request("POST",
                             f"/coop/distributions/{distribution_id}/transition",
                             payload, headers)


api_client = ApiClient()
