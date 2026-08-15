"""API client: one method per endpoint defined in PRD §4."""
from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- asset classes ---
    def create_asset_class(self, payload: Dict, headers: Dict):
        return self._request("POST", "/asset-classes", payload, headers)

    def get_asset_class(self, class_id: str, headers: Dict):
        return self._request("GET", f"/asset-classes/{class_id}", headers=headers)

    # --- capital projects / CIP cost lines ---
    def create_capital_project(self, payload: Dict, headers: Dict):
        return self._request("POST", "/capital-projects", payload, headers)

    def list_capital_projects(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/capital-projects", headers=headers, params=params)

    def get_capital_project(self, project_id: str, headers: Dict):
        return self._request("GET", f"/capital-projects/{project_id}", headers=headers)

    def capitalize_project(self, project_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/capital-projects/{project_id}/capitalize", payload, headers
        )

    def cancel_project(self, project_id: str, headers: Dict):
        return self._request(
            "POST", f"/capital-projects/{project_id}/cancel", {}, headers
        )

    def create_cip_cost_line(self, payload: Dict, headers: Dict):
        return self._request("POST", "/cip-cost-lines", payload, headers)

    def list_project_cost_lines(self, project_id: str, headers: Dict,
                                params: Optional[Dict] = None):
        return self._request(
            "GET", f"/capital-projects/{project_id}/cost-lines",
            headers=headers, params=params,
        )

    def reverse_cip_cost_line(self, line_id: str, headers: Dict):
        return self._request("POST", f"/cip-cost-lines/{line_id}/reverse", {}, headers)

    # --- fixed assets ---
    def create_fixed_asset(self, payload: Dict, headers: Dict):
        return self._request("POST", "/fixed-assets", payload, headers)

    def list_fixed_assets(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/fixed-assets", headers=headers, params=params)

    def get_fixed_asset(self, asset_id: str, headers: Dict):
        return self._request("GET", f"/fixed-assets/{asset_id}", headers=headers)

    def patch_fixed_asset(self, asset_id: str, payload: Dict, headers: Dict):
        return self._request("PATCH", f"/fixed-assets/{asset_id}", payload, headers)

    def place_in_service(self, asset_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/fixed-assets/{asset_id}/place-in-service", payload, headers
        )

    def list_asset_count_lines(self, asset_id: str, headers: Dict,
                               params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fixed-assets/{asset_id}/count-lines",
            headers=headers, params=params,
        )

    def list_asset_external_schedules(self, asset_id: str, headers: Dict,
                                      params: Optional[Dict] = None):
        return self._request(
            "GET", f"/fixed-assets/{asset_id}/external-schedules",
            headers=headers, params=params,
        )

    # --- depreciation runs / entries ---
    def create_depreciation_run(self, payload: Dict, headers: Dict):
        return self._request("POST", "/depreciation-runs", payload, headers)

    def get_depreciation_run(self, run_id: str, headers: Dict):
        return self._request("GET", f"/depreciation-runs/{run_id}", headers=headers)

    def post_depreciation_run(self, run_id: str, headers: Dict):
        return self._request("POST", f"/depreciation-runs/{run_id}/post", {}, headers)

    def list_depreciation_entries(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/depreciation-entries", headers=headers,
                             params=params)

    def get_depreciation_entry(self, entry_id: str, headers: Dict):
        return self._request("GET", f"/depreciation-entries/{entry_id}", headers=headers)

    # --- disposals ---
    def create_disposal(self, payload: Dict, headers: Dict):
        return self._request("POST", "/disposals", payload, headers)

    def list_disposals(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/disposals", headers=headers, params=params)

    def get_disposal(self, disposal_id: str, headers: Dict):
        return self._request("GET", f"/disposals/{disposal_id}", headers=headers)

    def approve_disposal(self, disposal_id: str, headers: Dict):
        return self._request("POST", f"/disposals/{disposal_id}/approve", {}, headers)

    def reject_disposal(self, disposal_id: str, payload: Optional[Dict], headers: Dict):
        return self._request(
            "POST", f"/disposals/{disposal_id}/reject", payload or {}, headers
        )

    def resubmit_disposal(self, disposal_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/disposals/{disposal_id}/resubmit", payload, headers
        )

    def post_disposal(self, disposal_id: str, headers: Dict):
        return self._request("POST", f"/disposals/{disposal_id}/post", {}, headers)

    # --- inventory runs / count lines ---
    def create_inventory_run(self, payload: Dict, headers: Dict):
        return self._request("POST", "/inventory-runs", payload, headers)

    def get_inventory_run(self, run_id: str, headers: Dict):
        return self._request("GET", f"/inventory-runs/{run_id}", headers=headers)

    def upsert_count_line(self, run_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/inventory-runs/{run_id}/count-lines", payload, headers
        )

    def list_run_count_lines(self, run_id: str, headers: Dict,
                             params: Optional[Dict] = None):
        return self._request(
            "GET", f"/inventory-runs/{run_id}/count-lines",
            headers=headers, params=params,
        )

    def begin_reconciliation(self, run_id: str, headers: Dict):
        return self._request(
            "POST", f"/inventory-runs/{run_id}/begin-reconciliation", {}, headers
        )

    def recount_inventory_run(self, run_id: str, headers: Dict):
        return self._request("POST", f"/inventory-runs/{run_id}/recount", {}, headers)

    def close_inventory_run(self, run_id: str, headers: Dict):
        return self._request("POST", f"/inventory-runs/{run_id}/close", {}, headers)

    # --- impairment reviews ---
    def create_impairment_review(self, payload: Dict, headers: Dict):
        return self._request("POST", "/impairment-reviews", payload, headers)

    def list_impairment_reviews(self, headers: Dict, params: Optional[Dict] = None):
        return self._request("GET", "/impairment-reviews", headers=headers,
                             params=params)

    def get_impairment_review(self, review_id: str, headers: Dict):
        return self._request("GET", f"/impairment-reviews/{review_id}", headers=headers)

    def confirm_impairment_review(self, review_id: str, payload: Dict, headers: Dict):
        return self._request(
            "POST", f"/impairment-reviews/{review_id}/confirm", payload, headers
        )

    def dismiss_impairment_review(self, review_id: str, headers: Dict):
        return self._request(
            "POST", f"/impairment-reviews/{review_id}/dismiss", {}, headers
        )

    # --- external schedules ---
    def create_external_schedule(self, payload: Dict, headers: Dict):
        return self._request("POST", "/external-schedules", payload, headers)

    def apply_external_schedule(self, schedule_id: str, headers: Dict):
        return self._request(
            "POST", f"/external-schedules/{schedule_id}/apply", {}, headers
        )


api_client = ApiClient()
