"""API client: one method per endpoint defined in the PRD."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------- Preservation programs ----------------

    def create_program(self, payload: dict, headers: dict):
        return self._request("POST", "/preservation-programs", payload, headers)

    def get_program(self, program_id: str, headers: dict):
        return self._request(
            "GET", f"/preservation-programs/{program_id}", headers=headers
        )

    # ---------------- Funding rounds ----------------

    def create_funding_round(self, payload: dict, headers: dict):
        return self._request("POST", "/funding-rounds", payload, headers)

    def get_funding_round(self, round_id: str, headers: dict):
        return self._request("GET", f"/funding-rounds/{round_id}", headers=headers)

    def list_funding_rounds(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/funding-rounds", headers=headers, params=params)

    def open_funding_round(self, round_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST", f"/funding-rounds/{round_id}/opening", payload if payload is not None else {}, headers
        )

    def rank_funding_round(self, round_id: str, payload: dict, headers: dict):
        return self._request("POST", f"/funding-rounds/{round_id}/rank", payload, headers)

    # ---------------- Landowners ----------------

    def create_landowner(self, payload: dict, headers: dict):
        return self._request("POST", "/landowners", payload, headers)

    def get_landowner(self, landowner_id: str, headers: dict):
        return self._request("GET", f"/landowners/{landowner_id}", headers=headers)

    # ---------------- Parcels ----------------

    def create_parcel(self, payload: dict, headers: dict):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id: str, headers: dict):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def list_parcels(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/parcels", headers=headers, params=params)

    def patch_parcel(self, parcel_id: str, payload: dict, headers: dict):
        return self._request("PATCH", f"/parcels/{parcel_id}", payload, headers)

    # ---------------- Applications ----------------

    def create_application(self, payload: dict, headers: dict):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id: str, headers: dict):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def issue_offer(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/offers", payload, headers
        )

    def file_counter(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/counters", payload, headers
        )

    def accept_application(self, application_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/applications/{application_id}/acceptance",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_application(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/withdrawal", payload, headers
        )

    def assemble_funding_plan(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/funding-plan", payload, headers
        )

    def list_negotiation_rounds(
        self, application_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/applications/{application_id}/negotiation-rounds",
            headers=headers,
            params=params,
        )

    def list_closing_requirements(
        self, application_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/applications/{application_id}/closing-requirements",
            headers=headers,
            params=params,
        )

    def record_closing(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/closing", payload, headers
        )

    def cancel_closing(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/applications/{application_id}/closing-cancellation",
            payload,
            headers,
        )

    # ---------------- Appraisals ----------------

    def engage_appraisal(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/applications/{application_id}/appraisals", payload, headers
        )

    def list_appraisals(
        self, application_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/applications/{application_id}/appraisals",
            headers=headers,
            params=params,
        )

    def get_appraisal(self, appraisal_id: str, headers: dict):
        return self._request("GET", f"/appraisals/{appraisal_id}", headers=headers)

    def submit_appraisal(self, appraisal_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/submission", payload, headers
        )

    def review_appraisal(self, appraisal_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/appraisals/{appraisal_id}/review", payload, headers
        )

    # ---------------- Funding sources ----------------

    def create_funding_source(self, payload: dict, headers: dict):
        return self._request("POST", "/funding-sources", payload, headers)

    def get_funding_source(self, source_id: str, headers: dict):
        return self._request("GET", f"/funding-sources/{source_id}", headers=headers)

    def list_funding_sources(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/funding-sources", headers=headers, params=params)

    def suspend_funding_source(self, source_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/funding-sources/{source_id}/suspension", payload, headers
        )

    # ---------------- Funding commitments ----------------

    def get_funding_commitment(self, commitment_id: str, headers: dict):
        return self._request(
            "GET", f"/funding-commitments/{commitment_id}", headers=headers
        )

    def list_funding_commitments(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", "/funding-commitments", headers=headers, params=params
        )

    # ---------------- Closing requirements ----------------

    def get_closing_requirement(self, requirement_id: str, headers: dict):
        return self._request(
            "GET", f"/closing-requirements/{requirement_id}", headers=headers
        )

    def submit_closing_requirement(self, requirement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/closing-requirements/{requirement_id}/submission", payload, headers
        )

    def review_closing_requirement(self, requirement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/closing-requirements/{requirement_id}/review", payload, headers
        )

    def waive_closing_requirement(self, requirement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/closing-requirements/{requirement_id}/waiver", payload, headers
        )

    # ---------------- Easements ----------------

    def get_easement(self, easement_id: str, headers: dict):
        return self._request("GET", f"/easements/{easement_id}", headers=headers)

    def list_easements(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/easements", headers=headers, params=params)

    def record_impervious_request(self, easement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/easements/{easement_id}/impervious-requests", payload, headers
        )

    def list_monitoring_visits(
        self, easement_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/easements/{easement_id}/monitoring-visits",
            headers=headers,
            params=params,
        )

    def list_easement_violations(
        self, easement_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/easements/{easement_id}/violations", headers=headers, params=params
        )

    def list_easement_amendments(
        self, easement_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/easements/{easement_id}/amendments", headers=headers, params=params
        )

    def draft_amendment(self, easement_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/easements/{easement_id}/amendments", payload, headers
        )

    # ---------------- Monitoring visits ----------------

    def schedule_monitoring_visit(self, payload: dict, headers: dict):
        return self._request("POST", "/monitoring-visits", payload, headers)

    def get_monitoring_visit(self, visit_id: str, headers: dict):
        return self._request("GET", f"/monitoring-visits/{visit_id}", headers=headers)

    def complete_monitoring_visit(self, visit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/monitoring-visits/{visit_id}/completion", payload, headers
        )

    def cancel_monitoring_visit(self, visit_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/monitoring-visits/{visit_id}/cancellation", payload, headers
        )

    def list_visit_violations(
        self, visit_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/monitoring-visits/{visit_id}/violations",
            headers=headers,
            params=params,
        )

    # ---------------- Violations ----------------

    def open_violation(self, payload: dict, headers: dict):
        return self._request("POST", "/violations", payload, headers)

    def get_violation(self, violation_id: str, headers: dict):
        return self._request("GET", f"/violations/{violation_id}", headers=headers)

    def accept_cure_plan(self, violation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/violations/{violation_id}/cure-plan", payload, headers
        )

    def verify_cure(self, violation_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/violations/{violation_id}/cure-verification", payload, headers
        )

    # ---------------- Amendments ----------------

    def get_amendment(self, amendment_id: str, headers: dict):
        return self._request("GET", f"/amendments/{amendment_id}", headers=headers)

    def submit_amendment(self, amendment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/amendments/{amendment_id}/submission",
            payload if payload is not None else {},
            headers,
        )

    def decide_amendment(self, amendment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/amendments/{amendment_id}/decision", payload, headers
        )

    def reinstate_amendment(self, amendment_id: str, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            f"/amendments/{amendment_id}/reinstatement",
            payload if payload is not None else {},
            headers,
        )

    def rescind_amendment(self, amendment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/amendments/{amendment_id}/rescission", payload, headers
        )

    # ---------------- Clock and sweep ----------------

    def set_clock(self, current_utc: str, headers: Optional[dict] = None):
        return self._request(
            "POST",
            "/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )

    def run_stewardship_sweep(self, headers: dict, payload: Optional[dict] = None):
        return self._request(
            "POST",
            "/stewardship-sweeps",
            payload if payload is not None else {},
            headers,
        )

    # ---------------- Raw escape hatches ----------------

    def raw_post(self, path: str, payload: Optional[dict], headers: Optional[dict]):
        return self._request("POST", path, payload, headers)

    def raw_get(self, path: str, headers: Optional[dict], params: Optional[dict] = None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_patch(self, path: str, payload: Optional[dict], headers: Optional[dict]):
        return self._request("PATCH", path, payload, headers)


api_client = ApiClient()
