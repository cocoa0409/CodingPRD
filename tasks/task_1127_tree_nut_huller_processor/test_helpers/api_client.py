"""API client: one method per endpoint defined in the PRD (Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- growers ---
    def create_grower(self, payload, headers):
        return self._request("POST", "/growers", payload, headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/growers", headers=headers, params=params)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/growers/{grower_id}", headers=headers)

    # --- buyers ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/buyers", payload, headers)

    def list_buyers(self, headers, params=None):
        return self._request("GET", "/buyers", headers=headers, params=params)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/buyers/{buyer_id}", headers=headers)

    # --- lots ---
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def route_lot(self, lot_id, payload, headers):
        return self._request("POST", f"/lots/{lot_id}/route", payload, headers)

    def resample_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/resample", {}, headers)

    def dispose_lot(self, lot_id, headers):
        return self._request("POST", f"/lots/{lot_id}/dispose", {}, headers)

    # --- lab tests ---
    def create_lab_test(self, payload, headers):
        return self._request("POST", "/lab-tests", payload, headers)

    def list_lab_tests(self, headers, params=None):
        return self._request("GET", "/lab-tests", headers=headers, params=params)

    def get_lab_test(self, test_id, headers):
        return self._request("GET", f"/lab-tests/{test_id}", headers=headers)

    # --- processing runs ---
    def create_processing_run(self, payload, headers):
        return self._request("POST", "/processing-runs", payload, headers)

    def list_processing_runs(self, headers, params=None):
        return self._request("GET", "/processing-runs", headers=headers, params=params)

    def get_processing_run(self, run_id, headers):
        return self._request("GET", f"/processing-runs/{run_id}", headers=headers)

    def start_processing_run(self, run_id, headers):
        return self._request("POST", f"/processing-runs/{run_id}/start", {}, headers)

    def complete_processing_run(self, run_id, payload, headers):
        return self._request("POST", f"/processing-runs/{run_id}/complete", payload, headers)

    def cancel_processing_run(self, run_id, headers):
        return self._request("POST", f"/processing-runs/{run_id}/cancel", {}, headers)

    # --- dryers ---
    def create_dryer(self, payload, headers):
        return self._request("POST", "/dryers", payload, headers)

    def list_dryers(self, headers, params=None):
        return self._request("GET", "/dryers", headers=headers, params=params)

    # --- drying batches ---
    def create_drying_batch(self, payload, headers):
        return self._request("POST", "/drying-batches", payload, headers)

    def list_drying_batches(self, headers, params=None):
        return self._request("GET", "/drying-batches", headers=headers, params=params)

    def get_drying_batch(self, batch_id, headers):
        return self._request("GET", f"/drying-batches/{batch_id}", headers=headers)

    def start_drying_batch(self, batch_id, headers):
        return self._request("POST", f"/drying-batches/{batch_id}/start", {}, headers)

    def complete_drying_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/drying-batches/{batch_id}/complete", payload, headers)

    def cancel_drying_batch(self, batch_id, headers):
        return self._request("POST", f"/drying-batches/{batch_id}/cancel", {}, headers)

    # --- bins ---
    def create_bin(self, payload, headers):
        return self._request("POST", "/bins", payload, headers)

    def list_bins(self, headers, params=None):
        return self._request("GET", "/bins", headers=headers, params=params)

    def get_bin(self, bin_id, headers):
        return self._request("GET", f"/bins/{bin_id}", headers=headers)

    # --- placements ---
    def create_placement(self, payload, headers):
        return self._request("POST", "/placements", payload, headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", "/placements", headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/placements/{placement_id}", headers=headers)

    # --- withdrawals ---
    def create_withdrawal(self, payload, headers):
        return self._request("POST", "/withdrawals", payload, headers)

    def list_withdrawals(self, headers, params=None):
        return self._request("GET", "/withdrawals", headers=headers, params=params)

    def get_withdrawal(self, withdrawal_id, headers):
        return self._request("GET", f"/withdrawals/{withdrawal_id}", headers=headers)

    # --- fumigations ---
    def create_fumigation(self, payload, headers):
        return self._request("POST", "/fumigations", payload, headers)

    def list_fumigations(self, headers, params=None):
        return self._request("GET", "/fumigations", headers=headers, params=params)

    def get_fumigation(self, fumigation_id, headers):
        return self._request("GET", f"/fumigations/{fumigation_id}", headers=headers)

    def start_fumigation(self, fumigation_id, headers):
        return self._request("POST", f"/fumigations/{fumigation_id}/start", {}, headers)

    def begin_aeration_fumigation(self, fumigation_id, headers):
        return self._request("POST", f"/fumigations/{fumigation_id}/begin-aeration", {}, headers)

    def cancel_fumigation(self, fumigation_id, headers):
        return self._request("POST", f"/fumigations/{fumigation_id}/cancel", {}, headers)

    # --- contracts ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def suspend_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/suspend", {}, headers)

    def resume_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/resume", {}, headers)

    def close_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/close", {}, headers)

    # --- shipments ---
    def create_shipment(self, payload, headers):
        return self._request("POST", "/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def confirm_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/confirm", {}, headers)

    def cancel_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/cancel", {}, headers)

    # --- settlements ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def approve_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/approve", {}, headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/void", {}, headers)

    def pay_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/pay", {}, headers)

    def cancel_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/cancel", {}, headers)

    # --- byproduct sales ---
    def create_byproduct_sale(self, payload, headers):
        return self._request("POST", "/byproduct-sales", payload, headers)

    def list_byproduct_sales(self, headers, params=None):
        return self._request("GET", "/byproduct-sales", headers=headers, params=params)

    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
