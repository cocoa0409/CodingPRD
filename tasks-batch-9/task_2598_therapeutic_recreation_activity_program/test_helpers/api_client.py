"""One method per endpoint of the Therapeutic Recreation Activity Program API."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin transport wrapper; every method returns the raw response."""

    # ------------------------------------------------------------------
    # Census and clinical record
    # ------------------------------------------------------------------
    def create_resident(self, payload, headers):
        return self._request("POST", "/recreation/residents", payload, headers)

    def update_resident(self, resident_id, payload, headers):
        return self._request(
            "PATCH", f"/recreation/residents/{resident_id}", payload, headers
        )

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/recreation/residents/{resident_id}", None, headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/recreation/residents", params, headers)

    def create_assessment(self, resident_id, payload, headers):
        return self._request(
            "POST", f"/recreation/residents/{resident_id}/assessments", payload, headers
        )

    def list_resident_assessments(self, resident_id, headers, params=None):
        return self._request(
            "GET", f"/recreation/residents/{resident_id}/assessments", params, headers
        )

    def get_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/recreation/assessments/{assessment_id}", None, headers
        )

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/recreation/assessments", params, headers)

    # ------------------------------------------------------------------
    # Catalogue, rooms and fleet
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/recreation/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/recreation/programs/{program_id}", None, headers)

    def create_room(self, payload, headers):
        return self._request("POST", "/recreation/rooms", payload, headers)

    def create_vehicle(self, payload, headers):
        return self._request("POST", "/recreation/vehicles", payload, headers)

    def update_vehicle(self, vehicle_id, payload, headers):
        return self._request(
            "PATCH", f"/recreation/vehicles/{vehicle_id}", payload, headers
        )

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/recreation/vehicles/{vehicle_id}", None, headers)

    # ------------------------------------------------------------------
    # Activity plans
    # ------------------------------------------------------------------
    def create_activity_plan(self, payload, headers):
        return self._request("POST", "/recreation/activity-plans", payload, headers)

    def transition_activity_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"/recreation/activity-plans/{plan_id}/transition", payload, headers
        )

    def get_activity_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/recreation/activity-plans/{plan_id}", None, headers
        )

    def list_activity_plans(self, headers, params=None):
        return self._request("GET", "/recreation/activity-plans", params, headers)

    # ------------------------------------------------------------------
    # Calendar, enrollment and documentation
    # ------------------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/recreation/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/recreation/sessions/{session_id}", None, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/recreation/sessions", params, headers)

    def session_status(self, session_id, payload, headers):
        return self._request(
            "POST", f"/recreation/sessions/{session_id}/status", payload, headers
        )

    def create_enrollment(self, session_id, payload, headers):
        return self._request(
            "POST", f"/recreation/sessions/{session_id}/enrollments", payload, headers
        )

    def list_session_participation(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/recreation/sessions/{session_id}/participation", params, headers
        )

    def document_participation(self, record_id, payload, headers):
        return self._request(
            "PATCH", f"/recreation/participation/{record_id}", payload, headers
        )

    def get_participation(self, record_id, headers):
        return self._request(
            "GET", f"/recreation/participation/{record_id}", None, headers
        )

    def list_participation(self, headers, params=None):
        return self._request("GET", "/recreation/participation", params, headers)

    # ------------------------------------------------------------------
    # Volunteers
    # ------------------------------------------------------------------
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/recreation/volunteers", payload, headers)

    def volunteer_screening(self, volunteer_id, payload, headers):
        return self._request(
            "POST", f"/recreation/volunteers/{volunteer_id}/screening", payload, headers
        )

    def get_volunteer(self, volunteer_id, headers):
        return self._request(
            "GET", f"/recreation/volunteers/{volunteer_id}", None, headers
        )

    def create_volunteer_assignment(self, payload, headers):
        return self._request(
            "POST", "/recreation/volunteer-assignments", payload, headers
        )

    def update_volunteer_assignment(self, assignment_id, payload, headers):
        return self._request(
            "PATCH", f"/recreation/volunteer-assignments/{assignment_id}", payload, headers
        )

    def get_volunteer_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/recreation/volunteer-assignments/{assignment_id}", None, headers
        )

    def list_volunteer_assignments(self, headers, params=None):
        return self._request(
            "GET", "/recreation/volunteer-assignments", params, headers
        )

    # ------------------------------------------------------------------
    # Outings, transport and consent
    # ------------------------------------------------------------------
    def create_outing(self, payload, headers):
        return self._request("POST", "/recreation/outings", payload, headers)

    def get_outing(self, outing_id, headers):
        return self._request("GET", f"/recreation/outings/{outing_id}", None, headers)

    def list_outings(self, headers, params=None):
        return self._request("GET", "/recreation/outings", params, headers)

    def book_transport(self, outing_id, payload, headers):
        return self._request(
            "POST", f"/recreation/outings/{outing_id}/transport-booking", payload, headers
        )

    def outing_logistics(self, outing_id, payload, headers):
        return self._request(
            "POST", f"/recreation/outings/{outing_id}/logistics", payload, headers
        )

    def create_outing_consent(self, outing_id, payload, headers):
        return self._request(
            "POST", f"/recreation/outings/{outing_id}/consents", payload, headers
        )

    def decide_outing_consent(self, outing_id, consent_id, payload, headers):
        return self._request(
            "POST",
            f"/recreation/outings/{outing_id}/consents/{consent_id}/decision",
            payload,
            headers,
        )

    def list_outing_roster(self, outing_id, headers, params=None):
        return self._request(
            "GET", f"/recreation/outings/{outing_id}/consents", params, headers
        )

    def get_outing_consent(self, consent_id, headers):
        return self._request(
            "GET", f"/recreation/outing-consents/{consent_id}", None, headers
        )

    def list_outing_consents(self, headers, params=None):
        return self._request("GET", "/recreation/outing-consents", params, headers)

    # ------------------------------------------------------------------
    # Council requests
    # ------------------------------------------------------------------
    def create_council_request(self, payload, headers):
        return self._request("POST", "/recreation/council-requests", payload, headers)

    def review_council_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/recreation/council-requests/{request_id}/review", payload, headers
        )

    def get_council_request(self, request_id, headers):
        return self._request(
            "GET", f"/recreation/council-requests/{request_id}", None, headers
        )

    def list_council_requests(self, headers, params=None):
        return self._request("GET", "/recreation/council-requests", params, headers)

    # ------------------------------------------------------------------
    # Survey packets
    # ------------------------------------------------------------------
    def create_survey_packet(self, payload, headers):
        return self._request("POST", "/recreation/survey-packets", payload, headers)

    def compile_survey_packet(self, packet_id, payload, headers):
        return self._request(
            "POST", f"/recreation/survey-packets/{packet_id}/compile", payload, headers
        )

    def attest_survey_packet(self, packet_id, payload, headers):
        return self._request(
            "POST", f"/recreation/survey-packets/{packet_id}/attestation", payload, headers
        )

    def get_survey_packet(self, packet_id, headers):
        return self._request(
            "GET", f"/recreation/survey-packets/{packet_id}", None, headers
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, current_utc, headers):
        return self._request(
            "POST",
            "/recreation/_clock/set_current_utc",
            {"current_utc": current_utc},
            headers,
        )


api_client = ApiClient()
