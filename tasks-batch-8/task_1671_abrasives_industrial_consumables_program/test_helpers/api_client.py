"""API client: one method per endpoint defined in the PRD (§4)."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Catalog ---
    def create_product(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/products", payload, headers)

    def list_products(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/products", headers=headers, params=params)

    def get_product(self, product_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    def discontinue_product(self, product_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/api/products/{product_id}/discontinue", payload, headers)

    # --- Machines ---
    def create_machine(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/machines", payload, headers)

    def get_machine(self, machine_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/machines/{machine_id}", headers=headers)

    def quarantine_machine(self, machine_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/machines/{machine_id}/quarantine", headers=headers)

    def reinstate_machine(self, machine_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/machines/{machine_id}/reinstate", headers=headers)

    # --- Inventory lots ---
    def create_lot(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/lots", payload, headers)

    def get_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/lots/{lot_id}", headers=headers)

    def list_lots(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/lots", headers=headers, params=params)

    # --- Usage standards ---
    def create_standard(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/standards", payload, headers)

    def get_standard(self, standard_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/standards/{standard_id}", headers=headers)

    def list_standards(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/standards", headers=headers, params=params)

    def retire_standard(self, standard_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/standards/{standard_id}/retire", headers=headers)

    # --- Usage records ---
    def create_usage_record(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/usage-records", payload, headers)

    def get_usage_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/usage-records/{record_id}", headers=headers)

    def list_usage_records(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/usage-records", headers=headers, params=params)

    # --- Contracts ---
    def create_contract(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/contracts", payload, headers)

    def get_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/contracts/{contract_id}/activate", headers=headers)

    def amend_contract(self, contract_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("PATCH", f"/api/contracts/{contract_id}", payload, headers)

    def terminate_contract(self, contract_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/contracts/{contract_id}/terminate", headers=headers)

    # --- Contract lines ---
    def get_contract_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/contract-lines/{line_id}", headers=headers)

    def list_contract_lines(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/contract-lines", headers=headers, params=params)

    # --- Blanket orders ---
    def create_blanket_order(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/blanket-orders", payload, headers)

    def get_blanket_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/blanket-orders/{order_id}", headers=headers)

    def list_blanket_orders(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/blanket-orders", headers=headers, params=params)

    def confirm_blanket_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/blanket-orders/{order_id}/confirm", headers=headers)

    def cancel_blanket_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/blanket-orders/{order_id}/cancel", headers=headers)

    def accept_substitution(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/blanket-orders/{order_id}/accept-substitution", headers=headers
        )

    # --- Releases ---
    def create_release(self, order_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/blanket-orders/{order_id}/releases", payload, headers
        )

    def get_release(self, release_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/releases/{release_id}", headers=headers)

    def list_releases(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/releases", headers=headers, params=params)

    def pick_release(self, release_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/releases/{release_id}/pick", headers=headers)

    def ship_release(self, release_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/releases/{release_id}/ship", headers=headers)

    def cancel_release(self, release_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/releases/{release_id}/cancel", headers=headers)

    # --- Trials ---
    def create_trial(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/trials", payload, headers)

    def get_trial(self, trial_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/trials/{trial_id}", headers=headers)

    def list_trials(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/trials", headers=headers, params=params)

    def submit_trial_results(self, trial_id: str, payload: dict, headers: Dict[str, str]):
        return self._request(
            "POST", f"/api/trials/{trial_id}/submit-results", payload, headers
        )

    def convert_trial(self, trial_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/api/trials/{trial_id}/convert", headers=headers)

    def reject_trial(self, trial_id: str, payload: dict, headers: Dict[str, str]):
        return self._request("POST", f"/api/trials/{trial_id}/reject", payload, headers)

    # --- Disposal records ---
    def create_disposal_record(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/disposal-records", payload, headers)

    def get_disposal_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/api/disposal-records/{record_id}", headers=headers)

    def list_disposal_records(self, headers: Dict[str, str], params: Optional[dict] = None):
        return self._request("GET", "/api/disposal-records", headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, payload: dict, headers: Dict[str, str]):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
