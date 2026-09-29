"""One method per endpoint of the marketing-mix / incrementality API.

Every business endpoint is mounted under `/mmm`; the logical-clock endpoint is
the single exception and sits at the service root. Methods hand back the raw
`requests.Response` so a test can assert on the status code as well as the body.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import CLOCK_PATH

PREFIX = "/mmm"


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the marketing-mix modelling service."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(
        self, current_utc: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", CLOCK_PATH, {"current_utc": current_utc}, headers)

    def set_clock_raw(
        self, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ) -> requests.Response:
        """Post an arbitrary body to the clock endpoint (shape-validation probes)."""
        return self._request("POST", CLOCK_PATH, payload, headers)

    # ------------------------------------------------------------------
    # Markets
    # ------------------------------------------------------------------

    def create_market(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/markets", payload, headers)

    def list_markets(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/markets", params, headers)

    def get_market(
        self, market_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/markets/{market_id}", None, headers)

    def washout_sweep(
        self,
        market_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/markets/{market_id}/washout-sweep", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Media channels
    # ------------------------------------------------------------------

    def create_media_channel(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/media-channels", payload, headers)

    def list_media_channels(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/media-channels", params, headers)

    def get_media_channel(
        self, channel_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/media-channels/{channel_id}", None, headers
        )

    def patch_media_channel(
        self, channel_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "PATCH", f"{PREFIX}/media-channels/{channel_id}", payload, headers
        )

    # ------------------------------------------------------------------
    # Geo cells
    # ------------------------------------------------------------------

    def create_geo_cell(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/geo-cells", payload, headers)

    def list_geo_cells(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/geo-cells", params, headers)

    def get_geo_cell(self, cell_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/geo-cells/{cell_id}", None, headers)

    # ------------------------------------------------------------------
    # Data windows
    # ------------------------------------------------------------------

    def create_data_window(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/data-windows", payload, headers)

    def list_data_windows(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/data-windows", params, headers)

    def get_data_window(
        self, window_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/data-windows/{window_id}", None, headers)

    def seal_data_window(
        self,
        window_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/data-windows/{window_id}/seal", payload or {}, headers
        )

    def reopen_data_window(
        self, window_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/data-windows/{window_id}/reopen", payload, headers
        )

    # ------------------------------------------------------------------
    # Observations
    # ------------------------------------------------------------------

    def create_spend_observation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/spend-observations", payload, headers)

    def list_spend_observations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/spend-observations", params, headers)

    def get_spend_observation(
        self, observation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/spend-observations/{observation_id}", None, headers
        )

    def create_sales_observation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/sales-observations", payload, headers)

    def list_sales_observations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/sales-observations", params, headers)

    def get_sales_observation(
        self, observation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/sales-observations/{observation_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Model runs and their four actions
    # ------------------------------------------------------------------

    def create_model_run(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/model-runs", payload, headers)

    def list_model_runs(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/model-runs", params, headers)

    def get_model_run(self, run_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"{PREFIX}/model-runs/{run_id}", None, headers)

    def fit_model_run(
        self,
        run_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/model-runs/{run_id}/fit", payload or {}, headers
        )

    def validate_model_run(
        self,
        run_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/model-runs/{run_id}/validate", payload or {}, headers
        )

    def publish_model_run(
        self,
        run_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/model-runs/{run_id}/publish", payload or {}, headers
        )

    def recalibrate_model_run(
        self,
        run_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/model-runs/{run_id}/recalibrate", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Channel contributions (read-only: written by the fit)
    # ------------------------------------------------------------------

    def list_channel_contributions(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/channel-contributions", params, headers)

    def get_channel_contribution(
        self, contribution_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/channel-contributions/{contribution_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Experiments and their seven actions
    # ------------------------------------------------------------------

    def create_experiment(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/experiments", payload, headers)

    def list_experiments(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/experiments", params, headers)

    def get_experiment(
        self, experiment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/experiments/{experiment_id}", None, headers)

    def lock_design(
        self,
        experiment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/experiments/{experiment_id}/lock-design",
            payload or {},
            headers,
        )

    def assign_cells(
        self, experiment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/experiments/{experiment_id}/assign-cells",
            payload,
            headers,
        )

    def start_experiment(
        self,
        experiment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/experiments/{experiment_id}/start",
            payload or {},
            headers,
        )

    def read_out_experiment(
        self, experiment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/experiments/{experiment_id}/read-out", payload, headers
        )

    def accept_experiment(
        self,
        experiment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/experiments/{experiment_id}/accept",
            payload or {},
            headers,
        )

    def reject_experiment(
        self, experiment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/experiments/{experiment_id}/reject", payload, headers
        )

    def release_cells(
        self,
        experiment_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/experiments/{experiment_id}/release-cells",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Calibration records
    # ------------------------------------------------------------------

    def create_calibration_record(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/calibration-records", payload, headers)

    def list_calibration_records(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/calibration-records", params, headers)

    def get_calibration_record(
        self, record_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/calibration-records/{record_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Budget scenarios, allocations and the three scenario actions
    # ------------------------------------------------------------------

    def create_budget_scenario(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/budget-scenarios", payload, headers)

    def list_budget_scenarios(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/budget-scenarios", params, headers)

    def get_budget_scenario(
        self, scenario_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/budget-scenarios/{scenario_id}", None, headers
        )

    def create_budget_allocation(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"{PREFIX}/budget-allocations", payload, headers)

    def list_budget_allocations(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request("GET", f"{PREFIX}/budget-allocations", params, headers)

    def get_budget_allocation(
        self, allocation_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/budget-allocations/{allocation_id}", None, headers
        )

    def optimize_budget_scenario(
        self,
        scenario_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/budget-scenarios/{scenario_id}/optimize",
            payload or {},
            headers,
        )

    def revert_optimization(
        self,
        scenario_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/budget-scenarios/{scenario_id}/revert-optimization",
            payload or {},
            headers,
        )

    def approve_budget_scenario(
        self,
        scenario_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{PREFIX}/budget-scenarios/{scenario_id}/approve",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Reconciliation reports
    # ------------------------------------------------------------------

    def create_reconciliation_report(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"{PREFIX}/reconciliation-reports", payload, headers
        )

    def list_reconciliation_reports(
        self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/reconciliation-reports", params, headers
        )

    def get_reconciliation_report(
        self, report_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "GET", f"{PREFIX}/reconciliation-reports/{report_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Raw probes, for sweeping every collection with one loop
    # ------------------------------------------------------------------

    def get_collection_item(
        self, collection: str, item_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        """GET /mmm/{collection}/{item_id} for an arbitrary collection segment."""
        return self._request("GET", f"{PREFIX}/{collection}/{item_id}", None, headers)

    def get_collection(
        self,
        collection: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """GET /mmm/{collection} for an arbitrary collection segment."""
        return self._request("GET", f"{PREFIX}/{collection}", params, headers)

    def post_collection(
        self,
        collection: str,
        payload: Optional[Dict[str, Any]],
        headers: Dict[str, str],
    ) -> requests.Response:
        """POST /mmm/{collection} with an arbitrary body."""
        return self._request("POST", f"{PREFIX}/{collection}", payload, headers)
