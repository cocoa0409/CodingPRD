"""Typed HTTP client for the Licensure Portability API.

One method per endpoint documented in the PRD's endpoint table, so a test never
has to spell a URL.  Every method returns the raw `requests.Response` so that
status codes and error envelopes remain assertable.
"""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX

Headers = Optional[Dict[str, str]]
Payload = Optional[Dict[str, Any]]


class ApiClient(GenericApiClient):
    """Endpoint methods for every operation in the Licensure Portability API."""

    # ─── Professions ──────────────────────────────────

    def create_profession(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/professions", payload, headers)

    def get_profession(self, profession_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/professions/{profession_id}", None, headers)

    # ─── Reciprocal agreements (compacts) ─────────────

    def create_reciprocal_agreement(
        self, profession_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/professions/{profession_id}/reciprocal-agreements", payload, headers
        )

    def list_reciprocal_agreements(
        self, profession_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/professions/{profession_id}/reciprocal-agreements", params, headers
        )

    # ─── Applicants ───────────────────────────────────

    def create_applicant(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/applicants", payload, headers)

    def get_applicant(self, applicant_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/applicants/{applicant_id}", None, headers)

    # ─── Out-of-state credentials ─────────────────────

    def create_credential(
        self, applicant_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applicants/{applicant_id}/out-of-state-credentials", payload, headers
        )

    def list_credentials(
        self, applicant_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applicants/{applicant_id}/out-of-state-credentials", params, headers
        )

    # ─── Military training records ────────────────────

    def create_training_record(
        self, applicant_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applicants/{applicant_id}/military-training-records", payload, headers
        )

    def list_training_records(
        self, applicant_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applicants/{applicant_id}/military-training-records", params, headers
        )

    # ─── Disciplinary records ─────────────────────────

    def create_disciplinary_record(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/disciplinary-records", payload, headers)

    def list_disciplinary_records(
        self, applicant_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applicants/{applicant_id}/disciplinary-records", params, headers
        )

    def resolve_disciplinary_record(
        self, record_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/disciplinary-records/{record_id}/resolve", payload or {}, headers
        )

    # ─── Applications ─────────────────────────────────

    def create_application(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/applications", payload, headers)

    def get_application(self, application_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/applications/{application_id}", None, headers)

    def list_applications(self, headers: Headers = None, params: Payload = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/applications", params, headers)

    def submit_application(
        self, application_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applications/{application_id}/submit", payload or {}, headers
        )

    def create_payment(
        self, application_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applications/{application_id}/payments", payload, headers
        )

    def list_fee_ledger_entries(
        self, application_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applications/{application_id}/fee-ledger-entries", params, headers
        )

    def record_exam_result(
        self, application_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applications/{application_id}/exam-results", payload, headers
        )

    def record_deficiency(
        self, application_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applications/{application_id}/deficiency", payload, headers
        )

    def cure_application(
        self, application_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applications/{application_id}/cure", payload or {}, headers
        )

    def issue_decision(
        self, application_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/applications/{application_id}/decision", payload, headers
        )

    def list_application_permits(
        self, application_id: str, headers: Headers = None, params: Payload = None
    ) -> requests.Response:
        return self._request(
            "GET", f"{API_PREFIX}/applications/{application_id}/temporary-permits", params, headers
        )

    # ─── Credential evaluations ───────────────────────

    def create_evaluation(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/credential-evaluations", payload, headers)

    def get_evaluation(self, evaluation_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/credential-evaluations/{evaluation_id}", None, headers)

    def list_evaluations(self, headers: Headers = None, params: Payload = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/credential-evaluations", params, headers)

    def record_scope_review(
        self, evaluation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/credential-evaluations/{evaluation_id}/scope-review", payload, headers
        )

    def record_discipline_finding(
        self, evaluation_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"{API_PREFIX}/credential-evaluations/{evaluation_id}/discipline-finding",
            payload,
            headers,
        )

    def finalize_evaluation(
        self, evaluation_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/credential-evaluations/{evaluation_id}/finalize", payload or {}, headers
        )

    # ─── Credit awards ────────────────────────────────

    def create_credit_award(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/credit-awards", payload, headers)

    def get_credit_award(self, award_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/credit-awards/{award_id}", None, headers)

    def list_credit_awards(self, headers: Headers = None, params: Payload = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/credit-awards", params, headers)

    def revoke_credit_award(
        self, award_id: str, payload: Payload = None, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/credit-awards/{award_id}/revoke", payload or {}, headers
        )

    # ─── Temporary permits ────────────────────────────

    def create_temporary_permit(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/temporary-permits", payload, headers)

    def revoke_temporary_permit(
        self, permit_id: str, payload: Payload, headers: Headers = None
    ) -> requests.Response:
        return self._request(
            "POST", f"{API_PREFIX}/temporary-permits/{permit_id}/revoke", payload, headers
        )

    def run_permit_expiry(self, payload: Payload = None, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/permit-expiry-runs", payload or {}, headers)

    # ─── Evaluators and review assignments ────────────

    def create_evaluator(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/evaluators", payload, headers)

    def get_evaluator(self, evaluator_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/evaluators/{evaluator_id}", None, headers)

    def create_review_assignment(self, payload: Payload, headers: Headers = None) -> requests.Response:
        return self._request("POST", f"{API_PREFIX}/review-assignments", payload, headers)

    def get_review_assignment(self, assignment_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/review-assignments/{assignment_id}", None, headers)

    def list_review_assignments(self, headers: Headers = None, params: Payload = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/review-assignments", params, headers)

    # ─── Licenses ─────────────────────────────────────

    def get_license(self, license_id: str, headers: Headers = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses/{license_id}", None, headers)

    def list_licenses(self, headers: Headers = None, params: Payload = None) -> requests.Response:
        return self._request("GET", f"{API_PREFIX}/licenses", params, headers)

    # ─── Logical clock ────────────────────────────────

    def set_clock(self, to_iso8601: str, headers: Headers = None) -> requests.Response:
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


# Module-level shared instance used by the fixtures and tests.
api_client = ApiClient()
