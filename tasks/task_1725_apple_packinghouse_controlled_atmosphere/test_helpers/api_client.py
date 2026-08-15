"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Growers / orchard blocks ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/growers/{grower_id}", headers=headers)

    def create_block(self, grower_id, payload, headers):
        return self._request("POST", f"/growers/{grower_id}/blocks", payload, headers)

    def list_blocks(self, grower_id, headers, params=None):
        return self._request("GET", f"/growers/{grower_id}/blocks", headers=headers, params=params)

    # --- Lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def presize_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/presize", payload, headers)

    def divert_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/divert", {}, headers)

    # --- CA rooms ---
    def create_ca_room(self, payload, headers):
        return self._request("POST", "/ca-rooms", payload, headers)

    def get_ca_room(self, room_id, headers):
        return self._request("GET", f"/ca-rooms/{room_id}", headers=headers)

    def update_ca_room_schedule(self, room_id, payload, headers):
        return self._request("PUT", f"/ca-rooms/{room_id}/schedule", payload, headers)

    def seal_ca_room(self, room_id, payload, headers):
        return self._request("POST", f"/ca-rooms/{room_id}/seal", payload, headers)

    def open_ca_room(self, room_id, headers):
        return self._request("POST", f"/ca-rooms/{room_id}/open", {}, headers)

    def create_atmosphere_reading(self, room_id, payload, headers):
        return self._request("POST", f"/ca-rooms/{room_id}/atmosphere-readings", payload, headers)

    def create_inspection(self, room_id, payload, headers):
        return self._request("POST", f"/ca-rooms/{room_id}/inspections", payload, headers)

    def list_inspections(self, room_id, headers, params=None):
        return self._request("GET", f"/ca-rooms/{room_id}/inspections", headers=headers, params=params)

    def create_allocation(self, room_id, payload, headers):
        return self._request("POST", f"/ca-rooms/{room_id}/allocations", payload, headers)

    def select_release(self, room_id, headers):
        return self._request("POST", f"/ca-rooms/{room_id}/select-release", {}, headers)

    # --- Allocations (flat) ---
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/allocations/{allocation_id}/release", {}, headers)

    # --- Packaging specs ---
    def create_spec(self, payload, headers):
        return self._request("POST", "/specs", payload, headers)

    def get_spec(self, spec_id, headers):
        return self._request("GET", f"/specs/{spec_id}", headers=headers)

    # --- Packing runs ---
    def create_packing_run(self, payload, headers):
        return self._request("POST", "/packing-runs", payload, headers)

    def get_packing_run(self, run_id, headers):
        return self._request("GET", f"/packing-runs/{run_id}", headers=headers)

    def list_packing_runs(self, headers, params=None):
        return self._request("GET", "/packing-runs", headers=headers, params=params)

    def complete_packing_run(self, run_id, payload, headers):
        return self._request("POST", f"/packing-runs/{run_id}/complete", payload, headers)

    def cancel_packing_run(self, run_id, headers):
        return self._request("POST", f"/packing-runs/{run_id}/cancel", {}, headers)

    def void_packing_run(self, run_id, headers):
        return self._request("POST", f"/packing-runs/{run_id}/void", {}, headers)

    # --- Pools ---
    def create_pool(self, payload, headers):
        return self._request("POST", "/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/pools/{pool_id}", headers=headers)

    def record_pool_sale(self, pool_id, payload, headers):
        return self._request("POST", f"/pools/{pool_id}/sales", payload, headers)

    def close_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/pools/{pool_id}/close", payload, headers)

    def reopen_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/reopen", {}, headers)

    # --- Grower settlements ---
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def pay_settlement_advance(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/advance", {}, headers)

    # --- Test-driving logical clock ---
    def set_logical_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
