"""One method per endpoint of the pump manufacturing and hydraulic testing API.

Every method returns the raw `requests.Response` so tests can assert on status
codes as well as bodies.  List methods take arbitrary keyword arguments and
forward them as query parameters, so `limit` and `offset` (PRD 2.3) work
alongside the declared filters.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


def _params(kwargs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    cleaned = {k: v for k, v in kwargs.items() if v is not None}
    return cleaned or None


class ApiClient(GenericApiClient):
    """Endpoint surface of the contract under test."""

    # ── Logical clock ────────────────────────────────────────────────────────
    def set_clock(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers: dict) -> requests.Response:
        return self._request("GET", "/_clock", headers=headers)

    # ── Foundries ────────────────────────────────────────────────────────────
    def create_foundry(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/foundries", payload, headers)

    def list_foundries(self, headers: dict, **params) -> requests.Response:
        return self._request("GET", "/foundries", headers=headers, params=_params(params))

    def get_foundry(self, foundry_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/foundries/{foundry_id}", headers=headers)

    def suspend_foundry(
        self, foundry_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/foundries/{foundry_id}/suspend", payload, headers
        )

    # ── Pump models ──────────────────────────────────────────────────────────
    def create_pump_model(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/pump-models", payload, headers)

    def list_pump_models(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/pump-models", headers=headers, params=_params(params)
        )

    def get_pump_model(self, model_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/pump-models/{model_id}", headers=headers)

    def supersede_pump_model(
        self, model_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/pump-models/{model_id}/supersede", payload, headers
        )

    # ── Pattern assets ───────────────────────────────────────────────────────
    def create_pattern_asset(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/pattern-assets", payload, headers)

    def list_pattern_assets(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/pattern-assets", headers=headers, params=_params(params)
        )

    def get_pattern_asset(self, pattern_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/pattern-assets/{pattern_id}", headers=headers)

    def start_pattern_refurbishment(
        self, pattern_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/pattern-assets/{pattern_id}/refurbishment-start",
            payload or {},
            headers,
        )

    def complete_pattern_refurbishment(
        self, pattern_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/pattern-assets/{pattern_id}/refurbishment-complete",
            payload or {},
            headers,
        )

    def retire_pattern_asset(
        self, pattern_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pattern-assets/{pattern_id}/retire", payload or {}, headers
        )

    # ── Material and seal configurations ─────────────────────────────────────
    def create_material_seal_config(
        self, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request("POST", "/material-seal-configs", payload, headers)

    def list_material_seal_configs(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/material-seal-configs", headers=headers, params=_params(params)
        )

    def get_material_seal_config(
        self, config_id: str, headers: dict
    ) -> requests.Response:
        return self._request(
            "GET", f"/material-seal-configs/{config_id}", headers=headers
        )

    # ── Duty applications ────────────────────────────────────────────────────
    def create_duty_application(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/duty-applications", payload, headers)

    def list_duty_applications(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/duty-applications", headers=headers, params=_params(params)
        )

    def get_duty_application(self, duty_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/duty-applications/{duty_id}", headers=headers)

    # ── Selections ───────────────────────────────────────────────────────────
    def create_selection(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/selections", payload, headers)

    def list_selections(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/selections", headers=headers, params=_params(params)
        )

    def get_selection(self, selection_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/selections/{selection_id}", headers=headers)

    def propose_selection(
        self, selection_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/selections/{selection_id}/propose", payload or {}, headers
        )

    def revise_selection(
        self, selection_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/selections/{selection_id}/revise", payload or {}, headers
        )

    def approve_selection(
        self, selection_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/selections/{selection_id}/approve", payload or {}, headers
        )

    def supersede_selection(
        self, selection_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/selections/{selection_id}/supersede", payload or {}, headers
        )

    # ── Casting lots ─────────────────────────────────────────────────────────
    def create_casting_lot(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/casting-lots", payload, headers)

    def list_casting_lots(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/casting-lots", headers=headers, params=_params(params)
        )

    def get_casting_lot(self, lot_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/casting-lots/{lot_id}", headers=headers)

    def inspect_casting_lot(
        self, lot_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/casting-lots/{lot_id}/inspect", payload or {}, headers
        )

    def accept_casting_lot(
        self, lot_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/casting-lots/{lot_id}/accept", payload or {}, headers
        )

    def start_casting_lot_rework(
        self, lot_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/casting-lots/{lot_id}/rework-start", payload or {}, headers
        )

    def scrap_casting_lot(
        self, lot_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/casting-lots/{lot_id}/scrap-lot", payload or {}, headers
        )

    def report_casting_defect(
        self, lot_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/casting-lots/{lot_id}/defects", payload, headers
        )

    # ── Casting defects ──────────────────────────────────────────────────────
    def list_casting_defects(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/casting-defects", headers=headers, params=_params(params)
        )

    def get_casting_defect(self, defect_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/casting-defects/{defect_id}", headers=headers)

    def disposition_casting_defect(
        self, defect_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/casting-defects/{defect_id}/disposition", payload, headers
        )

    def revise_casting_defect_disposition(
        self, defect_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/casting-defects/{defect_id}/revise-disposition", payload, headers
        )

    def verify_casting_defect_repair(
        self, defect_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/casting-defects/{defect_id}/repair-verified",
            payload or {},
            headers,
        )

    # ── Build orders ─────────────────────────────────────────────────────────
    def create_build_order(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/build-orders", payload, headers)

    def list_build_orders(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/build-orders", headers=headers, params=_params(params)
        )

    def get_build_order(self, build_order_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/build-orders/{build_order_id}", headers=headers)

    def record_assembly(
        self, build_order_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/build-orders/{build_order_id}/assembly", payload, headers
        )

    def complete_build_order_rework(
        self, build_order_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/build-orders/{build_order_id}/rework-complete",
            payload or {},
            headers,
        )

    def reassign_build_order_lot(
        self, build_order_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/build-orders/{build_order_id}/reassign-lot", payload, headers
        )

    def auto_allocate_kit(
        self, build_order_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/build-orders/{build_order_id}/kit-allocations/auto",
            payload,
            headers,
        )

    # ── Test runs and points ─────────────────────────────────────────────────
    def create_test_run(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/test-runs", payload, headers)

    def list_test_runs(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/test-runs", headers=headers, params=_params(params)
        )

    def get_test_run(self, test_run_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/test-runs/{test_run_id}", headers=headers)

    def add_test_point(
        self, test_run_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/test-runs/{test_run_id}/points", payload, headers
        )

    def list_test_points(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/test-points", headers=headers, params=_params(params)
        )

    def get_test_point(self, test_point_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/test-points/{test_point_id}", headers=headers)

    def lock_test_run(
        self, test_run_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/test-runs/{test_run_id}/lock", payload or {}, headers
        )

    def evaluate_test_run(
        self, test_run_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/test-runs/{test_run_id}/evaluate", payload or {}, headers
        )

    def certify_test_run(
        self, test_run_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/test-runs/{test_run_id}/certify", payload or {}, headers
        )

    def reopen_test_run(
        self, test_run_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/test-runs/{test_run_id}/reopen", payload or {}, headers
        )

    # ── Pump packages ────────────────────────────────────────────────────────
    def create_pump_package(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/pump-packages", payload, headers)

    def list_pump_packages(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/pump-packages", headers=headers, params=_params(params)
        )

    def get_pump_package(self, package_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/pump-packages/{package_id}", headers=headers)

    def release_pump_package(
        self, package_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pump-packages/{package_id}/release", payload or {}, headers
        )

    def ship_pump_package(
        self, package_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/pump-packages/{package_id}/ship", payload, headers
        )

    def release_pump_package_hold(
        self, package_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/pump-packages/{package_id}/release-hold", payload or {}, headers
        )

    # ── Repair kits ──────────────────────────────────────────────────────────
    def create_repair_kit(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/repair-kits", payload, headers)

    def list_repair_kits(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/repair-kits", headers=headers, params=_params(params)
        )

    def get_repair_kit(self, kit_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/repair-kits/{kit_id}", headers=headers)

    def receive_repair_kit_stock(
        self, kit_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request("POST", f"/repair-kits/{kit_id}/receipts", payload, headers)

    def discontinue_repair_kit(
        self, kit_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/repair-kits/{kit_id}/discontinue", payload or {}, headers
        )

    # ── Kit allocations ──────────────────────────────────────────────────────
    def create_kit_allocation(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/kit-allocations", payload, headers)

    def list_kit_allocations(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/kit-allocations", headers=headers, params=_params(params)
        )

    def get_kit_allocation(self, allocation_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/kit-allocations/{allocation_id}", headers=headers)

    def issue_kit_allocation(
        self, allocation_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/kit-allocations/{allocation_id}/issue", payload or {}, headers
        )

    def consume_kit_allocation(
        self, allocation_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/kit-allocations/{allocation_id}/consume", payload or {}, headers
        )

    def release_kit_allocation(
        self, allocation_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/kit-allocations/{allocation_id}/release", payload or {}, headers
        )

    # ── Warranty claims ──────────────────────────────────────────────────────
    def create_warranty_claim(self, payload: dict, headers: dict) -> requests.Response:
        return self._request("POST", "/warranty-claims", payload, headers)

    def list_warranty_claims(self, headers: dict, **params) -> requests.Response:
        return self._request(
            "GET", "/warranty-claims", headers=headers, params=_params(params)
        )

    def get_warranty_claim(self, claim_id: str, headers: dict) -> requests.Response:
        return self._request("GET", f"/warranty-claims/{claim_id}", headers=headers)

    def begin_claim_adjudication(
        self, claim_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/warranty-claims/{claim_id}/begin-adjudication",
            payload or {},
            headers,
        )

    def request_claim_info(
        self, claim_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/request-info", payload, headers
        )

    def resume_claim_adjudication(
        self, claim_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/warranty-claims/{claim_id}/resume-adjudication",
            payload or {},
            headers,
        )

    def adjudicate_claim(
        self, claim_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/adjudicate", payload or {}, headers
        )

    def settle_claim(
        self, claim_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/warranty-claims/{claim_id}/settle", payload or {}, headers
        )


# Shared client instance; the base URL comes from API_BASE_URL.
api_client = ApiClient()
