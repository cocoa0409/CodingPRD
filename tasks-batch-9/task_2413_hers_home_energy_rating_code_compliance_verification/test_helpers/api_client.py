"""One method per endpoint of PRD §4.  The API is mounted at the server root.

Every method returns the raw `requests.Response` so tests can assert on status
codes as well as bodies.  Payloads are passed through untouched so that tests
can deliberately omit required fields.
"""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """HERS Rating & Code Compliance API client."""

    # ---------------------------------------------------------------- builders
    def create_builder(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/builders", payload, headers)

    def get_builder(self, builder_id: str, headers) -> requests.Response:
        return self._request("GET", f"/builders/{builder_id}", None, headers)

    # ------------------------------------------------------------ subdivisions
    def create_subdivision(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/subdivisions", payload, headers)

    def get_subdivision(self, subdivision_id: str, headers) -> requests.Response:
        return self._request("GET", f"/subdivisions/{subdivision_id}", None, headers)

    def list_subdivisions(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/subdivisions", params or {}, headers)

    # ------------------------------------------------------------- plan models
    def create_plan_model(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/plan-models", payload, headers)

    def list_plan_models(
        self, subdivision_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/subdivisions/{subdivision_id}/plan-models", params or {}, headers
        )

    # ------------------------------------------------------------------- homes
    def create_home(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/homes", payload, headers)

    def get_home(self, home_id: str, headers) -> requests.Response:
        return self._request("GET", f"/homes/{home_id}", None, headers)

    def list_homes(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/homes", params or {}, headers)

    # ------------------------------------------------------------------ raters
    def create_rater(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/raters", payload, headers)

    def get_rater(self, rater_id: str, headers) -> requests.Response:
        return self._request("GET", f"/raters/{rater_id}", None, headers)

    def reinstate_rater(
        self, rater_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/raters/{rater_id}/reinstate", payload, headers)

    # ----------------------------------------------------------------- ratings
    def create_rating(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/ratings", payload, headers)

    def get_rating(self, rating_id: str, headers) -> requests.Response:
        return self._request("GET", f"/ratings/{rating_id}", None, headers)

    def list_ratings(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/ratings", params or {}, headers)

    def confirm_rating(self, rating_id: str, headers, payload: Optional[Dict] = None):
        return self._request("POST", f"/ratings/{rating_id}/confirm", payload or {}, headers)

    def void_rating(self, rating_id: str, payload: Dict[str, Any], headers):
        return self._request("POST", f"/ratings/{rating_id}/void", payload, headers)

    def submit_rating_to_registry(
        self, rating_id: str, headers, payload: Optional[Dict] = None
    ):
        return self._request(
            "POST", f"/ratings/{rating_id}/submit-to-registry", payload or {}, headers
        )

    def record_registry_decision(self, rating_id: str, payload: Dict[str, Any], headers):
        return self._request(
            "POST", f"/ratings/{rating_id}/registry-decision", payload, headers
        )

    # ------------------------------------------------------------- inspections
    def create_inspection(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id: str, headers) -> requests.Response:
        return self._request("GET", f"/inspections/{inspection_id}", None, headers)

    def list_inspections(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/inspections", params or {}, headers)

    def create_diagnostic_test(
        self, inspection_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/inspections/{inspection_id}/tests", payload, headers)

    def list_diagnostic_tests(
        self, inspection_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/inspections/{inspection_id}/tests", params or {}, headers
        )

    def complete_inspection(
        self, inspection_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/inspections/{inspection_id}/complete", payload or {}, headers
        )

    # ------------------------------------------------------------- sample sets
    def create_sample_set(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/sample-sets", payload, headers)

    def get_sample_set(self, sample_set_id: str, headers) -> requests.Response:
        return self._request("GET", f"/sample-sets/{sample_set_id}", None, headers)

    def list_sample_sets(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/sample-sets", params or {}, headers)

    def add_sample_set_home(
        self, sample_set_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/sample-sets/{sample_set_id}/homes", payload, headers)

    def withdraw_sample_set_home(
        self, sample_set_id: str, home_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST",
            f"/sample-sets/{sample_set_id}/homes/{home_id}/withdraw",
            payload,
            headers,
        )

    def select_sample_set(
        self, sample_set_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/sample-sets/{sample_set_id}/select", payload or {}, headers
        )

    def close_sample_set(
        self, sample_set_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/sample-sets/{sample_set_id}/close", payload or {}, headers
        )

    # -------------------------------------------------------------- qa reviews
    def create_qa_review(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/qa-reviews", payload, headers)

    def get_qa_review(self, qa_review_id: str, headers) -> requests.Response:
        return self._request("GET", f"/qa-reviews/{qa_review_id}", None, headers)

    def list_qa_reviews(self, headers, params: Optional[Dict] = None) -> requests.Response:
        return self._request("GET", "/qa-reviews", params or {}, headers)

    def complete_qa_review(
        self, qa_review_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request("POST", f"/qa-reviews/{qa_review_id}/complete", payload, headers)

    # ------------------------------------------------------- corrective actions
    def list_corrective_actions(
        self, rating_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/ratings/{rating_id}/corrective-actions", params or {}, headers
        )

    def submit_corrective_action(
        self, corrective_action_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-actions/{corrective_action_id}/submit", payload, headers
        )

    def review_corrective_action(
        self, corrective_action_id: str, payload: Dict[str, Any], headers
    ) -> requests.Response:
        return self._request(
            "POST", f"/corrective-actions/{corrective_action_id}/review", payload, headers
        )

    # ------------------------------------------------------- document packages
    def create_document_package(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/document-packages", payload, headers)

    def issue_document_package(
        self, package_id: str, headers, payload: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "POST", f"/document-packages/{package_id}/issue", payload or {}, headers
        )

    def list_document_packages(
        self, rating_id: str, headers, params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/ratings/{rating_id}/document-packages", params or {}, headers
        )

    # ------------------------------------------------------------ logical clock
    def set_clock(self, payload: Dict[str, Any], headers) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)
