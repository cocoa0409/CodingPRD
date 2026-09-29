"""One method per documented endpoint of the residency administration API."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin transport wrapper; every method returns the raw HTTP response."""

    # -----------------------------------------------------------------
    # Logical clock
    # -----------------------------------------------------------------
    def set_clock(self, current_utc: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # -----------------------------------------------------------------
    # Cycles
    # -----------------------------------------------------------------
    def create_cycle(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/cycles", payload, headers)

    def list_cycles(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cycles", params, headers)

    def get_cycle(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cycles/{cycle_id}", None, headers)

    def update_cycle(self, cycle_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/cycles/{cycle_id}", payload, headers)

    def advance_cycle_stage(self, cycle_id: str, to_status: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/cycles/{cycle_id}/stage", {"to_status": to_status}, headers
        )

    def lock_slate(self, cycle_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/cycles/{cycle_id}/lock-slate", None, headers)

    def get_funder_outcome_report(self, cycle_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cycles/{cycle_id}/funder-outcome-report", None, headers
        )

    # -----------------------------------------------------------------
    # Disciplines
    # -----------------------------------------------------------------
    def create_discipline(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/disciplines", payload, headers)

    def list_disciplines(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/disciplines", params, headers)

    def get_discipline(self, discipline_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/disciplines/{discipline_id}", None, headers)

    # -----------------------------------------------------------------
    # Applicants
    # -----------------------------------------------------------------
    def create_applicant(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/applicants", payload, headers)

    def list_applicants(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/applicants", params, headers)

    def get_applicant(self, applicant_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/applicants/{applicant_id}", None, headers)

    def update_applicant(self, applicant_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/applicants/{applicant_id}", payload, headers)

    # -----------------------------------------------------------------
    # Applications
    # -----------------------------------------------------------------
    def create_application(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/applications", params, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/applications/{application_id}", None, headers)

    def update_application(
        self, application_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request("PATCH", f"/applications/{application_id}", payload, headers)

    def resolve_application_fee(
        self, application_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/applications/{application_id}/fee-resolution", payload, headers
        )

    def submit_application(
        self, application_id: str, headers: Dict[str, str], payload: Any = None
    ):
        return self._request(
            "POST", f"/applications/{application_id}/submit", payload, headers
        )

    def decide_screening(
        self, application_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/applications/{application_id}/screening-decision", payload, headers
        )

    def respond_to_offer(
        self, application_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/applications/{application_id}/offer-response", payload, headers
        )

    # -----------------------------------------------------------------
    # Portfolio items
    # -----------------------------------------------------------------
    def create_portfolio_item(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/portfolio-items", payload, headers)

    def list_portfolio_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/portfolio-items", params, headers)

    def get_portfolio_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/portfolio-items/{item_id}", None, headers)

    def delete_portfolio_item(self, item_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"/portfolio-items/{item_id}", None, headers)

    # -----------------------------------------------------------------
    # Panelists
    # -----------------------------------------------------------------
    def create_panelist(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/panelists", payload, headers)

    def list_panelists(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/panelists", params, headers)

    def get_panelist(self, panelist_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/panelists/{panelist_id}", None, headers)

    def update_panelist(self, panelist_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/panelists/{panelist_id}", payload, headers)

    # -----------------------------------------------------------------
    # Panel assignments
    # -----------------------------------------------------------------
    def create_panel_assignment(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/panel-assignments", payload, headers)

    def list_panel_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/panel-assignments", params, headers)

    def get_panel_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/panel-assignments/{assignment_id}", None, headers)

    def submit_scores(self, assignment_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/panel-assignments/{assignment_id}/scores", payload, headers
        )

    def declare_conflict(self, assignment_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/panel-assignments/{assignment_id}/declare-conflict",
            payload,
            headers,
        )

    # -----------------------------------------------------------------
    # Residencies
    # -----------------------------------------------------------------
    def create_residency(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/residencies", payload, headers)

    def list_residencies(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/residencies", params, headers)

    def get_residency(self, residency_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/residencies/{residency_id}", None, headers)

    def schedule_residency(
        self, residency_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/residencies/{residency_id}/schedule", payload, headers
        )

    def residency_lifecycle(
        self, residency_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/residencies/{residency_id}/lifecycle", payload, headers
        )

    def residency_compliance(
        self, residency_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/residencies/{residency_id}/compliance", payload, headers
        )

    def record_training(self, residency_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/residencies/{residency_id}/trainings", payload, headers
        )

    def generate_stipend_schedule(
        self, residency_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/residencies/{residency_id}/stipend-schedule", payload, headers
        )

    def get_tax_report(self, residency_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/residencies/{residency_id}/tax-report", None, headers
        )

    # -----------------------------------------------------------------
    # Studios
    # -----------------------------------------------------------------
    def create_studio(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/studios", payload, headers)

    def list_studios(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/studios", params, headers)

    def get_studio(self, studio_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studios/{studio_id}", None, headers)

    def update_studio(self, studio_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/studios/{studio_id}", payload, headers)

    # -----------------------------------------------------------------
    # Studio assignments
    # -----------------------------------------------------------------
    def create_studio_assignment(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/studio-assignments", payload, headers)

    def list_studio_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/studio-assignments", params, headers)

    def get_studio_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/studio-assignments/{assignment_id}", None, headers)

    def release_studio_assignment(
        self, assignment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/studio-assignments/{assignment_id}/release", payload, headers
        )

    # -----------------------------------------------------------------
    # Housing units
    # -----------------------------------------------------------------
    def create_housing_unit(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/housing-units", payload, headers)

    def list_housing_units(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/housing-units", params, headers)

    def get_housing_unit(self, unit_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/housing-units/{unit_id}", None, headers)

    def update_housing_unit(self, unit_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("PATCH", f"/housing-units/{unit_id}", payload, headers)

    # -----------------------------------------------------------------
    # Housing assignments
    # -----------------------------------------------------------------
    def create_housing_assignment(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/housing-assignments", payload, headers)

    def list_housing_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request("GET", "/housing-assignments", params, headers)

    def get_housing_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/housing-assignments/{assignment_id}", None, headers)

    def release_housing_assignment(
        self, assignment_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/housing-assignments/{assignment_id}/release", payload, headers
        )

    # -----------------------------------------------------------------
    # Visa cases
    # -----------------------------------------------------------------
    def create_visa_case(self, payload: Any, headers: Dict[str, str]):
        return self._request("POST", "/visa-cases", payload, headers)

    def list_visa_cases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/visa-cases", params, headers)

    def get_visa_case(self, case_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/visa-cases/{case_id}", None, headers)

    def visa_docs(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request("POST", f"/visa-cases/{case_id}/docs", payload, headers)

    def visa_adjudication(self, case_id: str, payload: Any, headers: Dict[str, str]):
        return self._request(
            "POST", f"/visa-cases/{case_id}/adjudication", payload, headers
        )

    # -----------------------------------------------------------------
    # Stipend disbursements
    # -----------------------------------------------------------------
    def list_disbursements(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/stipend-disbursements", params, headers)

    def get_disbursement(self, disbursement_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/stipend-disbursements/{disbursement_id}", None, headers
        )

    def settle_disbursement(
        self, disbursement_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/stipend-disbursements/{disbursement_id}/settlement",
            payload,
            headers,
        )

    # -----------------------------------------------------------------
    # Obligations
    # -----------------------------------------------------------------
    def list_obligations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/obligations", params, headers)

    def get_obligation(self, obligation_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/obligations/{obligation_id}", None, headers)

    def update_obligation_progress(
        self, obligation_id: str, payload: Any, headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/obligations/{obligation_id}/progress", payload, headers
        )
