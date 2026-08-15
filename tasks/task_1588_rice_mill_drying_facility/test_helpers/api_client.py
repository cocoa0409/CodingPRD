"""API client: one method per endpoint defined in the PRD (§4 endpoint index)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- HarvestSeason ---
    def create_season(self, payload, headers):
        return self._request("POST", "/mill/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/mill/seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/mill/seasons/{season_id}", headers=headers)

    def open_intake(self, season_id, headers):
        return self._request("POST", f"/mill/seasons/{season_id}/open-intake", {}, headers)

    def close_intake(self, season_id, headers):
        return self._request("POST", f"/mill/seasons/{season_id}/close-intake", {}, headers)

    def reopen_intake(self, season_id, headers):
        return self._request("POST", f"/mill/seasons/{season_id}/reopen-intake", {}, headers)

    def begin_settlement_review(self, season_id, headers):
        return self._request(
            "POST", f"/mill/seasons/{season_id}/begin-settlement-review", {}, headers
        )

    def settle_season(self, season_id, headers):
        return self._request("POST", f"/mill/seasons/{season_id}/settle", {}, headers)

    def set_clock(self, season_id, payload, headers):
        return self._request("POST", f"/mill/seasons/{season_id}/clock/set", payload, headers)

    def get_byproduct_inventory(self, season_id, headers):
        return self._request(
            "GET", f"/mill/seasons/{season_id}/byproduct-inventory", headers=headers
        )

    # --- Grower ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/mill/growers", payload, headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/mill/growers", headers=headers, params=params)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/mill/growers/{grower_id}", headers=headers)

    # --- DeliveryContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/mill/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/mill/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/mill/contracts/{contract_id}", headers=headers)

    def amend_contract(self, contract_id, payload, headers):
        return self._request("PUT", f"/mill/contracts/{contract_id}", payload, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/mill/contracts/{contract_id}/cancel", {}, headers)

    # --- Bin ---
    def create_bin(self, payload, headers):
        return self._request("POST", "/mill/bins", payload, headers)

    def list_bins(self, headers, params=None):
        return self._request("GET", "/mill/bins", headers=headers, params=params)

    def get_bin(self, bin_id, headers):
        return self._request("GET", f"/mill/bins/{bin_id}", headers=headers)

    # --- PaddyLot ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/mill/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/mill/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/mill/lots/{lot_id}", headers=headers)

    def grade_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/mill/lots/{lot_id}/grade", payload, headers)

    def regrade_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/mill/lots/{lot_id}/regrade", payload, headers)

    def reject_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/mill/lots/{lot_id}/reject", payload, headers)

    def store_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/mill/lots/{lot_id}/store", payload, headers)

    # --- DryingRun ---
    def create_drying_run(self, payload, headers):
        return self._request("POST", "/mill/drying-runs", payload, headers)

    def list_drying_runs(self, headers, params=None):
        return self._request("GET", "/mill/drying-runs", headers=headers, params=params)

    def get_drying_run(self, run_id, headers):
        return self._request("GET", f"/mill/drying-runs/{run_id}", headers=headers)

    def complete_drying_run(self, run_id, payload, headers):
        return self._request("POST", f"/mill/drying-runs/{run_id}/complete", payload, headers)

    def cancel_drying_run(self, run_id, headers):
        return self._request("POST", f"/mill/drying-runs/{run_id}/cancel", {}, headers)

    # --- MillRun ---
    def create_mill_run(self, payload, headers):
        return self._request("POST", "/mill/mill-runs", payload, headers)

    def list_mill_runs(self, headers, params=None):
        return self._request("GET", "/mill/mill-runs", headers=headers, params=params)

    def get_mill_run(self, run_id, headers):
        return self._request("GET", f"/mill/mill-runs/{run_id}", headers=headers)

    def start_mill_run(self, run_id, headers):
        return self._request("POST", f"/mill/mill-runs/{run_id}/start", {}, headers)

    def complete_mill_run(self, run_id, headers):
        return self._request("POST", f"/mill/mill-runs/{run_id}/complete", {}, headers)

    def verify_mill_run(self, run_id, payload, headers):
        return self._request("POST", f"/mill/mill-runs/{run_id}/verify", payload, headers)

    def void_mill_run(self, run_id, headers):
        return self._request("POST", f"/mill/mill-runs/{run_id}/void", {}, headers)

    # --- PackagingRun ---
    def create_packaging_run(self, payload, headers):
        return self._request("POST", "/mill/packaging-runs", payload, headers)

    def list_packaging_runs(self, headers, params=None):
        return self._request("GET", "/mill/packaging-runs", headers=headers, params=params)

    def get_packaging_run(self, run_id, headers):
        return self._request("GET", f"/mill/packaging-runs/{run_id}", headers=headers)

    def complete_packaging_run(self, run_id, payload, headers):
        return self._request("POST", f"/mill/packaging-runs/{run_id}/complete", payload, headers)

    def cancel_packaging_run(self, run_id, headers):
        return self._request("POST", f"/mill/packaging-runs/{run_id}/cancel", {}, headers)

    # --- ByproductSaleOrder ---
    def create_byproduct_order(self, payload, headers):
        return self._request("POST", "/mill/byproduct-orders", payload, headers)

    def list_byproduct_orders(self, headers, params=None):
        return self._request("GET", "/mill/byproduct-orders", headers=headers, params=params)

    def get_byproduct_order(self, order_id, headers):
        return self._request("GET", f"/mill/byproduct-orders/{order_id}", headers=headers)

    def reserve_byproduct_order(self, order_id, headers):
        return self._request("POST", f"/mill/byproduct-orders/{order_id}/reserve", {}, headers)

    def release_byproduct_order(self, order_id, headers):
        return self._request("POST", f"/mill/byproduct-orders/{order_id}/release", {}, headers)

    def ship_byproduct_order(self, order_id, headers):
        return self._request("POST", f"/mill/byproduct-orders/{order_id}/ship", {}, headers)

    def cancel_byproduct_order(self, order_id, headers):
        return self._request("POST", f"/mill/byproduct-orders/{order_id}/cancel", {}, headers)

    # --- FumigationEvent ---
    def create_fumigation_event(self, payload, headers):
        return self._request("POST", "/mill/fumigation-events", payload, headers)

    def list_fumigation_events(self, headers, params=None):
        return self._request("GET", "/mill/fumigation-events", headers=headers, params=params)

    def get_fumigation_event(self, event_id, headers):
        return self._request("GET", f"/mill/fumigation-events/{event_id}", headers=headers)

    def begin_aeration(self, event_id, headers):
        return self._request(
            "POST", f"/mill/fumigation-events/{event_id}/begin-aeration", {}, headers
        )

    def clear_fumigation(self, event_id, headers):
        return self._request("POST", f"/mill/fumigation-events/{event_id}/clear", {}, headers)

    # --- FoodSafetyHold ---
    def create_hold(self, payload, headers):
        return self._request("POST", "/mill/holds", payload, headers)

    def list_holds(self, headers, params=None):
        return self._request("GET", "/mill/holds", headers=headers, params=params)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/mill/holds/{hold_id}", headers=headers)

    def release_hold(self, hold_id, payload, headers):
        return self._request("POST", f"/mill/holds/{hold_id}/release", payload, headers)

    # --- Settlement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/mill/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/mill/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/mill/settlements/{settlement_id}", headers=headers)

    def issue_provisional(self, settlement_id, headers):
        return self._request(
            "POST", f"/mill/settlements/{settlement_id}/issue-provisional", {}, headers
        )

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/mill/settlements/{settlement_id}/approve", {}, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/mill/settlements/{settlement_id}/pay", {}, headers)

    def dispute_settlement(self, settlement_id, payload, headers):
        return self._request("POST", f"/mill/settlements/{settlement_id}/dispute", payload, headers)

    def revise_settlement(self, settlement_id, headers):
        return self._request("POST", f"/mill/settlements/{settlement_id}/revise", {}, headers)


api_client = ApiClient()
