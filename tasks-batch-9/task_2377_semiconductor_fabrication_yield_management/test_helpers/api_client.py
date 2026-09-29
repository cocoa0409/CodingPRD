"""Typed client for the Semiconductor Fab Yield API.

Wraps the shared ``GenericApiClient`` with one named method per route so no
test ever hand-builds a URL.  Every method returns the raw ``requests``
response; callers pass it to ``validate_success`` / ``validate_error`` /
``validate_paginated`` to make an assertion.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing.client import GenericApiClient

from .constants import API_PREFIX, CLOCK_PATH


class FabApiClient:
    """Route-aware facade over the generic HTTP client."""

    def __init__(self, base_url: Optional[str] = None):
        self._client = GenericApiClient(base_url)

    # -- plumbing ---------------------------------------------------------

    @property
    def raw(self) -> GenericApiClient:
        return self._client

    def _get(self, path, headers=None, params=None):
        return self._client._request("GET", path, params=params, headers=headers)

    def _post(self, path, payload=None, headers=None):
        return self._client._request("POST", path, payload=payload or {}, headers=headers)

    def _patch(self, path, payload=None, headers=None):
        return self._client._request("PATCH", path, payload=payload or {}, headers=headers)

    def request_without_headers(self, method: str, path: str, payload=None):
        """Issue a request carrying no identity headers at all (PRD §2.1)."""
        return self._client._request(method, path, payload=payload)

    # -- logical clock (PRD §2.4) -----------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._post(CLOCK_PATH, {"to_iso8601": to_iso8601}, headers)

    # -- process flows (PRD §3.1) -----------------------------------------

    def create_process_flow(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/process-flows", payload, headers)

    def get_process_flow(self, flow_id: str, headers):
        return self._get(API_PREFIX + "/process-flows/%s" % flow_id, headers)

    def list_process_flows(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/process-flows", headers, params)

    def add_process_step(self, flow_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/process-flows/%s/steps" % flow_id, payload, headers
        )

    def release_process_flow(self, flow_id: str, headers, payload=None):
        return self._post(
            API_PREFIX + "/process-flows/%s/release" % flow_id, payload or {}, headers
        )

    def get_process_step(self, step_id: str, headers):
        return self._get(API_PREFIX + "/process-steps/%s" % step_id, headers)

    def list_process_steps(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/process-steps", headers, params)

    # -- recipes (PRD §3.2) -----------------------------------------------

    def create_recipe(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/recipes", payload, headers)

    def get_recipe(self, recipe_id: str, headers):
        return self._get(API_PREFIX + "/recipes/%s" % recipe_id, headers)

    def list_recipes(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/recipes", headers, params)

    # -- engineering change notices (PRD §3.2) ----------------------------

    def create_change_request(self, recipe_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/recipes/%s/change-requests" % recipe_id, payload, headers
        )

    def get_change_request(self, cr_id: str, headers):
        return self._get(API_PREFIX + "/change-requests/%s" % cr_id, headers)

    def list_change_requests(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/change-requests", headers, params)

    def request_change_revision(self, cr_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/change-requests/%s/request-revision" % cr_id, payload, headers
        )

    def resubmit_change_request(self, cr_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/change-requests/%s/resubmit" % cr_id, payload, headers
        )

    def approve_change_request(self, cr_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/change-requests/%s/approve" % cr_id, payload, headers
        )

    def implement_change_request(self, cr_id: str, headers, payload=None):
        return self._post(
            API_PREFIX + "/change-requests/%s/implement" % cr_id, payload or {}, headers
        )

    # -- SPC charts (PRD §3.7) --------------------------------------------

    def create_spc_chart(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/spc-charts", payload, headers)

    def get_spc_chart(self, chart_id: str, headers):
        return self._get(API_PREFIX + "/spc-charts/%s" % chart_id, headers)

    def list_spc_charts(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/spc-charts", headers, params)

    # -- equipment (PRD §3.3) ---------------------------------------------

    def create_equipment(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/equipment", payload, headers)

    def get_equipment(self, equipment_id: str, headers):
        return self._get(API_PREFIX + "/equipment/%s" % equipment_id, headers)

    def list_equipment(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/equipment", headers, params)

    def pm_start(self, equipment_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/equipment/%s/pm-start" % equipment_id, payload, headers
        )

    def pm_complete(self, equipment_id: str, headers, payload=None):
        return self._post(
            API_PREFIX + "/equipment/%s/pm-complete" % equipment_id, payload or {}, headers
        )

    # -- chambers (PRD §3.3, §3.7) ----------------------------------------

    def create_chamber(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/chambers", payload, headers)

    def get_chamber(self, chamber_id: str, headers):
        return self._get(API_PREFIX + "/chambers/%s" % chamber_id, headers)

    def list_chambers(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/chambers", headers, params)

    def create_qualification_run(self, chamber_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/chambers/%s/qualification-runs" % chamber_id, payload, headers
        )

    def create_particle_reading(self, chamber_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/chambers/%s/particle-readings" % chamber_id, payload, headers
        )

    # -- operators (PRD §3.6) ---------------------------------------------

    def create_operator(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/operators", payload, headers)

    def get_operator(self, operator_id: str, headers):
        return self._get(API_PREFIX + "/operators/%s" % operator_id, headers)

    def list_operators(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/operators", headers, params)

    def patch_operator(self, operator_id: str, payload: Dict[str, Any], headers):
        return self._patch(API_PREFIX + "/operators/%s" % operator_id, payload, headers)

    # -- wafer start plans (PRD §3.4) -------------------------------------

    def create_plan(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/wafer-start-plans", payload, headers)

    def get_plan(self, plan_id: str, headers):
        return self._get(API_PREFIX + "/wafer-start-plans/%s" % plan_id, headers)

    def list_plans(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/wafer-start-plans", headers, params)

    def commit_plan(self, plan_id: str, headers, payload=None):
        return self._post(
            API_PREFIX + "/wafer-start-plans/%s/commit" % plan_id, payload or {}, headers
        )

    # -- lots (PRD §3.5, §3.8) --------------------------------------------

    def create_lot(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/lots", payload, headers)

    def get_lot(self, lot_id: str, headers):
        return self._get(API_PREFIX + "/lots/%s" % lot_id, headers)

    def list_lots(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/lots", headers, params)

    def release_lot(self, lot_id: str, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/lots/%s/release" % lot_id, payload, headers)

    def split_lot(self, lot_id: str, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/lots/%s/splits" % lot_id, payload, headers)

    def rejoin_lot(self, lot_id: str, headers, payload=None):
        return self._post(API_PREFIX + "/lots/%s/rejoin" % lot_id, payload or {}, headers)

    def rework_lot(self, lot_id: str, headers, payload=None):
        return self._post(API_PREFIX + "/lots/%s/rework" % lot_id, payload or {}, headers)

    def get_cycle_time_projection(self, lot_id: str, headers):
        return self._get(API_PREFIX + "/lots/%s/cycle-time-projection" % lot_id, headers)

    # -- step runs (PRD §3.6) ---------------------------------------------

    def create_step_run(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/step-runs", payload, headers)

    def get_step_run(self, run_id: str, headers):
        return self._get(API_PREFIX + "/step-runs/%s" % run_id, headers)

    def list_step_runs(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/step-runs", headers, params)

    def track_out(self, run_id: str, headers, payload=None):
        return self._post(
            API_PREFIX + "/step-runs/%s/track-out" % run_id, payload or {}, headers
        )

    def abort_step_run(self, run_id: str, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/step-runs/%s/abort" % run_id, payload, headers)

    # -- metrology (PRD §3.7) ---------------------------------------------

    def create_measurement(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/measurements", payload, headers)

    def get_measurement(self, measurement_id: str, headers):
        return self._get(API_PREFIX + "/measurements/%s" % measurement_id, headers)

    def list_measurements(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/measurements", headers, params)

    def patch_measurement(self, measurement_id: str, payload: Dict[str, Any], headers):
        """No mutation route exists for a measurement; used to prove that."""
        return self._patch(
            API_PREFIX + "/measurements/%s" % measurement_id, payload, headers
        )

    # -- excursions (PRD §3.7, §3.8) --------------------------------------

    def get_excursion(self, excursion_id: str, headers):
        return self._get(API_PREFIX + "/excursions/%s" % excursion_id, headers)

    def list_excursions(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/excursions", headers, params)

    def contain_excursion(self, excursion_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/excursions/%s/contain" % excursion_id, payload, headers
        )

    def disposition_excursion(self, excursion_id: str, payload: Dict[str, Any], headers):
        return self._post(
            API_PREFIX + "/excursions/%s/disposition" % excursion_id, payload, headers
        )

    # -- die sort (PRD §3.9) ----------------------------------------------

    def create_die_sort_run(self, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/die-sort-runs", payload, headers)

    def get_die_sort_run(self, run_id: str, headers):
        return self._get(API_PREFIX + "/die-sort-runs/%s" % run_id, headers)

    def list_die_sort_runs(self, headers, params: Optional[Dict[str, Any]] = None):
        return self._get(API_PREFIX + "/die-sort-runs", headers, params)

    def bin_die_sort_run(self, run_id: str, payload: Dict[str, Any], headers):
        return self._post(API_PREFIX + "/die-sort-runs/%s/bin" % run_id, payload, headers)
