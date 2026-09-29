"""One method per endpoint row of PRD section 4.

Every method returns the raw ``requests.Response`` so a test can assert the
status code itself. Listing methods take ``params`` for the `limit` / `offset`
parameters of PRD 2.3 plus each listing's own domain filters.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]
Headers = Dict[str, str]


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Utility-Scale Solar EPC API."""

    # ------------------------------------------------------------------
    # The logical site clock (PRD 2.5)
    # ------------------------------------------------------------------
    def set_clock(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Projects, scope and the commercial summary (PRD 3.1)
    # ------------------------------------------------------------------
    def create_project(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/solar/projects", payload, headers)

    def get_project(self, project_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/projects/{project_id}", None, headers)

    def list_projects(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/solar/projects", params, headers)

    def get_settlement_summary(
        self, project_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/projects/{project_id}/settlement-summary", None, headers
        )

    def create_change_order(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/change-orders", payload, headers
        )

    def create_labor_compliance_run(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/solar/projects/{project_id}/labor-compliance-runs",
            payload,
            headers,
        )

    def create_milestone_claim(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/milestone-claims", payload, headers
        )

    def create_milestone_decision(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/milestone-decisions", payload, headers
        )

    # ------------------------------------------------------------------
    # Grading areas, earthwork and site events (PRD 3.2)
    # ------------------------------------------------------------------
    def create_grading_area(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/grading-areas", payload, headers
        )

    def get_grading_area(
        self, grading_area_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/grading-areas/{grading_area_id}", None, headers
        )

    def list_project_grading_areas(
        self, project_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/projects/{project_id}/grading-areas", params, headers
        )

    def create_earthwork_log(
        self, grading_area_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/solar/grading-areas/{grading_area_id}/earthwork-logs",
            payload,
            headers,
        )

    def create_site_event(
        self, grading_area_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/solar/grading-areas/{grading_area_id}/site-events",
            payload,
            headers,
        )

    def accept_grading_area(
        self, grading_area_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/solar/grading-areas/{grading_area_id}/acceptance",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Laydown yard zones and deliveries (PRD 3.3)
    # ------------------------------------------------------------------
    def create_yard_zone(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/yard-zones", payload, headers
        )

    def get_yard_zone(self, yard_zone_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/yard-zones/{yard_zone_id}", None, headers)

    def list_project_yard_zones(
        self, project_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/projects/{project_id}/yard-zones", params, headers
        )

    def create_delivery(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/solar/deliveries", payload, headers)

    def get_delivery(self, delivery_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/deliveries/{delivery_id}", None, headers)

    def list_deliveries(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/solar/deliveries", params, headers)

    def receive_delivery(
        self, delivery_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/deliveries/{delivery_id}/receipt", payload, headers
        )

    def cancel_delivery(
        self, delivery_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/deliveries/{delivery_id}/cancellation", payload, headers
        )

    # ------------------------------------------------------------------
    # Blocks, piles and mechanical completion (PRD 3.4)
    # ------------------------------------------------------------------
    def create_block(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/blocks", payload, headers
        )

    def get_block(self, block_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/blocks/{block_id}", None, headers)

    def list_blocks(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/solar/blocks", params, headers)

    def create_pile(
        self, block_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", f"/solar/blocks/{block_id}/piles", payload, headers)

    def list_block_piles(
        self, block_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", f"/solar/blocks/{block_id}/piles", params, headers)

    def get_pile(self, pile_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/piles/{pile_id}", None, headers)

    def create_drive_result(
        self, pile_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/piles/{pile_id}/drive-results", payload, headers
        )

    def create_remediation(
        self, pile_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/piles/{pile_id}/remediations", payload, headers
        )

    def declare_mechanical_completion(
        self, block_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/blocks/{block_id}/mechanical-completion", payload, headers
        )

    # ------------------------------------------------------------------
    # String circuits, wiring and testing (PRD 3.5)
    # ------------------------------------------------------------------
    def create_string_circuit(
        self, block_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/blocks/{block_id}/string-circuits", payload, headers
        )

    def list_block_string_circuits(
        self, block_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/blocks/{block_id}/string-circuits", params, headers
        )

    def get_string_circuit(self, circuit_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/string-circuits/{circuit_id}", None, headers)

    def create_wiring(
        self, circuit_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/string-circuits/{circuit_id}/wiring", payload, headers
        )

    def create_string_test_result(
        self, circuit_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/string-circuits/{circuit_id}/test-results", payload, headers
        )

    # ------------------------------------------------------------------
    # Substation and utility coordination (PRD 3.6)
    # ------------------------------------------------------------------
    def create_substation(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/substations", payload, headers
        )

    def get_substation(self, substation_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/substations/{substation_id}", None, headers)

    def list_project_substations(
        self, project_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/projects/{project_id}/substations", params, headers
        )

    def create_status_advance(
        self, substation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/solar/substations/{substation_id}/status-advances",
            payload,
            headers,
        )

    def create_outage_window(
        self, substation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/substations/{substation_id}/outage-windows", payload, headers
        )

    def list_substation_outage_windows(
        self, substation_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/substations/{substation_id}/outage-windows", params, headers
        )

    def get_outage_window(self, window_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/outage-windows/{window_id}", None, headers)

    def create_utility_response(
        self, window_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/outage-windows/{window_id}/utility-response", payload, headers
        )

    # ------------------------------------------------------------------
    # Commissioning tests and measurement intervals (PRD 3.7)
    # ------------------------------------------------------------------
    def create_commissioning_test(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/solar/commissioning-tests", payload, headers)

    def get_commissioning_test(self, test_id: str, headers: Headers) -> requests.Response:
        return self._request(
            "GET", f"/solar/commissioning-tests/{test_id}", None, headers
        )

    def list_project_commissioning_tests(
        self, project_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/projects/{project_id}/commissioning-tests", params, headers
        )

    def create_test_interval(
        self, test_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/commissioning-tests/{test_id}/intervals", payload, headers
        )

    def list_test_intervals(
        self, test_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/commissioning-tests/{test_id}/intervals", params, headers
        )

    def finalize_commissioning_test(
        self, test_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/commissioning-tests/{test_id}/finalization", payload, headers
        )

    # ------------------------------------------------------------------
    # Punch list (PRD 3.9)
    # ------------------------------------------------------------------
    def create_punch_list_item(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/punch-list-items", payload, headers
        )

    def get_punch_list_item(self, item_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/punch-list-items/{item_id}", None, headers)

    def list_punch_list_items(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/solar/punch-list-items", params, headers)

    def create_closure_submission(
        self, item_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/solar/punch-list-items/{item_id}/closure-submissions",
            payload,
            headers,
        )

    def create_closure_decision(
        self, item_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/solar/punch-list-items/{item_id}/closure-decisions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Certified payroll (PRD 3.8)
    # ------------------------------------------------------------------
    def create_payroll_week(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/projects/{project_id}/payroll-weeks", payload, headers
        )

    def get_payroll_week(self, week_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/payroll-weeks/{week_id}", None, headers)

    def list_project_payroll_weeks(
        self, project_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/projects/{project_id}/payroll-weeks", params, headers
        )

    def create_labor_entry(
        self, week_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/payroll-weeks/{week_id}/labor-entries", payload, headers
        )

    def list_week_labor_entries(
        self, week_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/solar/payroll-weeks/{week_id}/labor-entries", params, headers
        )

    def get_labor_entry(self, entry_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/solar/labor-entries/{entry_id}", None, headers)

    def void_labor_entry(
        self, entry_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/labor-entries/{entry_id}/void", payload, headers
        )

    def certify_payroll_week(
        self, week_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/solar/payroll-weeks/{week_id}/certification", payload, headers
        )


api_client = ApiClient()
