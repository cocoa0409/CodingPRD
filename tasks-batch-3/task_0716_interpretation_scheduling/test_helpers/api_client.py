"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/interpretation"


class ApiClient(GenericApiClient):
    # ---- ClientAccount ----
    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"{PREFIX}/clients/{client_id}/suspend", headers=headers)

    # ---- RatePlan ----
    def create_rate_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rate-plans", payload, headers)

    def get_rate_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/rate-plans/{plan_id}", headers=headers)

    def list_rate_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rate-plans", headers=headers, params=params)

    # ---- LanguagePair ----
    def create_language_pair(self, payload, headers):
        return self._request("POST", f"{PREFIX}/language-pairs", payload, headers)

    def get_language_pair(self, lp_id, headers):
        return self._request("GET", f"{PREFIX}/language-pairs/{lp_id}", headers=headers)

    # ---- Interpreter ----
    def create_interpreter(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interpreters", payload, headers)

    def get_interpreter(self, interpreter_id, headers):
        return self._request("GET", f"{PREFIX}/interpreters/{interpreter_id}", headers=headers)

    def list_interpreters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/interpreters", headers=headers, params=params)

    def set_interpreter_status(self, interpreter_id, payload, headers):
        return self._request("POST", f"{PREFIX}/interpreters/{interpreter_id}/status", payload, headers)

    # ---- Certification ----
    def create_certification(self, interpreter_id, payload, headers):
        return self._request("POST", f"{PREFIX}/interpreters/{interpreter_id}/certifications", payload, headers)

    def list_certifications(self, interpreter_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/interpreters/{interpreter_id}/certifications", headers=headers, params=params)

    def revoke_certification(self, cert_id, headers):
        return self._request("POST", f"{PREFIX}/certifications/{cert_id}/revoke", headers=headers)

    # ---- InterpreterLanguage (junction) ----
    def create_language_grant(self, interpreter_id, payload, headers):
        return self._request("POST", f"{PREFIX}/interpreters/{interpreter_id}/languages", payload, headers)

    def list_language_grants(self, interpreter_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/interpreters/{interpreter_id}/languages", headers=headers, params=params)

    def get_interpreter_language(self, junction_id, headers):
        return self._request("GET", f"{PREFIX}/interpreter-languages/{junction_id}", headers=headers)

    def list_interpreter_languages(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/interpreter-languages", headers=headers, params=params)

    # ---- InterpretationRequest ----
    def create_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/requests", payload, headers)

    def get_request(self, request_id, headers):
        return self._request("GET", f"{PREFIX}/requests/{request_id}", headers=headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/requests", headers=headers, params=params)

    def dispatch_request(self, request_id, payload, headers):
        return self._request("POST", f"{PREFIX}/requests/{request_id}/dispatch", payload, headers)

    def cancel_request(self, request_id, headers):
        return self._request("POST", f"{PREFIX}/requests/{request_id}/cancel", headers=headers)

    # ---- Assignment ----
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/accept", headers=headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/decline", headers=headers)

    def start_session(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/start-session", headers=headers)

    # ---- Session ----
    def get_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sessions", headers=headers, params=params)

    def connect_session(self, session_id, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/connect", headers=headers)

    def end_session(self, session_id, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/end", headers=headers)

    def mark_no_show(self, session_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/mark-no-show", payload, headers)

    def dispute_session(self, session_id, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/dispute", headers=headers)

    def reopen_session(self, session_id, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/reopen", headers=headers)

    def reconcile_session(self, session_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/reconcile", payload, headers)

    # ---- Rating ----
    def rate_session(self, session_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/rating", payload, headers)

    def list_session_ratings(self, session_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/sessions/{session_id}/ratings", headers=headers, params=params)

    def get_rating(self, rating_id, headers):
        return self._request("GET", f"{PREFIX}/ratings/{rating_id}", headers=headers)

    def list_ratings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/ratings", headers=headers, params=params)

    # ---- Encounter ----
    def create_encounter(self, session_id, payload, headers):
        return self._request("POST", f"{PREFIX}/sessions/{session_id}/encounters", payload, headers)

    def list_encounters(self, session_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/sessions/{session_id}/encounters", headers=headers, params=params)

    # ---- Complaint ----
    def create_complaint(self, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"{PREFIX}/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/complaints", headers=headers, params=params)

    def review_complaint(self, complaint_id, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/review", headers=headers)

    def request_info_complaint(self, complaint_id, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/request-info", headers=headers)

    def resubmit_complaint(self, complaint_id, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/resubmit", headers=headers)

    def resolve_complaint(self, complaint_id, payload, headers):
        return self._request("POST", f"{PREFIX}/complaints/{complaint_id}/resolve", payload, headers)

    # ---- Invoice ----
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/issue", headers=headers)

    def settle_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/settle", headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
