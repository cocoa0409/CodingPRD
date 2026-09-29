"""
One method per endpoint in the PRD endpoint table.

Methods return the raw requests.Response so tests can assert on HTTP status as
well as body. No method interprets a response; that is the validators' job.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HTTP surface of the brick and masonry unit manufacturing API."""

    # ---- Logical clock -------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Plant ---------------------------------------------------------
    def create_plant(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/plants", payload, headers)

    def get_plant(self, plant_id: str, headers) -> requests.Response:
        return self._request("GET", f"/plants/{plant_id}", None, headers)

    def list_plants(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/plants", None, headers, params=params)

    def idle_plant(self, plant_id: str, headers) -> requests.Response:
        return self._request("POST", f"/plants/{plant_id}/idle", {}, headers)

    # ---- ClayPit -------------------------------------------------------
    def create_clay_pit(self, plant_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/plants/{plant_id}/clay-pits", payload, headers)

    def list_clay_pits(self, plant_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/plants/{plant_id}/clay-pits", None, headers, params=params
        )

    # ---- Kiln ----------------------------------------------------------
    def create_kiln(self, plant_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/plants/{plant_id}/kilns", payload, headers)

    def list_kilns(self, plant_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/plants/{plant_id}/kilns", None, headers, params=params
        )

    # ---- KilnCar -------------------------------------------------------
    def create_kiln_car(self, plant_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/plants/{plant_id}/kiln-cars", payload, headers)

    def list_kiln_cars(self, plant_id: str, headers, params=None) -> requests.Response:
        return self._request(
            "GET", f"/plants/{plant_id}/kiln-cars", None, headers, params=params
        )

    # ---- BodyFormulation ----------------------------------------------
    def create_formulation(self, payload, headers) -> requests.Response:
        return self._request("POST", "/formulations", payload, headers)

    def get_formulation(self, formulation_id: str, headers) -> requests.Response:
        return self._request("GET", f"/formulations/{formulation_id}", None, headers)

    def list_formulations(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/formulations", None, headers, params=params)

    def add_formulation_component(
        self, formulation_id: str, payload, headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/formulations/{formulation_id}/components", payload, headers
        )

    def qualify_formulation(self, formulation_id: str, headers) -> requests.Response:
        return self._request(
            "POST", f"/formulations/{formulation_id}/qualify", {}, headers
        )

    # ---- ProductionRun -------------------------------------------------
    def create_production_run(self, payload, headers) -> requests.Response:
        return self._request("POST", "/production-runs", payload, headers)

    def get_production_run(self, run_id: str, headers) -> requests.Response:
        return self._request("GET", f"/production-runs/{run_id}", None, headers)

    def list_production_runs(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/production-runs", None, headers, params=params)

    def close_green(self, run_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/production-runs/{run_id}/close-green", payload, headers
        )

    # ---- KilnRun -------------------------------------------------------
    def create_kiln_run(self, payload, headers) -> requests.Response:
        return self._request("POST", "/kiln-runs", payload, headers)

    def get_kiln_run(self, kiln_run_id: str, headers) -> requests.Response:
        return self._request("GET", f"/kiln-runs/{kiln_run_id}", None, headers)

    def list_kiln_runs(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/kiln-runs", None, headers, params=params)

    def load_kiln_run(self, kiln_run_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/kiln-runs/{kiln_run_id}/load", payload, headers)

    def start_kiln_run(self, kiln_run_id: str, headers) -> requests.Response:
        return self._request("POST", f"/kiln-runs/{kiln_run_id}/start", {}, headers)

    def grade_kiln_run(self, kiln_run_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/kiln-runs/{kiln_run_id}/grade", payload, headers)

    # ---- FiredLot ------------------------------------------------------
    def get_fired_lot(self, lot_id: str, headers) -> requests.Response:
        return self._request("GET", f"/fired-lots/{lot_id}", None, headers)

    def list_fired_lots(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/fired-lots", None, headers, params=params)

    def list_fired_lot_blend_components(
        self, lot_id: str, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"/fired-lots/{lot_id}/blend-components", None, headers, params=params
        )

    def quarantine_fired_lot(self, lot_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/fired-lots/{lot_id}/quarantine", payload, headers
        )

    # ---- Order ---------------------------------------------------------
    def create_order(self, payload, headers) -> requests.Response:
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id: str, headers) -> requests.Response:
        return self._request("GET", f"/orders/{order_id}", None, headers)

    def list_orders(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/orders", None, headers, params=params)

    def assign_plant(self, order_id: str, headers) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/assign-plant", {}, headers)

    def package_order(self, order_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/package", payload, headers)

    def deliver_order(self, order_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/deliver", payload, headers)

    def cancel_order(self, order_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    # ---- ShippedBlend --------------------------------------------------
    def create_blend(self, order_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/orders/{order_id}/blends", payload, headers)

    def get_blend(self, blend_id: str, headers) -> requests.Response:
        return self._request("GET", f"/blends/{blend_id}", None, headers)

    def list_blends(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/blends", None, headers, params=params)

    def add_blend_component(self, blend_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/blends/{blend_id}/components", payload, headers)

    def list_blend_components(
        self, blend_id: str, headers, params=None
    ) -> requests.Response:
        return self._request(
            "GET", f"/blends/{blend_id}/components", None, headers, params=params
        )

    def compose_blend(self, blend_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/blends/{blend_id}/compose", payload, headers)

    def certify_blend(self, blend_id: str, headers) -> requests.Response:
        return self._request("POST", f"/blends/{blend_id}/certify", {}, headers)

    def reject_blend(self, blend_id: str, payload, headers) -> requests.Response:
        return self._request("POST", f"/blends/{blend_id}/reject", payload, headers)

    # ---- SamplePanel ---------------------------------------------------
    def create_sample_panel(self, order_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/orders/{order_id}/sample-panels", payload, headers
        )

    def get_sample_panel(self, panel_id: str, headers) -> requests.Response:
        return self._request("GET", f"/sample-panels/{panel_id}", None, headers)

    def list_sample_panels(self, headers, params=None) -> requests.Response:
        return self._request("GET", "/sample-panels", None, headers, params=params)

    def submit_panel(self, panel_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sample-panels/{panel_id}/submit", {}, headers)

    def request_panel_revision(self, panel_id: str, payload, headers) -> requests.Response:
        return self._request(
            "POST", f"/sample-panels/{panel_id}/request-revision", payload, headers
        )

    def approve_panel(self, panel_id: str, headers) -> requests.Response:
        return self._request("POST", f"/sample-panels/{panel_id}/approve", {}, headers)
