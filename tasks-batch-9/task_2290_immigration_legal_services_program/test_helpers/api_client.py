"""Typed API client for the Immigration Legal Services Program contract.

One method per endpoint declared in PRD section 4. All collections mount at the
server root with no version prefix. Every method takes an explicit ``headers``
mapping so the caller controls which identity performs the call -- ownership and
segregation-of-duties rules make the acting identity load bearing, so it is
never defaulted here.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint-per-method wrapper over the shared generic HTTP client."""

    # ------------------------------------------------------------------
    # GenericApiClient exposes get/post/put/delete but no PATCH helper.
    # ------------------------------------------------------------------
    def patch(
        self,
        path: str,
        json: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ):
        return self._request("PATCH", path, json, headers)

    # ==================================================================
    # Logical clock
    # ==================================================================
    def set_clock(self, to_iso8601: str, headers: Optional[Dict[str, str]] = None):
        """POST /_clock/set_current_utc -- ProgramDirector only."""
        return self.post(
            "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ==================================================================
    # Clients
    # ==================================================================
    def create_client(self, payload: Dict[str, Any], headers=None):
        """POST /clients"""
        return self.post("/clients", payload, headers=headers)

    def list_clients(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /clients"""
        return self.get("/clients", headers=headers, params=params)

    def get_client(self, client_id: str, headers=None):
        """GET /clients/{client_id}"""
        return self.get("/clients/{0}".format(client_id), headers=headers)

    def update_client(self, client_id: str, payload: Dict[str, Any], headers=None):
        """PATCH /clients/{client_id}"""
        return self.patch("/clients/{0}".format(client_id), payload, headers=headers)

    # ==================================================================
    # Program capacity cycles
    # ==================================================================
    def create_capacity_cycle(self, payload: Dict[str, Any], headers=None):
        """POST /capacity-cycles"""
        return self.post("/capacity-cycles", payload, headers=headers)

    def list_capacity_cycles(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /capacity-cycles"""
        return self.get("/capacity-cycles", headers=headers, params=params)

    def get_capacity_cycle(self, cycle_id: str, headers=None):
        """GET /capacity-cycles/{cycle_id}"""
        return self.get("/capacity-cycles/{0}".format(cycle_id), headers=headers)

    def posture_override(self, cycle_id: str, payload: Dict[str, Any], headers=None):
        """POST /capacity-cycles/{cycle_id}/posture-override"""
        return self.post(
            "/capacity-cycles/{0}/posture-override".format(cycle_id),
            payload,
            headers=headers,
        )

    def checkpoint_cycle(
        self, cycle_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        """POST /capacity-cycles/{cycle_id}/checkpoint"""
        return self.post(
            "/capacity-cycles/{0}/checkpoint".format(cycle_id),
            payload if payload is not None else {},
            headers=headers,
        )

    # ==================================================================
    # Detention facilities
    # ==================================================================
    def create_facility(self, payload: Dict[str, Any], headers=None):
        """POST /detention-facilities"""
        return self.post("/detention-facilities", payload, headers=headers)

    def list_facilities(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /detention-facilities"""
        return self.get("/detention-facilities", headers=headers, params=params)

    def get_facility(self, facility_id: str, headers=None):
        """GET /detention-facilities/{facility_id}"""
        return self.get("/detention-facilities/{0}".format(facility_id), headers=headers)

    # ==================================================================
    # Organization recognitions
    # ==================================================================
    def create_recognition(self, payload: Dict[str, Any], headers=None):
        """POST /organization-recognitions"""
        return self.post("/organization-recognitions", payload, headers=headers)

    def list_recognitions(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /organization-recognitions"""
        return self.get("/organization-recognitions", headers=headers, params=params)

    def get_recognition(self, recognition_id: str, headers=None):
        """GET /organization-recognitions/{recognition_id}"""
        return self.get(
            "/organization-recognitions/{0}".format(recognition_id), headers=headers
        )

    def transition_recognition(
        self, recognition_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /organization-recognitions/{recognition_id}/transition"""
        return self.post(
            "/organization-recognitions/{0}/transition".format(recognition_id),
            payload,
            headers=headers,
        )

    # ==================================================================
    # Representatives
    # ==================================================================
    def create_representative(self, payload: Dict[str, Any], headers=None):
        """POST /representatives"""
        return self.post("/representatives", payload, headers=headers)

    def list_representatives(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /representatives"""
        return self.get("/representatives", headers=headers, params=params)

    def get_representative(self, representative_id: str, headers=None):
        """GET /representatives/{representative_id}"""
        return self.get("/representatives/{0}".format(representative_id), headers=headers)

    def update_representative(
        self, representative_id: str, payload: Dict[str, Any], headers=None
    ):
        """PATCH /representatives/{representative_id}"""
        return self.patch(
            "/representatives/{0}".format(representative_id), payload, headers=headers
        )

    # ==================================================================
    # Accreditations
    # ==================================================================
    def create_accreditation(self, payload: Dict[str, Any], headers=None):
        """POST /accreditations"""
        return self.post("/accreditations", payload, headers=headers)

    def list_accreditations(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /accreditations"""
        return self.get("/accreditations", headers=headers, params=params)

    def get_accreditation(self, accreditation_id: str, headers=None):
        """GET /accreditations/{accreditation_id}"""
        return self.get("/accreditations/{0}".format(accreditation_id), headers=headers)

    def transition_accreditation(
        self, accreditation_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /accreditations/{accreditation_id}/transition"""
        return self.post(
            "/accreditations/{0}/transition".format(accreditation_id),
            payload,
            headers=headers,
        )

    def renew_accreditation(
        self, accreditation_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /accreditations/{accreditation_id}/renew"""
        return self.post(
            "/accreditations/{0}/renew".format(accreditation_id),
            payload,
            headers=headers,
        )

    # ==================================================================
    # Intake screenings
    # ==================================================================
    def create_intake(self, payload: Dict[str, Any], headers=None):
        """POST /intake-screenings"""
        return self.post("/intake-screenings", payload, headers=headers)

    def list_intakes(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /intake-screenings"""
        return self.get("/intake-screenings", headers=headers, params=params)

    def get_intake(self, intake_id: str, headers=None):
        """GET /intake-screenings/{intake_id}"""
        return self.get("/intake-screenings/{0}".format(intake_id), headers=headers)

    def screen_intake(
        self, intake_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        """POST /intake-screenings/{intake_id}/screen"""
        return self.post(
            "/intake-screenings/{0}/screen".format(intake_id),
            payload if payload is not None else {},
            headers=headers,
        )

    def decide_intake(self, intake_id: str, payload: Dict[str, Any], headers=None):
        """POST /intake-screenings/{intake_id}/decide"""
        return self.post(
            "/intake-screenings/{0}/decide".format(intake_id), payload, headers=headers
        )

    def withdraw_intake(
        self, intake_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        """POST /intake-screenings/{intake_id}/withdraw"""
        return self.post(
            "/intake-screenings/{0}/withdraw".format(intake_id),
            payload if payload is not None else {},
            headers=headers,
        )

    # ==================================================================
    # Case matters
    # ==================================================================
    def list_matters(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /case-matters -- the only discovery channel for a minted matter."""
        return self.get("/case-matters", headers=headers, params=params)

    def get_matter(self, matter_id: str, headers=None):
        """GET /case-matters/{matter_id}"""
        return self.get("/case-matters/{0}".format(matter_id), headers=headers)

    def set_facility(self, matter_id: str, payload: Dict[str, Any], headers=None):
        """POST /case-matters/{matter_id}/set-facility"""
        return self.post(
            "/case-matters/{0}/set-facility".format(matter_id), payload, headers=headers
        )

    def advance_filing(self, matter_id: str, payload: Dict[str, Any], headers=None):
        """POST /case-matters/{matter_id}/advance-filing"""
        return self.post(
            "/case-matters/{0}/advance-filing".format(matter_id),
            payload,
            headers=headers,
        )

    def withdraw_representation(
        self, matter_id: str, payload: Optional[Dict[str, Any]] = None, headers=None
    ):
        """POST /case-matters/{matter_id}/withdraw-representation"""
        return self.post(
            "/case-matters/{0}/withdraw-representation".format(matter_id),
            payload if payload is not None else {},
            headers=headers,
        )

    # ==================================================================
    # Case assignments
    # ==================================================================
    def create_assignment(self, payload: Dict[str, Any], headers=None):
        """POST /case-assignments -- requires expected_matter_version."""
        return self.post("/case-assignments", payload, headers=headers)

    def list_assignments(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /case-assignments -- only channel for an auto-selected supervisor row."""
        return self.get("/case-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id: str, headers=None):
        """GET /case-assignments/{assignment_id}"""
        return self.get("/case-assignments/{0}".format(assignment_id), headers=headers)

    def transition_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /case-assignments/{assignment_id}/transition"""
        return self.post(
            "/case-assignments/{0}/transition".format(assignment_id),
            payload,
            headers=headers,
        )

    def relink_supervision(
        self, assignment_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /case-assignments/{assignment_id}/relink-supervision"""
        return self.post(
            "/case-assignments/{0}/relink-supervision".format(assignment_id),
            payload,
            headers=headers,
        )

    def log_hours(self, assignment_id: str, payload: Dict[str, Any], headers=None):
        """POST /case-assignments/{assignment_id}/log-hours"""
        return self.post(
            "/case-assignments/{0}/log-hours".format(assignment_id),
            payload,
            headers=headers,
        )

    # ==================================================================
    # Evidence items
    # ==================================================================
    def create_evidence(self, payload: Dict[str, Any], headers=None):
        """POST /evidence-items"""
        return self.post("/evidence-items", payload, headers=headers)

    def list_evidence(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /evidence-items -- there is no single-item read endpoint."""
        return self.get("/evidence-items", headers=headers, params=params)

    def transition_evidence(self, item_id: str, payload: Dict[str, Any], headers=None):
        """POST /evidence-items/{item_id}/transition"""
        return self.post(
            "/evidence-items/{0}/transition".format(item_id), payload, headers=headers
        )

    # ==================================================================
    # Declarations
    # ==================================================================
    def create_declaration(self, payload: Dict[str, Any], headers=None):
        """POST /declarations"""
        return self.post("/declarations", payload, headers=headers)

    def list_declarations(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /declarations -- there is no single-declaration read endpoint."""
        return self.get("/declarations", headers=headers, params=params)

    def transition_declaration(
        self, declaration_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /declarations/{declaration_id}/transition"""
        return self.post(
            "/declarations/{0}/transition".format(declaration_id),
            payload,
            headers=headers,
        )

    # ==================================================================
    # Interpretation sessions
    # ==================================================================
    def create_session(self, payload: Dict[str, Any], headers=None):
        """POST /interpretation-sessions"""
        return self.post("/interpretation-sessions", payload, headers=headers)

    def list_sessions(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /interpretation-sessions"""
        return self.get("/interpretation-sessions", headers=headers, params=params)

    def transition_session(self, session_id: str, payload: Dict[str, Any], headers=None):
        """POST /interpretation-sessions/{session_id}/transition"""
        return self.post(
            "/interpretation-sessions/{0}/transition".format(session_id),
            payload,
            headers=headers,
        )

    # ==================================================================
    # Calendar events
    # ==================================================================
    def create_event(self, payload: Dict[str, Any], headers=None):
        """POST /calendar-events"""
        return self.post("/calendar-events", payload, headers=headers)

    def list_events(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /calendar-events -- only channel for a continuance successor."""
        return self.get("/calendar-events", headers=headers, params=params)

    def reschedule_event(self, event_id: str, payload: Dict[str, Any], headers=None):
        """POST /calendar-events/{event_id}/reschedule"""
        return self.post(
            "/calendar-events/{0}/reschedule".format(event_id), payload, headers=headers
        )

    def transition_event(self, event_id: str, payload: Dict[str, Any], headers=None):
        """POST /calendar-events/{event_id}/transition"""
        return self.post(
            "/calendar-events/{0}/transition".format(event_id), payload, headers=headers
        )

    # ==================================================================
    # Informed decisions
    # ==================================================================
    def create_informed_decision(self, payload: Dict[str, Any], headers=None):
        """POST /informed-decisions -- requires expected_matter_version."""
        return self.post("/informed-decisions", payload, headers=headers)

    def list_informed_decisions(
        self, params: Optional[Dict[str, Any]] = None, headers=None
    ):
        """GET /informed-decisions"""
        return self.get("/informed-decisions", headers=headers, params=params)

    def transition_informed_decision(
        self, decision_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /informed-decisions/{decision_id}/transition"""
        return self.post(
            "/informed-decisions/{0}/transition".format(decision_id),
            payload,
            headers=headers,
        )

    # ==================================================================
    # Grant reports
    # ==================================================================
    def create_grant_report(self, payload: Dict[str, Any], headers=None):
        """POST /grant-reports"""
        return self.post("/grant-reports", payload, headers=headers)

    def list_grant_reports(self, params: Optional[Dict[str, Any]] = None, headers=None):
        """GET /grant-reports"""
        return self.get("/grant-reports", headers=headers, params=params)

    def get_grant_report(self, report_id: str, headers=None):
        """GET /grant-reports/{report_id}"""
        return self.get("/grant-reports/{0}".format(report_id), headers=headers)

    def transition_grant_report(
        self, report_id: str, payload: Dict[str, Any], headers=None
    ):
        """POST /grant-reports/{report_id}/transition"""
        return self.post(
            "/grant-reports/{0}/transition".format(report_id), payload, headers=headers
        )
