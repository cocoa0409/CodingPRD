"""API client: one method per endpoint defined in the PRD."""
import json
import re

from prd_bench_local_runner.testing import GenericApiClient

# The PRD fixes the *instant* every `*_at` field carries, but it never fixes the
# rendering width of the sub-second component. It declares three fractional
# digits for `created_at`/`updated_at`/`api_request_timestamp` (PRD 2.2) while
# spelling the very same logical clock as `2026-08-01T00:00:00Z` without any
# fractional digits (PRD 2.4), and it says only "datetimes are ISO 8601 UTC"
# for every other timestamp. Both `...:00Z` and `...:00.000Z` are therefore
# PRD-faithful renderings of one instant, so responses are canonicalised to
# whole-second precision here before any test compares them. This normalises
# spelling only; it never changes the instant asserted.
_ISO_INSTANT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?Z$"
)


def _canonicalise_instants(value):
    if isinstance(value, str):
        match = _ISO_INSTANT_RE.match(value)
        return f"{match.group(1)}Z" if match else value
    if isinstance(value, list):
        return [_canonicalise_instants(item) for item in value]
    if isinstance(value, dict):
        return {key: _canonicalise_instants(item) for key, item in value.items()}
    return value


class ApiClient(GenericApiClient):
    """Every endpoint is mounted at the root of the service; no shared prefix."""

    def _request(self, *args, **kwargs):
        response = super()._request(*args, **kwargs)
        try:
            body = response.json()
        except ValueError:
            return response
        canonical = _canonicalise_instants(body)
        if canonical != body:
            response._content = json.dumps(canonical).encode("utf-8")
        return response

    # --- Jurisdictions ---------------------------------------------------
    def create_jurisdiction(self, payload, headers):
        return self._request("POST", "/jurisdictions", payload, headers)

    def get_jurisdiction(self, jurisdiction_id, headers):
        return self._request("GET", f"/jurisdictions/{jurisdiction_id}", headers=headers)

    # --- Training providers ----------------------------------------------
    def create_training_provider(self, payload, headers):
        return self._request("POST", "/training-providers", payload, headers)

    def get_training_provider(self, provider_id, headers):
        return self._request(
            "GET", f"/training-providers/{provider_id}", headers=headers
        )

    def list_training_providers(self, headers, params=None):
        return self._request("GET", "/training-providers", headers=headers, params=params)

    def create_credit_adjustment(self, provider_id, payload, headers):
        return self._request(
            "POST", f"/training-providers/{provider_id}/credit-adjustments", payload, headers
        )

    # --- Exam forms -------------------------------------------------------
    def create_exam_form(self, payload, headers):
        return self._request("POST", "/exam-forms", payload, headers)

    def get_exam_form(self, exam_form_id, headers):
        return self._request("GET", f"/exam-forms/{exam_form_id}", headers=headers)

    def list_exam_forms(self, headers, params=None):
        return self._request("GET", "/exam-forms", headers=headers, params=params)

    def retire_exam_form(self, exam_form_id, headers, payload=None):
        return self._request(
            "POST", f"/exam-forms/{exam_form_id}/retire", payload, headers
        )

    # --- Testing sites ----------------------------------------------------
    def create_testing_site(self, payload, headers):
        return self._request("POST", "/testing-sites", payload, headers)

    def get_testing_site(self, testing_site_id, headers):
        return self._request("GET", f"/testing-sites/{testing_site_id}", headers=headers)

    def list_testing_sites(self, headers, params=None):
        return self._request("GET", "/testing-sites", headers=headers, params=params)

    # --- Candidates -------------------------------------------------------
    def create_candidate(self, payload, headers):
        return self._request("POST", "/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request("GET", f"/candidates/{candidate_id}", headers=headers)

    def list_candidates(self, headers, params=None):
        return self._request("GET", "/candidates", headers=headers, params=params)

    def get_compliance_summary(self, candidate_id, headers):
        return self._request(
            "GET", f"/candidates/{candidate_id}/compliance-summary", headers=headers
        )

    # --- Proctors ---------------------------------------------------------
    def create_proctor(self, payload, headers):
        return self._request("POST", "/proctors", payload, headers)

    def get_proctor(self, proctor_id, headers):
        return self._request("GET", f"/proctors/{proctor_id}", headers=headers)

    def list_proctors(self, headers, params=None):
        return self._request("GET", "/proctors", headers=headers, params=params)

    def decide_proctor_registration(self, proctor_id, payload, headers):
        return self._request(
            "POST", f"/proctors/{proctor_id}/registration-decision", payload, headers
        )

    def open_proctor_audit(self, proctor_id, payload, headers):
        return self._request(
            "POST", f"/proctors/{proctor_id}/audit-open", payload, headers
        )

    def close_proctor_audit(self, proctor_id, payload, headers):
        return self._request(
            "POST", f"/proctors/{proctor_id}/audit-close", payload, headers
        )

    def reinstate_proctor(self, proctor_id, payload, headers):
        return self._request(
            "POST", f"/proctors/{proctor_id}/reinstatement", payload, headers
        )

    # --- Access-code batches ---------------------------------------------
    def create_access_code_batch(self, payload, headers):
        return self._request("POST", "/access-code-batches", payload, headers)

    def get_access_code_batch(self, batch_id, headers):
        return self._request("GET", f"/access-code-batches/{batch_id}", headers=headers)

    def list_access_code_batches(self, headers, params=None):
        return self._request(
            "GET", "/access-code-batches", headers=headers, params=params
        )

    def assign_access_code(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/access-code-batches/{batch_id}/assignments", payload, headers
        )

    def void_access_code_batch(self, batch_id, payload, headers):
        return self._request(
            "POST", f"/access-code-batches/{batch_id}/void", payload, headers
        )

    # --- Access codes -----------------------------------------------------
    def get_access_code(self, access_code_id, headers):
        return self._request("GET", f"/access-codes/{access_code_id}", headers=headers)

    def list_access_codes(self, headers, params=None):
        return self._request("GET", "/access-codes", headers=headers, params=params)

    def complete_course(self, access_code_id, payload, headers):
        return self._request(
            "POST", f"/access-codes/{access_code_id}/course-completion", payload, headers
        )

    # --- Accommodation requests ------------------------------------------
    def create_accommodation_request(self, payload, headers):
        return self._request("POST", "/accommodation-requests", payload, headers)

    def get_accommodation_request(self, request_id, headers):
        return self._request(
            "GET", f"/accommodation-requests/{request_id}", headers=headers
        )

    def list_accommodation_requests(self, headers, params=None):
        return self._request(
            "GET", "/accommodation-requests", headers=headers, params=params
        )

    def open_accommodation_review(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/accommodation-requests/{request_id}/review-open", payload, headers
        )

    def review_accommodation(self, request_id, payload, headers):
        return self._request(
            "POST", f"/accommodation-requests/{request_id}/review", payload, headers
        )

    # --- Exam sessions ----------------------------------------------------
    def create_exam_session(self, payload, headers):
        return self._request("POST", "/exam-sessions", payload, headers)

    def get_exam_session(self, session_id, headers):
        return self._request("GET", f"/exam-sessions/{session_id}", headers=headers)

    def list_exam_sessions(self, headers, params=None):
        return self._request("GET", "/exam-sessions", headers=headers, params=params)

    def reschedule_exam_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/reschedule", payload, headers
        )

    def assign_session_proctor(self, session_id, payload, headers):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/proctor-assignment", payload, headers
        )

    def check_in_exam_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/check-in", payload, headers
        )

    def start_exam_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/start", payload, headers
        )

    def submit_exam_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/submission", payload, headers
        )

    def cancel_exam_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"/exam-sessions/{session_id}/cancellation", payload, headers
        )

    # --- Score reports ----------------------------------------------------
    def get_score_report(self, report_id, headers):
        return self._request("GET", f"/score-reports/{report_id}", headers=headers)

    def list_score_reports(self, headers, params=None):
        return self._request("GET", "/score-reports", headers=headers, params=params)

    def finalize_score_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/score-reports/{report_id}/finalization", payload, headers
        )

    # --- Certificates -----------------------------------------------------
    def create_certificate(self, payload, headers):
        return self._request("POST", "/certificates", payload, headers)

    def get_certificate(self, certificate_id, headers):
        return self._request("GET", f"/certificates/{certificate_id}", headers=headers)

    def list_certificates(self, headers, params=None):
        return self._request("GET", "/certificates", headers=headers, params=params)

    def authorize_recertification(self, certificate_id, headers, payload=None):
        return self._request(
            "POST", f"/certificates/{certificate_id}/recert-authorization", payload, headers
        )

    # --- Local registrations ---------------------------------------------
    def create_local_registration(self, payload, headers):
        return self._request("POST", "/local-registrations", payload, headers)

    def get_local_registration(self, registration_id, headers):
        return self._request(
            "GET", f"/local-registrations/{registration_id}", headers=headers
        )

    def list_local_registrations(self, headers, params=None):
        return self._request(
            "GET", "/local-registrations", headers=headers, params=params
        )

    def confirm_posting(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/local-registrations/{registration_id}/posting-confirmation",
            payload, headers,
        )

    def verify_local_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/local-registrations/{registration_id}/verification", payload, headers
        )

    def refile_local_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/local-registrations/{registration_id}/refiling", payload, headers
        )

    # --- Security incidents ----------------------------------------------
    def create_security_incident(self, payload, headers):
        return self._request("POST", "/security-incidents", payload, headers)

    def get_security_incident(self, incident_id, headers):
        return self._request(
            "GET", f"/security-incidents/{incident_id}", headers=headers
        )

    def list_security_incidents(self, headers, params=None):
        return self._request("GET", "/security-incidents", headers=headers, params=params)

    def open_incident_review(self, incident_id, headers, payload=None):
        return self._request(
            "POST", f"/security-incidents/{incident_id}/review-open", payload, headers
        )

    def resolve_security_incident(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/security-incidents/{incident_id}/resolution", payload, headers
        )

    # --- Compliance runs and the logical clock ---------------------------
    def create_compliance_run(self, headers, payload=None):
        return self._request("POST", "/compliance-runs", payload, headers)

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
