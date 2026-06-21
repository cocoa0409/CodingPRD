"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the inherited _request() does the HTTP plumbing.
GET methods pass filters/pagination via params; POST methods pass a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Applicants ───────────────────────────────────
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    # ─── Applications ─────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def get_application_summary(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}/summary", headers=headers)

    def submit_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/submit", payload, headers)

    def begin_verification(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/begin-verification", payload or {}, headers)

    def clear_hold(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/clear-hold", payload or {}, headers)

    def adjudicate(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/adjudicate", payload, headers)

    def issue_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/issue", payload or {}, headers)

    def withdraw_application(self, application_id, headers, payload=None):
        return self._request("POST", f"/applications/{application_id}/withdraw", payload or {}, headers)

    def decide_name_change(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/name-change/decide", payload, headers)

    def list_status_events(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/status-events", headers=headers, params=params)

    # ─── Supporting documents ─────────────────────────
    def create_document(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/documents", payload, headers)

    def list_documents(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/documents", headers=headers, params=params)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/documents/{document_id}", headers=headers)

    def verify_document(self, document_id, payload, headers):
        return self._request("POST", f"/documents/{document_id}/verify", payload, headers)

    # ─── Photos ───────────────────────────────────────
    def create_photo(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/photos", payload, headers)

    def list_photos(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/photos", headers=headers, params=params)

    def revalidate_photo(self, photo_id, payload, headers):
        return self._request("POST", f"/photos/{photo_id}/revalidate", payload, headers)

    # ─── Fee assessments ──────────────────────────────
    def get_fee_assessment(self, fee_id, headers):
        return self._request("GET", f"/fee-assessments/{fee_id}", headers=headers)

    def list_fee_assessments(self, headers, params=None):
        return self._request("GET", "/fee-assessments", headers=headers, params=params)

    def pay_fee_assessment(self, fee_id, payload, headers):
        return self._request("POST", f"/fee-assessments/{fee_id}/pay", payload, headers)

    # ─── Facilities / counters / agents / adjudicators ─
    def create_acceptance_facility(self, payload, headers):
        return self._request("POST", "/acceptance-facilities", payload, headers)

    def get_acceptance_facility(self, facility_id, headers):
        return self._request("GET", f"/acceptance-facilities/{facility_id}", headers=headers)

    def create_urgent_travel_counter(self, payload, headers):
        return self._request("POST", "/urgent-travel-counters", payload, headers)

    def get_urgent_travel_counter(self, counter_id, headers):
        return self._request("GET", f"/urgent-travel-counters/{counter_id}", headers=headers)

    def create_acceptance_agent(self, payload, headers):
        return self._request("POST", "/acceptance-agents", payload, headers)

    def get_acceptance_agent(self, agent_id, headers):
        return self._request("GET", f"/acceptance-agents/{agent_id}", headers=headers)

    def list_acceptance_agents(self, headers, params=None):
        return self._request("GET", "/acceptance-agents", headers=headers, params=params)

    def create_adjudicator(self, payload, headers):
        return self._request("POST", "/adjudicators", payload, headers)

    def get_adjudicator(self, adjudicator_id, headers):
        return self._request("GET", f"/adjudicators/{adjudicator_id}", headers=headers)

    # ─── Appointments ─────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/appointments", headers=headers, params=params)

    def cancel_appointment(self, appointment_id, headers, payload=None):
        return self._request("POST", f"/appointments/{appointment_id}/cancel", payload or {}, headers)

    def complete_appointment(self, appointment_id, headers, payload=None):
        return self._request("POST", f"/appointments/{appointment_id}/complete", payload or {}, headers)

    # ─── Adjudication decisions ───────────────────────
    def list_adjudication_decisions_for_application(self, application_id, headers, params=None):
        return self._request("GET", f"/applications/{application_id}/adjudication-decisions", headers=headers, params=params)

    def list_adjudication_decisions(self, headers, params=None):
        return self._request("GET", "/adjudication-decisions", headers=headers, params=params)

    # ─── Test clock ───────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
