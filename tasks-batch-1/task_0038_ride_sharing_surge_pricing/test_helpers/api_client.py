"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Zones ──
    def create_zone(self, payload, headers):
        return self._request("POST", "/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/zones", headers=headers, params=params)

    def create_surge_snapshot(self, zone_id, payload, headers):
        return self._request("POST", f"/zones/{zone_id}/surge-snapshots", payload, headers)

    def list_surge_snapshots(self, zone_id, headers, params=None):
        return self._request("GET", f"/zones/{zone_id}/surge-snapshots", headers=headers, params=params)

    def list_zone_trips(self, zone_id, headers, params=None):
        return self._request("GET", f"/zones/{zone_id}/trips", headers=headers, params=params)

    def list_zone_drivers(self, zone_id, headers, params=None):
        return self._request("GET", f"/zones/{zone_id}/drivers", headers=headers, params=params)

    def list_zone_airport_queue(self, zone_id, headers, params=None):
        return self._request("GET", f"/zones/{zone_id}/airport-queue", headers=headers, params=params)

    # ── Riders ──
    def create_rider(self, payload, headers):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/riders/{rider_id}", headers=headers)

    def list_riders(self, headers, params=None):
        return self._request("GET", "/riders", headers=headers, params=params)

    def credit_wallet(self, rider_id, payload, headers):
        return self._request("POST", f"/riders/{rider_id}/wallet/credit", payload, headers)

    # ── Drivers ──
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    def go_online(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/go-online", {}, headers)

    def go_offline(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/go-offline", {}, headers)

    # ── Trips ──
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def start_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/start", {}, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/complete", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", {}, headers)

    def expire_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/expire", {}, headers)

    # ── Dispatch tick ──
    def dispatch_tick(self, payload, headers):
        return self._request("POST", "/_dispatch/tick", payload, headers)

    # ── Airport queue ──
    def join_airport_queue(self, payload, headers):
        return self._request("POST", "/airport-queue", payload, headers)

    def get_airport_queue_entry(self, entry_id, headers):
        return self._request("GET", f"/airport-queue/{entry_id}", headers=headers)

    def list_airport_queue(self, headers, params=None):
        return self._request("GET", "/airport-queue", headers=headers, params=params)

    def withdraw_airport_queue_entry(self, entry_id, headers):
        return self._request("POST", f"/airport-queue/{entry_id}/withdraw", {}, headers)

    # ── Quests ──
    def create_quest(self, payload, headers):
        return self._request("POST", "/quests", payload, headers)

    def get_quest(self, quest_id, headers):
        return self._request("GET", f"/quests/{quest_id}", headers=headers)

    def list_quests(self, headers, params=None):
        return self._request("GET", "/quests", headers=headers, params=params)

    def expire_quest(self, quest_id, headers):
        return self._request("POST", f"/quests/{quest_id}/expire", {}, headers)

    # ── Disputes ──
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"/disputes/{dispute_id}/resolve", payload, headers)


api_client = ApiClient()
