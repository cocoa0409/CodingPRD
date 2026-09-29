"""Domain API client: one method per endpoint in PRD 4.

Every path is served at the API root with no version or service prefix
(PRD 4), and every foreign key travels in a request body or a query string
rather than in a URL segment.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import GenericApiClient


class InsulationApiClient(GenericApiClient):
    """Thin transport wrapper - no assertions, no business logic."""

    # ------------------------------------------------------------------
    # Clock and health
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers=headers,
        )

    def health(self, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", "/_health", headers=headers)

    # ------------------------------------------------------------------
    # Certification programs
    # ------------------------------------------------------------------

    def create_certification_program(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/certification-programs", payload, headers=headers)

    def get_certification_program(self, program_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/certification-programs/{program_id}", headers=headers
        )

    def list_certification_programs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/certification-programs", params or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Plants
    # ------------------------------------------------------------------

    def create_plant(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/plants", payload, headers=headers)

    def get_plant(self, plant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/plants/{plant_id}", headers=headers)

    def list_plants(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/plants", params or {}, headers=headers)

    def file_emissions_report(
        self, plant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/plants/{plant_id}/emissions-report", payload, headers=headers
        )

    def posture_review(
        self, plant_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/plants/{plant_id}/posture-review", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Binder formulations
    # ------------------------------------------------------------------

    def create_binder_formulation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", "/binder-formulations", payload, headers=headers)

    def get_binder_formulation(self, binder_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/binder-formulations/{binder_id}", headers=headers
        )

    def list_binder_formulations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request(
            "GET", "/binder-formulations", params or {}, headers=headers
        )

    def submit_binder(self, binder_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/binder-formulations/{binder_id}/submit", {}, headers=headers
        )

    def record_binder_emissions_test(
        self, binder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/binder-formulations/{binder_id}/emissions-test",
            payload,
            headers=headers,
        )

    def binder_certification_decision(
        self, binder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/binder-formulations/{binder_id}/certification-decision",
            payload,
            headers=headers,
        )

    def revise_binder(
        self, binder_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/binder-formulations/{binder_id}/revise", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Product lines
    # ------------------------------------------------------------------

    def create_product_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/product-lines", payload, headers=headers)

    def get_product_line(self, product_line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/product-lines/{product_line_id}", headers=headers)

    def list_product_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/product-lines", params or {}, headers=headers)

    def patch_packaging(
        self, product_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "PATCH",
            f"/product-lines/{product_line_id}/packaging",
            payload,
            headers=headers,
        )

    def submit_sku_certification(self, product_line_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/product-lines/{product_line_id}/submit-certification",
            {},
            headers=headers,
        )

    def sku_certification_decision(
        self, product_line_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/product-lines/{product_line_id}/certification-decision",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Production runs
    # ------------------------------------------------------------------

    def create_production_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/production-runs", payload, headers=headers)

    def get_production_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/production-runs/{run_id}", headers=headers)

    def list_production_runs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/production-runs", params or {}, headers=headers)

    def start_melt(
        self, run_id: str, cullet_batch_ids: List[str], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/production-runs/{run_id}/start-melt",
            {"cullet_batch_ids": cullet_batch_ids},
            headers=headers,
        )

    def start_cure(
        self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/production-runs/{run_id}/start-cure", payload, headers=headers
        )

    def package_run(self, run_id: str, bags_produced: int, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/production-runs/{run_id}/package",
            {"bags_produced": bags_produced},
            headers=headers,
        )

    def close_run(self, run_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/production-runs/{run_id}/close", {}, headers=headers
        )

    def abort_run(self, run_id: str, abort_reason: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/production-runs/{run_id}/abort",
            {"abort_reason": abort_reason},
            headers=headers,
        )

    def release_hold(self, run_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/production-runs/{run_id}/release-hold", {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Changeover events
    # ------------------------------------------------------------------

    def create_changeover(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/changeover-events", payload, headers=headers)

    def get_changeover(self, changeover_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/changeover-events/{changeover_id}", headers=headers
        )

    def list_changeovers(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/changeover-events", params or {}, headers=headers)

    def close_changeover(
        self, changeover_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/changeover-events/{changeover_id}/close",
            payload,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Thermal tests
    # ------------------------------------------------------------------

    def create_thermal_test(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/thermal-tests", payload, headers=headers)

    def get_thermal_test(self, test_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/thermal-tests/{test_id}", headers=headers)

    def list_thermal_tests(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/thermal-tests", params or {}, headers=headers)

    def start_lab(self, test_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/thermal-tests/{test_id}/start-lab", {}, headers=headers
        )

    def record_result(
        self, test_id: str, specimen_r_values: List[float], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/thermal-tests/{test_id}/record-result",
            {"specimen_r_values": specimen_r_values},
            headers=headers,
        )

    def request_retest(
        self, test_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/thermal-tests/{test_id}/request-retest", payload, headers=headers
        )

    # ------------------------------------------------------------------
    # Inventory lots
    # ------------------------------------------------------------------

    def get_inventory_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/inventory-lots", params or {}, headers=headers)

    def repack_lot(
        self, lot_id: str, child_bags: List[int], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/inventory-lots/{lot_id}/repack",
            {"child_bags": child_bags},
            headers=headers,
        )

    def quarantine_lot(
        self, lot_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/inventory-lots/{lot_id}/quarantine", payload, headers=headers
        )

    def release_lot(self, lot_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/inventory-lots/{lot_id}/release", {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Cullet batches
    # ------------------------------------------------------------------

    def create_cullet_batch(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cullet-batches", payload, headers=headers)

    def get_cullet_batch(self, batch_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cullet-batches/{batch_id}", headers=headers)

    def list_cullet_batches(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/cullet-batches", params or {}, headers=headers)

    def reverse_cullet_batch(
        self,
        batch_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/cullet-batches/{batch_id}/reverse", payload or {}, headers=headers
        )

    def reject_cullet_batch(
        self, batch_id: str, reject_reason: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/cullet-batches/{batch_id}/reject",
            {"reject_reason": reject_reason},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Allocation cycles
    # ------------------------------------------------------------------

    def create_allocation_cycle(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/allocation-cycles", payload, headers=headers)

    def get_allocation_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/allocation-cycles/{cycle_id}", headers=headers)

    def list_allocation_cycles(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/allocation-cycles", params or {}, headers=headers)

    def propose_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/allocation-cycles/{cycle_id}/propose", {}, headers=headers
        )

    def commit_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/allocation-cycles/{cycle_id}/commit", {}, headers=headers
        )

    def cancel_cycle(
        self,
        cycle_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST",
            f"/allocation-cycles/{cycle_id}/cancel",
            payload or {},
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Channel orders
    # ------------------------------------------------------------------

    def create_channel_order(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/channel-orders", payload, headers=headers)

    def get_channel_order(self, order_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/channel-orders/{order_id}", headers=headers)

    def list_channel_orders(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/channel-orders", params or {}, headers=headers)

    def cancel_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/channel-orders/{order_id}/cancel", payload or {}, headers=headers
        )

    def ship_order(
        self,
        order_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/channel-orders/{order_id}/ship", payload or {}, headers=headers
        )

    # ------------------------------------------------------------------
    # Allocation lines
    # ------------------------------------------------------------------

    def create_allocation_line(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/allocation-lines", payload, headers=headers)

    def get_allocation_line(self, line_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/allocation-lines/{line_id}", headers=headers)

    def list_allocation_lines(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ):
        return self._request("GET", "/allocation-lines", params or {}, headers=headers)

    def revoke_allocation_line(
        self,
        line_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ):
        return self._request(
            "POST", f"/allocation-lines/{line_id}/revoke", payload or {}, headers=headers
        )
