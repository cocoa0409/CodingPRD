"""HTTP client for the LED Display Manufacturing API.

One method per operation in the endpoint table. Every method returns the raw
response so tests can assert both the status code and the envelope.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class LedDisplayApiClient(GenericApiClient):
    """Endpoint methods for every operation the requirements document declares."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Display models
    # ------------------------------------------------------------------

    def create_display_model(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/display-models", payload, headers)

    def get_display_model(self, display_model_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/display-models/{display_model_id}", None, headers)

    def list_display_models(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/display-models", params, headers)

    # ------------------------------------------------------------------
    # Burn-in chambers
    # ------------------------------------------------------------------

    def create_burn_in_chamber(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/burn-in-chambers", payload, headers)

    def get_burn_in_chamber(self, burn_in_chamber_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/burn-in-chambers/{burn_in_chamber_id}", None, headers
        )

    def list_burn_in_chambers(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/burn-in-chambers", params, headers)

    # ------------------------------------------------------------------
    # Commissioning crews
    # ------------------------------------------------------------------

    def create_commissioning_crew(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/commissioning-crews", payload, headers)

    def get_commissioning_crew(
        self, commissioning_crew_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/commissioning-crews/{commissioning_crew_id}", None, headers
        )

    def list_commissioning_crews(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/commissioning-crews", params, headers)

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def create_project(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/projects/{project_id}", None, headers)

    def list_projects(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/projects", params, headers)

    # ------------------------------------------------------------------
    # Drawing revisions
    # ------------------------------------------------------------------

    def create_drawing_revision(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/drawing-revisions", payload, headers)

    def review_drawing_revision(
        self, drawing_revision_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/drawing-revisions/{drawing_revision_id}/review", payload, headers
        )

    def get_drawing_revision(self, drawing_revision_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/drawing-revisions/{drawing_revision_id}", None, headers
        )

    def list_drawing_revisions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/drawing-revisions", params, headers)

    # ------------------------------------------------------------------
    # Modules
    # ------------------------------------------------------------------

    def create_module(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/modules", payload, headers)

    def pixel_test_module(
        self, module_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/modules/{module_id}/pixel-test", payload, headers
        )

    def calibrate_module(self, module_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/modules/{module_id}/calibrate", payload, headers
        )

    def get_module(self, module_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/modules/{module_id}", None, headers)

    def list_modules(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/modules", params, headers)

    # ------------------------------------------------------------------
    # Cabinets
    # ------------------------------------------------------------------

    def create_cabinet(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/cabinets", payload, headers)

    def install_module(self, cabinet_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cabinets/{cabinet_id}/modules", payload, headers
        )

    def remove_module(self, cabinet_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cabinets/{cabinet_id}/module-removals", payload, headers
        )

    def qa_approve_cabinet(
        self, cabinet_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/cabinets/{cabinet_id}/qa-approve", payload, headers
        )

    def mount_cabinet(
        self, cabinet_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request("POST", f"/cabinets/{cabinet_id}/mount", payload, headers)

    def get_cabinet(self, cabinet_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cabinets/{cabinet_id}", None, headers)

    def list_cabinets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cabinets", params, headers)

    # ------------------------------------------------------------------
    # Burn-in runs
    # ------------------------------------------------------------------

    def create_burn_in_run(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/burn-in-runs", payload, headers)

    def complete_burn_in_run(
        self, burn_in_run_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/burn-in-runs/{burn_in_run_id}/complete", payload, headers
        )

    def abort_burn_in_run(
        self, burn_in_run_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/burn-in-runs/{burn_in_run_id}/abort", payload, headers
        )

    def get_burn_in_run(self, burn_in_run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/burn-in-runs/{burn_in_run_id}", None, headers)

    def list_burn_in_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/burn-in-runs", params, headers)

    # ------------------------------------------------------------------
    # Commissioning visits
    # ------------------------------------------------------------------

    def create_commissioning_visit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/commissioning-visits", payload, headers)

    def arrive_at_visit(
        self, commissioning_visit_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST",
            f"/commissioning-visits/{commissioning_visit_id}/arrive",
            payload,
            headers,
        )

    def calibrate_visit(
        self, commissioning_visit_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/commissioning-visits/{commissioning_visit_id}/calibrate",
            payload,
            headers,
        )

    def sign_off_visit(
        self, commissioning_visit_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST",
            f"/commissioning-visits/{commissioning_visit_id}/sign-off",
            payload,
            headers,
        )

    def get_commissioning_visit(
        self, commissioning_visit_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "GET", f"/commissioning-visits/{commissioning_visit_id}", None, headers
        )

    def list_commissioning_visits(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/commissioning-visits", params, headers)

    # ------------------------------------------------------------------
    # Service contracts
    # ------------------------------------------------------------------

    def create_service_contract(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/service-contracts", payload, headers)

    def get_service_contract(self, service_contract_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/service-contracts/{service_contract_id}", None, headers
        )

    def list_service_contracts(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/service-contracts", params, headers)

    def reserve_spare(
        self, service_contract_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/service-contracts/{service_contract_id}/spare-reservations",
            payload,
            headers,
        )

    def release_spare(
        self, service_contract_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/service-contracts/{service_contract_id}/spare-releases",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Service cases
    # ------------------------------------------------------------------

    def create_service_case(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/service-cases", payload, headers)

    def respond_to_case(
        self, service_case_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/service-cases/{service_case_id}/respond", payload, headers
        )

    def assess_case(self, service_case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/service-cases/{service_case_id}/assess", payload, headers
        )

    def fulfil_case(self, service_case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/service-cases/{service_case_id}/fulfil", payload, headers
        )

    def get_service_case(self, service_case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/service-cases/{service_case_id}", None, headers)

    def list_service_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/service-cases", params, headers)

    # ------------------------------------------------------------------
    # Raw request escape hatch for header and shape probes
    # ------------------------------------------------------------------

    def raw(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ):
        return self._request(method, path, payload, headers, params)
