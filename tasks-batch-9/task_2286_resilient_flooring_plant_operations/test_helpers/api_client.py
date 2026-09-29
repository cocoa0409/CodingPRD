"""Typed HTTP client with one method per endpoint in PRD section 4.

Every method returns the raw `requests.Response`; tests pass that response to
`validate_success`, `validate_error` or `validate_paginated`. All paths are
mounted at the root, as PRD section 4 states: "All paths are mounted at the
root. There is no version prefix and no other namespace segment."
"""

from typing import Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint-per-method wrapper around the generic PRD-bench client."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/_clock/set_current_utc", json=payload, headers=headers)

    # --------------------------------------------------------- distributors
    def create_distributor(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/distributors", json=payload, headers=headers)

    def list_distributors(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/distributors", headers=headers, params=params)

    def get_distributor(self, distributor_id: str, headers: dict) -> requests.Response:
        return self.get(f"/distributors/{distributor_id}", headers=headers)

    # -------------------------------------------------------- raw materials
    def create_raw_material(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/raw-materials", json=payload, headers=headers)

    def list_raw_materials(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/raw-materials", headers=headers, params=params)

    def get_raw_material(self, material_id: str, headers: dict) -> requests.Response:
        return self.get(f"/raw-materials/{material_id}", headers=headers)

    def list_raw_material_formulation_components(
        self, material_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get(
            f"/raw-materials/{material_id}/formulation-components",
            headers=headers,
            params=params,
        )

    def set_raw_material_status(
        self, material_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/raw-materials/{material_id}/status", json=payload, headers=headers
        )

    def set_raw_material_cost(
        self, material_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/raw-materials/{material_id}/cost", json=payload, headers=headers
        )

    # --------------------------------------------------------- formulations
    def create_formulation(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/formulations", json=payload, headers=headers)

    def list_formulations(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/formulations", headers=headers, params=params)

    def get_formulation(self, formulation_id: str, headers: dict) -> requests.Response:
        return self.get(f"/formulations/{formulation_id}", headers=headers)

    def list_formulation_components(
        self, formulation_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get(
            f"/formulations/{formulation_id}/components", headers=headers, params=params
        )

    def add_formulation_component(
        self, formulation_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/formulations/{formulation_id}/components", json=payload, headers=headers
        )

    def delete_formulation_component(
        self, formulation_id: str, component_id: str, headers: dict
    ) -> requests.Response:
        return self.delete(
            f"/formulations/{formulation_id}/components/{component_id}", headers=headers
        )

    def submit_formulation(
        self, formulation_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/formulations/{formulation_id}/submit",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def review_formulation(
        self, formulation_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/formulations/{formulation_id}/review-decision",
            json=payload,
            headers=headers,
        )

    def create_formulation_revision(
        self, formulation_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/formulations/{formulation_id}/revisions", json=payload, headers=headers
        )

    # ------------------------------------------------------ design licenses
    def create_design_license(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/design-licenses", json=payload, headers=headers)

    def list_design_licenses(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/design-licenses", headers=headers, params=params)

    def get_design_license(self, license_id: str, headers: dict) -> requests.Response:
        return self.get(f"/design-licenses/{license_id}", headers=headers)

    def get_license_utilization(
        self, license_id: str, headers: dict
    ) -> requests.Response:
        return self.get(f"/design-licenses/{license_id}/utilization", headers=headers)

    def create_license_amendment(
        self, license_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/design-licenses/{license_id}/amendments", json=payload, headers=headers
        )

    def set_license_status(
        self, license_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/design-licenses/{license_id}/status", json=payload, headers=headers
        )

    # ----------------------------------------------------------- print films
    def create_print_film(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/print-films", json=payload, headers=headers)

    def list_print_films(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/print-films", headers=headers, params=params)

    def get_print_film(self, film_id: str, headers: dict) -> requests.Response:
        return self.get(f"/print-films/{film_id}", headers=headers)

    def set_print_film_status(
        self, film_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/print-films/{film_id}/status", json=payload, headers=headers
        )

    # ---------------------------------------------------------- product SKUs
    def create_product_sku(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/product-skus", json=payload, headers=headers)

    def list_product_skus(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/product-skus", headers=headers, params=params)

    def get_product_sku(self, sku_id: str, headers: dict) -> requests.Response:
        return self.get(f"/product-skus/{sku_id}", headers=headers)

    def get_sku_cost_summary(self, sku_id: str, headers: dict) -> requests.Response:
        return self.get(f"/product-skus/{sku_id}/cost-summary", headers=headers)

    def begin_sku_testing(
        self, sku_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/product-skus/{sku_id}/begin-testing",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def certify_sku(
        self, sku_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/product-skus/{sku_id}/certify",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def set_sku_commercial_status(
        self, sku_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/product-skus/{sku_id}/commercial-status", json=payload, headers=headers
        )

    # ----------------------------------------------------------- press lines
    def create_press_line(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/press-lines", json=payload, headers=headers)

    def list_press_lines(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/press-lines", headers=headers, params=params)

    def get_press_line(self, line_id: str, headers: dict) -> requests.Response:
        return self.get(f"/press-lines/{line_id}", headers=headers)

    def set_press_line_status(
        self, line_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/press-lines/{line_id}/status", json=payload, headers=headers
        )

    # ----------------------------------------------------------- test panels
    def create_test_panel(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/test-panels", json=payload, headers=headers)

    def list_test_panels(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/test-panels", headers=headers, params=params)

    def get_test_panel(self, panel_id: str, headers: dict) -> requests.Response:
        return self.get(f"/test-panels/{panel_id}", headers=headers)

    def list_test_results(
        self, panel_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get(
            f"/test-panels/{panel_id}/results", headers=headers, params=params
        )

    def start_test_panel(
        self, panel_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/test-panels/{panel_id}/start",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def record_test_result(
        self, panel_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/test-panels/{panel_id}/results", json=payload, headers=headers
        )

    def void_test_panel(
        self, panel_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(f"/test-panels/{panel_id}/void", json=payload, headers=headers)

    # -------------------------------------------------------- production runs
    def create_production_run(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/production-runs", json=payload, headers=headers)

    def list_production_runs(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/production-runs", headers=headers, params=params)

    def get_production_run(self, run_id: str, headers: dict) -> requests.Response:
        return self.get(f"/production-runs/{run_id}", headers=headers)

    def setup_production_run(
        self, run_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/production-runs/{run_id}/setup",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def start_production_run(
        self, run_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/production-runs/{run_id}/start",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def complete_production_run(
        self, run_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/production-runs/{run_id}/complete", json=payload, headers=headers
        )

    def abort_production_run(
        self, run_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/production-runs/{run_id}/abort", json=payload, headers=headers
        )

    def set_run_qc_disposition(
        self, run_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/production-runs/{run_id}/qc-disposition", json=payload, headers=headers
        )

    # ---------------------------------------------------------------- batches
    def list_batches(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/batches", headers=headers, params=params)

    def get_batch(self, batch_id: str, headers: dict) -> requests.Response:
        return self.get(f"/batches/{batch_id}", headers=headers)

    def list_batch_allocation_lines(
        self, batch_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get(
            f"/batches/{batch_id}/allocation-lines", headers=headers, params=params
        )

    def set_batch_hold_status(
        self, batch_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/batches/{batch_id}/hold-status", json=payload, headers=headers
        )

    # ------------------------------------------------------------ allocations
    def create_allocation(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/allocations", json=payload, headers=headers)

    def list_allocations(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/allocations", headers=headers, params=params)

    def get_allocation(self, allocation_id: str, headers: dict) -> requests.Response:
        return self.get(f"/allocations/{allocation_id}", headers=headers)

    def list_allocation_lines(
        self, allocation_id: str, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get(
            f"/allocations/{allocation_id}/lines", headers=headers, params=params
        )

    def fill_allocation(
        self, allocation_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/allocations/{allocation_id}/fill", json=payload, headers=headers
        )

    def release_allocation(
        self, allocation_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/allocations/{allocation_id}/release",
            json=payload if payload is not None else {},
            headers=headers,
        )

    # -------------------------------------------------------- warranty claims
    def create_warranty_claim(self, payload: dict, headers: dict) -> requests.Response:
        return self.post("/warranty-claims", json=payload, headers=headers)

    def list_warranty_claims(
        self, headers: dict, params: Optional[dict] = None
    ) -> requests.Response:
        return self.get("/warranty-claims", headers=headers, params=params)

    def get_warranty_claim(self, claim_id: str, headers: dict) -> requests.Response:
        return self.get(f"/warranty-claims/{claim_id}", headers=headers)

    def triage_warranty_claim(
        self, claim_id: str, headers: dict, payload: Optional[dict] = None
    ) -> requests.Response:
        return self.post(
            f"/warranty-claims/{claim_id}/triage",
            json=payload if payload is not None else {},
            headers=headers,
        )

    def record_claim_review(
        self, claim_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/warranty-claims/{claim_id}/reviews", json=payload, headers=headers
        )

    def adjudicate_warranty_claim(
        self, claim_id: str, payload: dict, headers: dict
    ) -> requests.Response:
        return self.post(
            f"/warranty-claims/{claim_id}/adjudicate", json=payload, headers=headers
        )


# Module-level singleton reused by every test through the `api` fixture.
api_client = ApiClient()
