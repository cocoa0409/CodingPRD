"""API client: one method per endpoint declared by the PRD.

Every business resource is mounted under ``/cancer-registry``; the logical clock
endpoint is the single exception and sits outside that prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/cancer-registry"


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- programs
    def create_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}", headers=headers)

    def get_compliance_summary(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/programs/{program_id}/compliance-summary",
            headers=headers,
            params=params,
        )

    def survey_schedule(self, program_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/survey-schedule", payload, headers
        )

    def survey_complete(self, program_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/programs/{program_id}/survey-complete", payload, headers
        )

    def accreditation_decision(self, program_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/programs/{program_id}/accreditation-decision",
            payload,
            headers,
        )

    # ------------------------------------------------------------- abstractors
    def create_abstractor(self, payload, headers):
        return self._request("POST", f"{PREFIX}/abstractors", payload, headers)

    def list_abstractors(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/abstractors", headers=headers, params=params
        )

    def get_abstractor(self, abstractor_id, headers):
        return self._request(
            "GET", f"{PREFIX}/abstractors/{abstractor_id}", headers=headers
        )

    def set_employment_status(self, abstractor_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/abstractors/{abstractor_id}/employment-status",
            payload,
            headers,
        )

    # ------------------------------------------------------ casefinding sources
    def create_casefinding_source(self, payload, headers):
        return self._request("POST", f"{PREFIX}/casefinding-sources", payload, headers)

    def list_casefinding_sources(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/casefinding-sources", headers=headers, params=params
        )

    def get_casefinding_source(self, source_id, headers):
        return self._request(
            "GET", f"{PREFIX}/casefinding-sources/{source_id}", headers=headers
        )

    def create_casefinding_entry(self, source_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/casefinding-sources/{source_id}/entries", payload, headers
        )

    def list_casefinding_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/casefinding-entries", headers=headers, params=params
        )

    def get_casefinding_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/casefinding-entries/{entry_id}", headers=headers
        )

    def reportability_decision(self, entry_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/casefinding-entries/{entry_id}/reportability-decision",
            payload,
            headers,
        )

    def reopen_casefinding_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/casefinding-entries/{entry_id}/reopen", payload, headers
        )

    # ------------------------------------------------------------- tumor cases
    def list_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/cases/{case_id}", headers=headers)

    def assign_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/assign", payload, headers
        )

    def unassign_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/unassign", payload, headers
        )

    def create_follow_up_contact(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cases/{case_id}/follow-up-contacts", payload, headers
        )

    def get_follow_up_contact(self, contact_id, headers):
        return self._request(
            "GET", f"{PREFIX}/follow-up-contacts/{contact_id}", headers=headers
        )

    def list_follow_up_contacts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/follow-up-contacts", headers=headers, params=params
        )

    # ------------------------------------------------------------ abstractions
    def create_abstraction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/abstractions", payload, headers)

    def list_abstractions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/abstractions", headers=headers, params=params
        )

    def get_abstraction(self, abstraction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/abstractions/{abstraction_id}", headers=headers
        )

    def submit_qa(self, abstraction_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/abstractions/{abstraction_id}/submit-qa", payload, headers
        )

    def qa_decision(self, abstraction_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/abstractions/{abstraction_id}/qa-decision",
            payload,
            headers,
        )

    def reopen_draft(self, abstraction_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/abstractions/{abstraction_id}/reopen-draft",
            payload,
            headers,
        )

    # ---------------------------------------------------------------- qa audits
    def create_qa_audit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/qa-audits", payload, headers)

    def list_qa_audits(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/qa-audits", headers=headers, params=params
        )

    def get_qa_audit(self, audit_id, headers):
        return self._request("GET", f"{PREFIX}/qa-audits/{audit_id}", headers=headers)

    def score_qa_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/qa-audits/{audit_id}/score", payload, headers
        )

    def void_qa_audit(self, audit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/qa-audits/{audit_id}/void", payload, headers
        )

    # ------------------------------------------------------ conference sessions
    def create_conference_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/conference-sessions", payload, headers)

    def list_conference_sessions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/conference-sessions", headers=headers, params=params
        )

    def get_conference_session(self, session_id, headers):
        return self._request(
            "GET", f"{PREFIX}/conference-sessions/{session_id}", headers=headers
        )

    def record_attendance(self, session_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/conference-sessions/{session_id}/attendances",
            payload,
            headers,
        )

    def hold_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/conference-sessions/{session_id}/hold", payload, headers
        )

    def credit_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/conference-sessions/{session_id}/credit", payload, headers
        )

    # ------------------------------------------------------------- submissions
    def create_submission(self, payload, headers):
        return self._request("POST", f"{PREFIX}/submissions", payload, headers)

    def list_submissions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/submissions", headers=headers, params=params
        )

    def get_submission(self, submission_id, headers):
        return self._request(
            "GET", f"{PREFIX}/submissions/{submission_id}", headers=headers
        )

    def add_submission_item(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/items", payload, headers
        )

    def list_submission_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/submission-items", headers=headers, params=params
        )

    def get_submission_item(self, item_id, headers):
        return self._request(
            "GET", f"{PREFIX}/submission-items/{item_id}", headers=headers
        )

    def transmit_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/transmit", payload, headers
        )

    def post_edit_results(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/submissions/{submission_id}/edit-results",
            payload,
            headers,
        )

    def resolve_submission_item(self, submission_id, item_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/submissions/{submission_id}/items/{item_id}/resolve",
            payload,
            headers,
        )

    def retransmit_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/submissions/{submission_id}/retransmit", payload, headers
        )

    def create_assessment_payment(self, submission_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/submissions/{submission_id}/assessment-payments",
            payload,
            headers,
        )

    # ------------------------------------------------------------ deficiencies
    def create_deficiency(self, payload, headers):
        return self._request("POST", f"{PREFIX}/deficiencies", payload, headers)

    def list_deficiencies(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/deficiencies", headers=headers, params=params
        )

    def get_deficiency(self, deficiency_id, headers):
        return self._request(
            "GET", f"{PREFIX}/deficiencies/{deficiency_id}", headers=headers
        )

    def respond_to_deficiency(self, deficiency_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deficiencies/{deficiency_id}/response", payload, headers
        )

    def review_deficiency_response(self, deficiency_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/deficiencies/{deficiency_id}/response-review",
            payload,
            headers,
        )

    # --------------------------------------------------------- quality measures
    def create_quality_measure(self, payload, headers):
        return self._request("POST", f"{PREFIX}/quality-measures", payload, headers)

    def list_quality_measures(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/quality-measures", headers=headers, params=params
        )

    def get_quality_measure(self, measure_id, headers):
        return self._request(
            "GET", f"{PREFIX}/quality-measures/{measure_id}", headers=headers
        )

    def evaluate_quality_measure(self, measure_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/quality-measures/{measure_id}/evaluate",
            payload,
            headers,
        )

    def improvement_project(self, measure_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/quality-measures/{measure_id}/improvement-project",
            payload,
            headers,
        )

    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
