"""API client: one method per endpoint defined in the PRD (§4).

Every method returns the raw ``requests.Response`` so tests can assert status
codes as well as bodies. ``headers`` is always explicit — the PRD requires
``X-User-ID`` and ``X-User-Role`` on every request except the public registry
verification read, which is reachable with no headers at all.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Certification programs (PRD §3.1)
    # ------------------------------------------------------------------

    def create_program(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def activate_program(self, program_id: str, payload: Optional[Dict[str, Any]] = None,
                         headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/programs/{program_id}/activate", payload, headers)

    def list_program_items(self, program_id: str, headers: Optional[Dict[str, str]] = None,
                           params: Optional[Dict] = None):
        return self._request("GET", f"/programs/{program_id}/items", headers=headers, params=params)

    def list_program_forms(self, program_id: str, headers: Optional[Dict[str, str]] = None,
                           params: Optional[Dict] = None):
        return self._request("GET", f"/programs/{program_id}/forms", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Items (PRD §3.2 – §3.4)
    # ------------------------------------------------------------------

    def create_item(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/items", payload, headers)

    def get_item(self, item_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/items/{item_id}", headers=headers)

    def list_items(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/items", headers=headers, params=params)

    def submit_item_for_review(self, item_id: str, payload: Optional[Dict[str, Any]] = None,
                               headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/items/{item_id}/submit-for-review", payload, headers)

    def review_item(self, item_id: str, payload: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/items/{item_id}/review", payload, headers)

    def ingest_response_batch(self, item_id: str, payload: Dict[str, Any],
                              headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/items/{item_id}/response-batches", payload, headers)

    def retire_item(self, item_id: str, payload: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/items/{item_id}/retire", payload, headers)

    # ------------------------------------------------------------------
    # Exam forms (PRD §3.5)
    # ------------------------------------------------------------------

    def create_form(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/forms", payload, headers)

    def get_form(self, form_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/forms/{form_id}", headers=headers)

    def list_forms(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/forms", headers=headers, params=params)

    def submit_panel_rating(self, form_id: str, payload: Dict[str, Any],
                            headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/forms/{form_id}/panel-ratings", payload, headers)

    def adopt_cut_score(self, form_id: str, payload: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/forms/{form_id}/adopt-cut-score", payload, headers)

    def publish_form(self, form_id: str, payload: Optional[Dict[str, Any]] = None,
                     headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/forms/{form_id}/publish", payload, headers)

    # ------------------------------------------------------------------
    # Candidates (PRD §3.6)
    # ------------------------------------------------------------------

    def create_candidate(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidates(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Eligibility applications (PRD §3.6)
    # ------------------------------------------------------------------

    def create_application(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def verify_application_dimension(self, application_id: str, payload: Dict[str, Any],
                                     headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/applications/{application_id}/verify", payload, headers)

    def decide_application_audit(self, application_id: str, payload: Dict[str, Any],
                                 headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/applications/{application_id}/audit-decision", payload, headers)

    # ------------------------------------------------------------------
    # Exam sessions (PRD §3.7)
    # ------------------------------------------------------------------

    def create_exam_session(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/exam-sessions", payload, headers)

    def get_exam_session(self, session_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/exam-sessions/{session_id}", headers=headers)

    def list_exam_sessions(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/exam-sessions", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Exam registrations (PRD §3.7 – §3.9)
    # ------------------------------------------------------------------

    def create_exam_registration(self, payload: Dict[str, Any],
                                 headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/exam-registrations", payload, headers)

    def get_exam_registration(self, registration_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/exam-registrations/{registration_id}", headers=headers)

    def list_exam_registrations(self, headers: Optional[Dict[str, str]] = None,
                                params: Optional[Dict] = None):
        return self._request("GET", "/exam-registrations", headers=headers, params=params)

    def schedule_seat(self, registration_id: str, payload: Dict[str, Any],
                      headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/exam-registrations/{registration_id}/schedule", payload, headers)

    def cancel_seat_schedule(self, registration_id: str, payload: Optional[Dict[str, Any]] = None,
                             headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/exam-registrations/{registration_id}/cancel-schedule",
                             payload, headers)

    def check_in(self, registration_id: str, payload: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/exam-registrations/{registration_id}/check-in", payload, headers)

    def submit_responses(self, registration_id: str, payload: Dict[str, Any],
                         headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/exam-registrations/{registration_id}/submit-responses",
                             payload, headers)

    def report_score(self, registration_id: str, payload: Optional[Dict[str, Any]] = None,
                     headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/exam-registrations/{registration_id}/report-score",
                             payload, headers)

    def raise_security_incident(self, registration_id: str, payload: Dict[str, Any],
                                headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/exam-registrations/{registration_id}/security-incidents",
                             payload, headers)

    def list_registration_security_incidents(self, registration_id: str,
                                             headers: Optional[Dict[str, str]] = None,
                                             params: Optional[Dict] = None):
        return self._request("GET", f"/exam-registrations/{registration_id}/security-incidents",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Security incidents (PRD §3.9)
    # ------------------------------------------------------------------

    def get_security_incident(self, incident_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/security-incidents/{incident_id}", headers=headers)

    def adjudicate_security_incident(self, incident_id: str, payload: Dict[str, Any],
                                     headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/security-incidents/{incident_id}/adjudicate", payload, headers)

    # ------------------------------------------------------------------
    # Certificants and the public registry (PRD §3.10)
    # ------------------------------------------------------------------

    def get_certificant(self, certificant_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/certificants/{certificant_id}", headers=headers)

    def list_certificants(self, headers: Optional[Dict[str, str]] = None, params: Optional[Dict] = None):
        return self._request("GET", "/certificants", headers=headers, params=params)

    def verify_registry(self, params: Optional[Dict] = None,
                        headers: Optional[Dict[str, str]] = None):
        """Public credential verification. Requires no headers whatsoever."""
        return self._request("GET", "/registry/verify", headers=headers, params=params)

    def list_certificant_recertification_cycles(self, certificant_id: str,
                                                headers: Optional[Dict[str, str]] = None,
                                                params: Optional[Dict] = None):
        return self._request("GET", f"/certificants/{certificant_id}/recertification-cycles",
                             headers=headers, params=params)

    def list_certificant_disciplinary_cases(self, certificant_id: str,
                                            headers: Optional[Dict[str, str]] = None,
                                            params: Optional[Dict] = None):
        return self._request("GET", f"/certificants/{certificant_id}/disciplinary-cases",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Recertification cycles (PRD §3.11)
    # ------------------------------------------------------------------

    def get_recertification_cycle(self, cycle_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/recertification-cycles/{cycle_id}", headers=headers)

    def list_recertification_cycles(self, headers: Optional[Dict[str, str]] = None,
                                    params: Optional[Dict] = None):
        return self._request("GET", "/recertification-cycles", headers=headers, params=params)

    def close_cycle(self, cycle_id: str, payload: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/recertification-cycles/{cycle_id}/close", payload, headers)

    def elect_reexam(self, cycle_id: str, payload: Optional[Dict[str, Any]] = None,
                     headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/recertification-cycles/{cycle_id}/elect-reexam",
                             payload, headers)

    def reinstate_cycle(self, cycle_id: str, payload: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/recertification-cycles/{cycle_id}/reinstate", payload, headers)

    def claim_ceu_activity(self, cycle_id: str, payload: Dict[str, Any],
                           headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/recertification-cycles/{cycle_id}/ceu-activities",
                             payload, headers)

    def list_cycle_ceu_activities(self, cycle_id: str, headers: Optional[Dict[str, str]] = None,
                                  params: Optional[Dict] = None):
        return self._request("GET", f"/recertification-cycles/{cycle_id}/ceu-activities",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Continuing-education activities (PRD §3.11)
    # ------------------------------------------------------------------

    def get_ceu_activity(self, activity_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/ceu-activities/{activity_id}", headers=headers)

    def review_ceu_activity(self, activity_id: str, payload: Dict[str, Any],
                            headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/ceu-activities/{activity_id}/review", payload, headers)

    def audit_verify_ceu_activity(self, activity_id: str, payload: Dict[str, Any],
                                  headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/ceu-activities/{activity_id}/audit-verify", payload, headers)

    # ------------------------------------------------------------------
    # Disciplinary cases (PRD §3.12)
    # ------------------------------------------------------------------

    def open_disciplinary_case(self, payload: Dict[str, Any],
                               headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/disciplinary-cases", payload, headers)

    def get_disciplinary_case(self, case_id: str, headers: Optional[Dict[str, str]] = None):
        return self._request("GET", f"/disciplinary-cases/{case_id}", headers=headers)

    def list_disciplinary_cases(self, headers: Optional[Dict[str, str]] = None,
                                params: Optional[Dict] = None):
        return self._request("GET", "/disciplinary-cases", headers=headers, params=params)

    def request_case_response(self, case_id: str, payload: Optional[Dict[str, Any]] = None,
                              headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/disciplinary-cases/{case_id}/request-response",
                             payload, headers)

    def respond_to_case(self, case_id: str, payload: Dict[str, Any],
                        headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/disciplinary-cases/{case_id}/respond", payload, headers)

    def decide_case(self, case_id: str, payload: Dict[str, Any],
                    headers: Optional[Dict[str, str]] = None):
        return self._request("POST", f"/disciplinary-cases/{case_id}/decide", payload, headers)

    # ------------------------------------------------------------------
    # Logical clock and the maintenance run (PRD §2.4, §3.13)
    # ------------------------------------------------------------------

    def set_clock(self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_maintenance(self, payload: Optional[Dict[str, Any]] = None,
                        headers: Optional[Dict[str, str]] = None):
        return self._request("POST", "/recertification-runs", payload, headers)


api_client = ApiClient()
