"""One method per endpoint row of PRD section 4.

Every method returns the raw ``requests.Response`` so a test can assert the
status code itself. Listing methods take ``params`` for the `limit` / `offset`
parameters of PRD 2.3 together with each listing's own domain filters.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient

Json = Dict[str, Any]
Headers = Dict[str, str]


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the Sterile Fill-Finish CMO API."""

    # ------------------------------------------------------------------
    # The logical clock (PRD 2.4)
    # ------------------------------------------------------------------
    def set_clock(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Client projects (PRD 3.1, 3.9)
    # ------------------------------------------------------------------
    def create_client_project(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/client-projects", payload, headers)

    def get_client_project(
        self, project_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/client-projects/{project_id}", None, headers)

    def list_client_projects(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/client-projects", params, headers)

    def advance_tech_transfer(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/client-projects/{project_id}/advance-tech-transfer",
            payload,
            headers,
        )

    def release_hold(
        self, project_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/client-projects/{project_id}/release-hold", payload, headers
        )

    def get_readiness_assessment(
        self, project_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/client-projects/{project_id}/readiness-assessment",
            params,
            headers,
        )

    def list_project_audit_engagements(
        self, project_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/client-projects/{project_id}/audit-engagements", params, headers
        )

    # ------------------------------------------------------------------
    # Filling suites (PRD 3.2)
    # ------------------------------------------------------------------
    def create_filling_suite(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/filling-suites", payload, headers)

    def get_filling_suite(self, suite_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/filling-suites/{suite_id}", None, headers)

    def list_filling_suites(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/filling-suites", params, headers)

    def record_cleaning_validation(
        self, suite_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/filling-suites/{suite_id}/cleaning-validation", payload, headers
        )

    # ------------------------------------------------------------------
    # Media fills (PRD 3.2)
    # ------------------------------------------------------------------
    def create_media_fill(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/media-fills", payload, headers)

    def get_media_fill(self, media_fill_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/media-fills/{media_fill_id}", None, headers)

    def list_media_fills(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/media-fills", params, headers)

    def execute_media_fill(
        self, media_fill_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/media-fills/{media_fill_id}/execute", payload, headers
        )

    def read_media_fill(
        self, media_fill_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/media-fills/{media_fill_id}/read", payload, headers
        )

    def adjudicate_media_fill(
        self, media_fill_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/media-fills/{media_fill_id}/adjudicate", payload, headers
        )

    # ------------------------------------------------------------------
    # Personnel qualifications (PRD 3.3)
    # ------------------------------------------------------------------
    def create_qualification(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/personnel-qualifications", payload, headers)

    def get_qualification(
        self, qualification_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/personnel-qualifications/{qualification_id}", None, headers
        )

    def list_qualifications(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/personnel-qualifications", params, headers)

    def qualify(
        self, qualification_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/personnel-qualifications/{qualification_id}/qualify",
            payload,
            headers,
        )

    def revoke_qualification(
        self, qualification_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/personnel-qualifications/{qualification_id}/revoke",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Component lots and reservations (PRD 3.4)
    # ------------------------------------------------------------------
    def create_component_lot(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/component-lots", payload, headers)

    def get_component_lot(self, lot_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/component-lots/{lot_id}", None, headers)

    def list_component_lots(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/component-lots", params, headers)

    def record_sterilization_validation(
        self, lot_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/component-lots/{lot_id}/sterilization-validation", payload, headers
        )

    def create_component_reservation(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/component-reservations", payload, headers)

    def get_component_reservation(
        self, reservation_id: str, headers: Headers
    ) -> requests.Response:
        return self._request(
            "GET", f"/component-reservations/{reservation_id}", None, headers
        )

    def list_component_reservations(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/component-reservations", params, headers)

    # ------------------------------------------------------------------
    # Batch orders (PRD 3.5, 3.6, 3.8, 3.9)
    # ------------------------------------------------------------------
    def create_batch_order(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/batch-orders", payload, headers)

    def get_batch_order(self, batch_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/batch-orders/{batch_id}", None, headers)

    def list_batch_orders(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/batch-orders", params, headers)

    def get_unit_accounting(
        self, batch_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/batch-orders/{batch_id}/unit-accounting", params, headers
        )

    def setup_batch(
        self, batch_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request("POST", f"/batch-orders/{batch_id}/setup", payload, headers)

    def start_fill(
        self, batch_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/batch-orders/{batch_id}/start-fill", payload, headers
        )

    def complete_fill(
        self, batch_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/batch-orders/{batch_id}/complete-fill", payload, headers
        )

    def cancel_batch(
        self, batch_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/batch-orders/{batch_id}/cancel", payload, headers
        )

    def list_qp_release_decisions(
        self, batch_id: str, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/batch-orders/{batch_id}/qp-release-decisions", params, headers
        )

    def qp_release(
        self, batch_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/batch-orders/{batch_id}/qp-release", payload, headers
        )

    # ------------------------------------------------------------------
    # In-process controls (PRD 3.6)
    # ------------------------------------------------------------------
    def create_in_process_check(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/in-process-checks", payload, headers)

    def get_in_process_check(self, check_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/in-process-checks/{check_id}", None, headers)

    def list_in_process_checks(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/in-process-checks", params, headers)

    # ------------------------------------------------------------------
    # Environmental monitoring (PRD 3.7)
    # ------------------------------------------------------------------
    def create_em_sample(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/em-samples", payload, headers)

    def get_em_sample(self, sample_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/em-samples/{sample_id}", None, headers)

    def list_em_samples(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/em-samples", params, headers)

    def investigate_em_sample(
        self, sample_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/em-samples/{sample_id}/investigate", payload, headers
        )

    def close_em_investigation(
        self, sample_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/em-samples/{sample_id}/close-investigation", payload, headers
        )

    # ------------------------------------------------------------------
    # Deviations and CAPA (PRD 3.7)
    # ------------------------------------------------------------------
    def create_deviation(self, payload: Json, headers: Headers) -> requests.Response:
        return self._request("POST", "/deviations", payload, headers)

    def get_deviation(self, deviation_id: str, headers: Headers) -> requests.Response:
        return self._request("GET", f"/deviations/{deviation_id}", None, headers)

    def list_deviations(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/deviations", params, headers)

    def classify_deviation(
        self, deviation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deviations/{deviation_id}/classify", payload, headers
        )

    def submit_capa(
        self, deviation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deviations/{deviation_id}/submit-capa", payload, headers
        )

    def decide_capa(
        self, deviation_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/deviations/{deviation_id}/decide-capa", payload, headers
        )

    # ------------------------------------------------------------------
    # Batch record reviews (PRD 3.8)
    # ------------------------------------------------------------------
    def create_batch_record_review(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/batch-record-reviews", payload, headers)

    def get_batch_record_review(
        self, review_id: str, headers: Headers
    ) -> requests.Response:
        return self._request("GET", f"/batch-record-reviews/{review_id}", None, headers)

    def list_batch_record_reviews(
        self, headers: Headers, params: Optional[Json] = None
    ) -> requests.Response:
        return self._request("GET", "/batch-record-reviews", params, headers)

    def record_findings(
        self, review_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/batch-record-reviews/{review_id}/record-findings", payload, headers
        )

    def close_batch_record_review(
        self, review_id: str, headers: Headers, payload: Optional[Json] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/batch-record-reviews/{review_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Audit engagements (PRD 3.9)
    # ------------------------------------------------------------------
    def create_audit_engagement(
        self, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request("POST", "/audit-engagements", payload, headers)

    def host_audit_engagement(
        self, engagement_id: str, payload: Json, headers: Headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/audit-engagements/{engagement_id}/host", payload, headers
        )


# The single client instance every test module shares.
api_client = ApiClient()
