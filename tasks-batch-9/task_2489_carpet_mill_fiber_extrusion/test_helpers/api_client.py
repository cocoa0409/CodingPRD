"""API client: one method per endpoint defined in the PRD.

All paths are rooted at the /mill prefix the PRD assigns to this service.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/mill"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    def create_account(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/accounts", payload, headers)

    def update_account(self, account_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"{BASE}/accounts/{account_id}", payload, headers)

    def get_account(self, account_id: str, headers: dict):
        return self._request("GET", f"{BASE}/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/accounts", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Polymer lots
    # ------------------------------------------------------------------
    def create_polymer_lot(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/polymer-lots", payload, headers)

    def get_polymer_lot(self, polymer_lot_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/polymer-lots/{polymer_lot_id}", headers=headers
        )

    def list_polymer_lots(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/polymer-lots", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Reclamation batches
    # ------------------------------------------------------------------
    def create_reclamation_batch(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/reclamation-batches", payload, headers)

    def depolymerize_reclamation_batch(
        self, reclamation_batch_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/reclamation-batches/{reclamation_batch_id}/depolymerize",
            payload if payload is not None else {},
            headers,
        )

    def get_reclamation_batch(self, reclamation_batch_id: str, headers: dict):
        return self._request(
            "GET",
            f"{BASE}/reclamation-batches/{reclamation_batch_id}",
            headers=headers,
        )

    def list_reclamation_batches(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/reclamation-batches", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Fiber batches
    # ------------------------------------------------------------------
    def create_fiber_batch(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/fiber-batches", payload, headers)

    def extrude_fiber_batch(self, fiber_batch_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/fiber-batches/{fiber_batch_id}/extrude", payload, headers
        )

    def disposition_fiber_batch(
        self, fiber_batch_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/fiber-batches/{fiber_batch_id}/disposition",
            payload,
            headers,
        )

    def get_fiber_batch(self, fiber_batch_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/fiber-batches/{fiber_batch_id}", headers=headers
        )

    def list_fiber_batches(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/fiber-batches", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Carpet styles
    # ------------------------------------------------------------------
    def create_style(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/styles", payload, headers)

    def activate_style(self, style_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{BASE}/styles/{style_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def discontinue_style(self, style_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/styles/{style_id}/discontinue", payload, headers
        )

    def get_style(self, style_id: str, headers: dict):
        return self._request("GET", f"{BASE}/styles/{style_id}", headers=headers)

    def list_styles(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/styles", headers=headers, params=params)

    def get_style_recycled_content(
        self, style_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"{BASE}/styles/{style_id}/recycled-content",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------------
    # Tufting machines
    # ------------------------------------------------------------------
    def create_tufting_machine(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/tufting-machines", payload, headers)

    def get_tufting_machine(self, machine_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/tufting-machines/{machine_id}", headers=headers
        )

    def list_tufting_machines(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/tufting-machines", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Dye vessels
    # ------------------------------------------------------------------
    def create_dye_vessel(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/dye-vessels", payload, headers)

    def get_dye_vessel(self, vessel_id: str, headers: dict):
        return self._request("GET", f"{BASE}/dye-vessels/{vessel_id}", headers=headers)

    def list_dye_vessels(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/dye-vessels", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Production runs
    # ------------------------------------------------------------------
    def create_production_run(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/production-runs", payload, headers)

    def load_setup_production_run(
        self, production_run_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/load-setup",
            payload,
            headers,
        )

    def complete_greige_production_run(
        self, production_run_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/complete-greige",
            payload,
            headers,
        )

    def apply_backing_production_run(
        self, production_run_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/apply-backing",
            payload,
            headers,
        )

    def recoat_production_run(
        self, production_run_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/recoat",
            payload if payload is not None else {},
            headers,
        )

    def abort_production_run(
        self, production_run_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/abort",
            payload,
            headers,
        )

    def doff_roll_good(self, production_run_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{BASE}/production-runs/{production_run_id}/roll-goods",
            payload,
            headers,
        )

    def get_production_run(self, production_run_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/production-runs/{production_run_id}", headers=headers
        )

    def list_production_runs(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/production-runs", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Dye lots
    # ------------------------------------------------------------------
    def create_dye_lot(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/dye-lots", payload, headers)

    def start_dyeing(self, dye_lot_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{BASE}/dye-lots/{dye_lot_id}/start-dyeing",
            payload if payload is not None else {},
            headers,
        )

    def record_dye_lot_measurement(self, dye_lot_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/dye-lots/{dye_lot_id}/measurements", payload, headers
        )

    def disposition_dye_lot(self, dye_lot_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/dye-lots/{dye_lot_id}/disposition", payload, headers
        )

    def get_dye_lot(self, dye_lot_id: str, headers: dict):
        return self._request("GET", f"{BASE}/dye-lots/{dye_lot_id}", headers=headers)

    def list_dye_lots(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/dye-lots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Roll goods
    # ------------------------------------------------------------------
    def qa_disposition_roll_good(self, roll_good_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"{BASE}/roll-goods/{roll_good_id}/qa-disposition",
            payload,
            headers,
        )

    def get_roll_good(self, roll_good_id: str, headers: dict):
        return self._request("GET", f"{BASE}/roll-goods/{roll_good_id}", headers=headers)

    def list_roll_goods(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/roll-goods", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Product tests
    # ------------------------------------------------------------------
    def create_product_test(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/product-tests", payload, headers)

    def get_product_test(self, product_test_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/product-tests/{product_test_id}", headers=headers
        )

    def list_product_tests(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/product-tests", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Certifications
    # ------------------------------------------------------------------
    def create_certification(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/certifications", payload, headers)

    def revoke_certification(
        self, certification_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"{BASE}/certifications/{certification_id}/revoke",
            payload,
            headers,
        )

    def get_certification(self, certification_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/certifications/{certification_id}", headers=headers
        )

    def list_certifications(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/certifications", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Cut orders
    # ------------------------------------------------------------------
    def create_cut_order(self, payload: dict, headers: dict):
        return self._request("POST", f"{BASE}/cut-orders", payload, headers)

    def allocate_cut_order(
        self, cut_order_id: str, headers: dict, payload: Optional[dict] = None
    ):
        return self._request(
            "POST",
            f"{BASE}/cut-orders/{cut_order_id}/allocate",
            payload if payload is not None else {},
            headers,
        )

    def create_manual_allocation(self, cut_order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/cut-orders/{cut_order_id}/allocations", payload, headers
        )

    def cut_cut_order(self, cut_order_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{BASE}/cut-orders/{cut_order_id}/cut",
            payload if payload is not None else {},
            headers,
        )

    def ship_cut_order(self, cut_order_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"{BASE}/cut-orders/{cut_order_id}/ship",
            payload if payload is not None else {},
            headers,
        )

    def cancel_cut_order(self, cut_order_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/cut-orders/{cut_order_id}/cancel", payload, headers
        )

    def get_cut_order(self, cut_order_id: str, headers: dict):
        return self._request("GET", f"{BASE}/cut-orders/{cut_order_id}", headers=headers)

    def list_cut_orders(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", f"{BASE}/cut-orders", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Cut allocations
    # ------------------------------------------------------------------
    def get_cut_allocation(self, cut_allocation_id: str, headers: dict):
        return self._request(
            "GET", f"{BASE}/cut-allocations/{cut_allocation_id}", headers=headers
        )

    def list_cut_allocations(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", f"{BASE}/cut-allocations", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload: dict, headers: dict):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", payload, headers
        )

    # ------------------------------------------------------------------
    # Raw escape hatch for path/verb-level tests
    # ------------------------------------------------------------------
    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[dict] = None,
    ):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
