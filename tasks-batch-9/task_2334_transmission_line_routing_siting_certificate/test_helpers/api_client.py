"""HTTP client with one method per endpoint in the PRD §4 endpoint table."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Transmission Siting API client. All paths are mounted under ``/siting``.

    The harness restarts the server before every test, which invalidates any
    socket left in the connection pool by the previous test.  Reusing one of
    those dead sockets surfaces as ``ConnectionResetError`` on a perfectly
    healthy request, so this client asks for a fresh connection every time.
    """

    def __init__(self, base_url=None):
        super().__init__(base_url)
        self.session.headers["Connection"] = "close"

    # ------------------------------------------------------------------
    # Administrative logical clock (PRD §2.6)
    # ------------------------------------------------------------------

    def set_clock(self, current_utc: str, headers: dict):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------

    def list_projects(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/projects", params or {}, headers)

    def get_project(self, project_id: str, headers: dict):
        return self._request("GET", f"/siting/projects/{project_id}", None, headers)

    def list_project_planning_studies(
        self, project_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/siting/projects/{project_id}/planning-studies", params or {}, headers
        )

    def list_project_routes(
        self, project_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/siting/projects/{project_id}/routes", params or {}, headers
        )

    def create_project(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/projects", payload, headers)

    def create_escrow_deposit(self, project_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/projects/{project_id}/escrow-deposits", payload, headers
        )

    # ------------------------------------------------------------------
    # Planning studies and alternatives
    # ------------------------------------------------------------------

    def list_planning_studies(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/planning-studies", params or {}, headers)

    def get_planning_study(self, study_id: str, headers: dict):
        return self._request("GET", f"/siting/planning-studies/{study_id}", None, headers)

    def list_study_alternatives(
        self, study_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/siting/planning-studies/{study_id}/alternatives", params or {}, headers
        )

    def create_planning_study(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/planning-studies", payload, headers)

    def certify_study_sufficiency(self, study_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/siting/planning-studies/{study_id}/sufficiency-certification",
            payload,
            headers,
        )

    def list_alternatives(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/alternatives", params or {}, headers)

    def get_alternative(self, alternative_id: str, headers: dict):
        return self._request("GET", f"/siting/alternatives/{alternative_id}", None, headers)

    def create_alternative(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/alternatives", payload, headers)

    def screen_alternative(self, alternative_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/alternatives/{alternative_id}/screening", payload, headers
        )

    # ------------------------------------------------------------------
    # Routes and segments
    # ------------------------------------------------------------------

    def list_routes(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/routes", params or {}, headers)

    def get_route(self, route_id: str, headers: dict):
        return self._request("GET", f"/siting/routes/{route_id}", None, headers)

    def list_route_segments_of_route(
        self, route_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET", f"/siting/routes/{route_id}/segments", params or {}, headers
        )

    def list_route_segments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/route-segments", params or {}, headers)

    def get_route_segment(self, segment_id: str, headers: dict):
        return self._request("GET", f"/siting/route-segments/{segment_id}", None, headers)

    def create_route(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/routes", payload, headers)

    def create_route_segment(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/route-segments", payload, headers)

    def record_federal_permit_action(self, segment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/siting/route-segments/{segment_id}/federal-permit-actions",
            payload,
            headers,
        )

    def run_constraint_mapping(self, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/routes/{route_id}/constraint-mapping", payload, headers
        )

    def publish_route(self, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/routes/{route_id}/publication", payload, headers
        )

    def record_open_house(self, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/routes/{route_id}/open-houses", payload, headers
        )

    def refine_route(self, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/routes/{route_id}/refinements", payload, headers
        )

    def nominate_route(self, route_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/routes/{route_id}/nomination", payload, headers
        )

    # ------------------------------------------------------------------
    # Public comments
    # ------------------------------------------------------------------

    def list_public_comments(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/public-comments", params or {}, headers)

    def get_public_comment(self, comment_id: str, headers: dict):
        return self._request("GET", f"/siting/public-comments/{comment_id}", None, headers)

    def create_public_comment(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/public-comments", payload, headers)

    def disposition_public_comment(self, comment_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/public-comments/{comment_id}/disposition", payload, headers
        )

    # ------------------------------------------------------------------
    # Applications and the docket
    # ------------------------------------------------------------------

    def list_applications(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/applications", params or {}, headers)

    def get_application(self, application_id: str, headers: dict):
        return self._request("GET", f"/siting/applications/{application_id}", None, headers)

    def list_application_hearing_sessions(
        self, application_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/siting/applications/{application_id}/hearing-sessions",
            params or {},
            headers,
        )

    def create_application(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/applications", payload, headers)

    def review_application_sufficiency(
        self, application_id: str, payload: dict, headers: dict
    ):
        return self._request(
            "POST",
            f"/siting/applications/{application_id}/sufficiency-review",
            payload,
            headers,
        )

    def amend_application(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/applications/{application_id}/amendments", payload, headers
        )

    def close_record(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/applications/{application_id}/record-closure", payload, headers
        )

    def record_decision(self, application_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/applications/{application_id}/decision", payload, headers
        )

    def list_hearing_sessions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/hearing-sessions", params or {}, headers)

    def get_hearing_session(self, session_id: str, headers: dict):
        return self._request("GET", f"/siting/hearing-sessions/{session_id}", None, headers)

    def create_hearing_session(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/hearing-sessions", payload, headers)

    def hold_hearing_session(self, session_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/hearing-sessions/{session_id}/holding", payload, headers
        )

    def list_interventions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/interventions", params or {}, headers)

    def get_intervention(self, intervention_id: str, headers: dict):
        return self._request("GET", f"/siting/interventions/{intervention_id}", None, headers)

    def create_intervention(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/interventions", payload, headers)

    def rule_on_intervention(self, intervention_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/interventions/{intervention_id}/ruling", payload, headers
        )

    # ------------------------------------------------------------------
    # Certificates and conditions
    # ------------------------------------------------------------------

    def list_certificates(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/certificates", params or {}, headers)

    def get_certificate(self, certificate_id: str, headers: dict):
        return self._request("GET", f"/siting/certificates/{certificate_id}", None, headers)

    def list_certificate_conditions_of_certificate(
        self, certificate_id: str, headers: dict, params: Optional[dict] = None
    ):
        return self._request(
            "GET",
            f"/siting/certificates/{certificate_id}/conditions",
            params or {},
            headers,
        )

    def list_certificate_conditions(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/certificate-conditions", params or {}, headers)

    def get_certificate_condition(self, condition_id: str, headers: dict):
        return self._request(
            "GET", f"/siting/certificate-conditions/{condition_id}", None, headers
        )

    def waive_certificate_condition(self, condition_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/certificate-conditions/{condition_id}/waiver", payload, headers
        )

    def close_out_certificate(self, certificate_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/certificates/{certificate_id}/closeout", payload, headers
        )

    # ------------------------------------------------------------------
    # Landowners and easement tracts
    # ------------------------------------------------------------------

    def list_landowners(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/landowners", params or {}, headers)

    def get_landowner(self, landowner_id: str, headers: dict):
        return self._request("GET", f"/siting/landowners/{landowner_id}", None, headers)

    def create_landowner(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/landowners", payload, headers)

    def list_easement_tracts(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/easement-tracts", params or {}, headers)

    def get_easement_tract(self, tract_id: str, headers: dict):
        return self._request("GET", f"/siting/easement-tracts/{tract_id}", None, headers)

    def create_easement_tract(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/easement-tracts", payload, headers)

    def create_offer(self, tract_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/easement-tracts/{tract_id}/offers", payload, headers
        )

    def respond_to_offer(self, tract_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/easement-tracts/{tract_id}/offer-response", payload, headers
        )

    def file_condemnation(self, tract_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/easement-tracts/{tract_id}/condemnation", payload, headers
        )

    def record_award(self, tract_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/easement-tracts/{tract_id}/award", payload, headers
        )

    def create_payment(self, tract_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/easement-tracts/{tract_id}/payments", payload, headers
        )

    def rescind_payment(self, tract_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/siting/easement-tracts/{tract_id}/payment-rescission",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Construction and compliance
    # ------------------------------------------------------------------

    def list_construction_activities(self, headers: dict, params: Optional[dict] = None):
        return self._request(
            "GET", "/siting/construction-activities", params or {}, headers
        )

    def get_construction_activity(self, activity_id: str, headers: dict):
        return self._request(
            "GET", f"/siting/construction-activities/{activity_id}", None, headers
        )

    def create_construction_activity(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/construction-activities", payload, headers)

    def start_activity(self, activity_id: str, payload: dict, headers: dict):
        return self._request(
            "POST", f"/siting/construction-activities/{activity_id}/start", payload, headers
        )

    def complete_activity(self, activity_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/siting/construction-activities/{activity_id}/completion",
            payload,
            headers,
        )

    def cancel_activity(self, activity_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/siting/construction-activities/{activity_id}/cancellation",
            payload,
            headers,
        )

    def list_nonconformances(self, headers: dict, params: Optional[dict] = None):
        return self._request("GET", "/siting/nonconformances", params or {}, headers)

    def get_nonconformance(self, nonconformance_id: str, headers: dict):
        return self._request(
            "GET", f"/siting/nonconformances/{nonconformance_id}", None, headers
        )

    def create_nonconformance(self, payload: dict, headers: dict):
        return self._request("POST", "/siting/nonconformances", payload, headers)

    def correct_nonconformance(self, nonconformance_id: str, payload: dict, headers: dict):
        return self._request(
            "POST",
            f"/siting/nonconformances/{nonconformance_id}/correction",
            payload,
            headers,
        )


#: Shared client instance for tests and fixtures.
api_client = ApiClient()
