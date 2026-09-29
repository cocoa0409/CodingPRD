"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ #
    # Facilities
    # ------------------------------------------------------------------ #
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    # ------------------------------------------------------------------ #
    # Clinicians
    # ------------------------------------------------------------------ #
    def create_clinician(self, payload, headers):
        return self._request("POST", "/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"/clinicians/{clinician_id}", headers=headers)

    def list_clinicians(self, headers, params=None):
        return self._request("GET", "/clinicians", headers=headers, params=params)

    def deactivate_clinician(self, clinician_id, headers, payload=None):
        return self._request(
            "POST", f"/clinicians/{clinician_id}/deactivate", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Patients
    # ------------------------------------------------------------------ #
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    # ------------------------------------------------------------------ #
    # Preadmission screenings
    # ------------------------------------------------------------------ #
    def create_screening(self, payload, headers):
        return self._request("POST", "/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/screenings", headers=headers, params=params)

    def patch_screening(self, screening_id, payload, headers):
        return self._request("PATCH", f"/screenings/{screening_id}", payload, headers)

    def submit_screening(self, screening_id, headers, payload=None):
        return self._request(
            "POST", f"/screenings/{screening_id}/submit", payload, headers
        )

    def review_screening(self, screening_id, payload, headers):
        return self._request(
            "POST", f"/screenings/{screening_id}/review", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Admissions
    # ------------------------------------------------------------------ #
    def create_admission(self, payload, headers):
        return self._request("POST", "/admissions", payload, headers)

    def get_admission(self, admission_id, headers):
        return self._request("GET", f"/admissions/{admission_id}", headers=headers)

    def list_admissions(self, headers, params=None):
        return self._request("GET", "/admissions", headers=headers, params=params)

    def admit_admission(self, admission_id, payload, headers):
        return self._request(
            "POST", f"/admissions/{admission_id}/admit", payload, headers
        )

    def deny_admission(self, admission_id, payload, headers):
        return self._request(
            "POST", f"/admissions/{admission_id}/deny", payload, headers
        )

    def discharge_admission(self, admission_id, payload, headers):
        return self._request(
            "POST", f"/admissions/{admission_id}/discharge", payload, headers
        )

    def rescind_interruption(self, admission_id, payload, headers):
        return self._request(
            "POST", f"/admissions/{admission_id}/rescind-interruption", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Plans of care
    # ------------------------------------------------------------------ #
    def create_plan_of_care(self, payload, headers):
        return self._request("POST", "/plans-of-care", payload, headers)

    def get_plan_of_care(self, plan_id, headers):
        return self._request("GET", f"/plans-of-care/{plan_id}", headers=headers)

    def list_plans_of_care(self, headers, params=None):
        return self._request("GET", "/plans-of-care", headers=headers, params=params)

    # ------------------------------------------------------------------ #
    # Therapy weeks
    # ------------------------------------------------------------------ #
    def create_therapy_week(self, payload, headers):
        return self._request("POST", "/therapy-weeks", payload, headers)

    def get_therapy_week(self, week_id, headers):
        return self._request("GET", f"/therapy-weeks/{week_id}", headers=headers)

    def list_therapy_weeks(self, headers, params=None):
        return self._request("GET", "/therapy-weeks", headers=headers, params=params)

    def evaluate_therapy_week(self, week_id, headers, payload=None):
        return self._request(
            "POST", f"/therapy-weeks/{week_id}/evaluate", payload, headers
        )

    def grant_therapy_week_exception(self, week_id, payload, headers):
        return self._request(
            "POST", f"/therapy-weeks/{week_id}/exception", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Therapy sessions
    # ------------------------------------------------------------------ #
    def create_therapy_session(self, payload, headers):
        return self._request("POST", "/therapy-sessions", payload, headers)

    def get_therapy_session(self, session_id, headers):
        return self._request("GET", f"/therapy-sessions/{session_id}", headers=headers)

    def list_therapy_sessions(self, headers, params=None):
        return self._request("GET", "/therapy-sessions", headers=headers, params=params)

    def deliver_therapy_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/therapy-sessions/{session_id}/deliver", payload, headers
        )

    def void_therapy_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/therapy-sessions/{session_id}/void", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Team conferences
    # ------------------------------------------------------------------ #
    def create_team_conference(self, payload, headers):
        return self._request("POST", "/team-conferences", payload, headers)

    def get_team_conference(self, conference_id, headers):
        return self._request(
            "GET", f"/team-conferences/{conference_id}", headers=headers
        )

    def list_team_conferences(self, headers, params=None):
        return self._request("GET", "/team-conferences", headers=headers, params=params)

    # ------------------------------------------------------------------ #
    # Patient assessment instruments
    # ------------------------------------------------------------------ #
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def complete_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/assessments/{assessment_id}/complete", payload, headers
        )

    def transmit_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"/assessments/{assessment_id}/transmit", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Compliance reviews
    # ------------------------------------------------------------------ #
    def create_compliance_review(self, payload, headers):
        return self._request("POST", "/compliance-reviews", payload, headers)

    def get_compliance_review(self, review_id, headers):
        return self._request(
            "GET", f"/compliance-reviews/{review_id}", headers=headers
        )

    def list_compliance_reviews(self, headers, params=None):
        return self._request(
            "GET", "/compliance-reviews", headers=headers, params=params
        )

    def compute_compliance_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/compliance-reviews/{review_id}/compute", payload, headers
        )

    def certify_compliance_review(self, review_id, headers, payload=None):
        return self._request(
            "POST", f"/compliance-reviews/{review_id}/certify", payload, headers
        )

    # ------------------------------------------------------------------ #
    # QRP assessments
    # ------------------------------------------------------------------ #
    def create_qrp_assessment(self, payload, headers):
        return self._request("POST", "/qrp-assessments", payload, headers)

    def get_qrp_assessment(self, qrp_id, headers):
        return self._request("GET", f"/qrp-assessments/{qrp_id}", headers=headers)

    def list_qrp_assessments(self, headers, params=None):
        return self._request("GET", "/qrp-assessments", headers=headers, params=params)

    def finalize_qrp_assessment(self, qrp_id, headers, payload=None):
        return self._request(
            "POST", f"/qrp-assessments/{qrp_id}/finalize", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Logical clock
    # ------------------------------------------------------------------ #
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
