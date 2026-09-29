"""Typed HTTP client for the Government Cloud Authorization Program API.

One method per endpoint in PRD 4. Every method returns the raw
``requests.Response`` so tests can assert on status codes and error envelopes.
"""

from typing import Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per endpoint of the program API."""

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, payload: dict, headers: Dict[str, str]):
        """POST /_clock/set_current_utc"""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------
    # Agencies
    # ------------------------------------------------------------------

    def create_agency(self, payload: dict, headers: Dict[str, str]):
        """POST /agencies"""
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id: str, headers: Dict[str, str]):
        """GET /agencies/{id}"""
        return self._request("GET", f"/agencies/{agency_id}", None, headers)

    # ------------------------------------------------------------------
    # Control baselines
    # ------------------------------------------------------------------

    def create_control_baseline(self, payload: dict, headers: Dict[str, str]):
        """POST /control-baselines"""
        return self._request("POST", "/control-baselines", payload, headers)

    # ------------------------------------------------------------------
    # Offerings
    # ------------------------------------------------------------------

    def create_offering(self, payload: dict, headers: Dict[str, str]):
        """POST /offerings"""
        return self._request("POST", "/offerings", payload, headers)

    def get_offering(self, offering_id: str, headers: Dict[str, str]):
        """GET /offerings/{id}"""
        return self._request("GET", f"/offerings/{offering_id}", None, headers)

    def list_offerings(self, headers: Dict[str, str], params: Optional[dict] = None):
        """GET /offerings"""
        return self._request("GET", "/offerings", params, headers)

    # ------------------------------------------------------------------
    # Data categories
    # ------------------------------------------------------------------

    def create_data_category(
        self, offering_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /offerings/{id}/data-categories"""
        return self._request(
            "POST", f"/offerings/{offering_id}/data-categories", payload, headers
        )

    def list_data_categories(
        self, offering_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /offerings/{id}/data-categories"""
        return self._request(
            "GET", f"/offerings/{offering_id}/data-categories", params, headers
        )

    def confirm_data_category(
        self, data_category_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /data-categories/{id}/confirm"""
        return self._request(
            "POST", f"/data-categories/{data_category_id}/confirm", payload, headers
        )

    # ------------------------------------------------------------------
    # Impact determination, path selection, coverage
    # ------------------------------------------------------------------

    def determine_impact(
        self, offering_id: str, payload: Optional[dict], headers: Dict[str, str]
    ):
        """POST /offerings/{id}/impact-determination"""
        return self._request(
            "POST",
            f"/offerings/{offering_id}/impact-determination",
            payload if payload is not None else {},
            headers,
        )

    def select_path(self, offering_id: str, payload: dict, headers: Dict[str, str]):
        """POST /offerings/{id}/path-selection"""
        return self._request(
            "POST", f"/offerings/{offering_id}/path-selection", payload, headers
        )

    def get_crm_coverage(self, offering_id: str, headers: Dict[str, str]):
        """GET /offerings/{id}/crm-coverage"""
        return self._request(
            "GET", f"/offerings/{offering_id}/crm-coverage", None, headers
        )

    # ------------------------------------------------------------------
    # Control implementations
    # ------------------------------------------------------------------

    def create_control_implementation(self, payload: dict, headers: Dict[str, str]):
        """POST /control-implementations"""
        return self._request("POST", "/control-implementations", payload, headers)

    def update_control_implementation(
        self, implementation_id: str, payload: dict, headers: Dict[str, str]
    ):
        """PATCH /control-implementations/{id}"""
        return self._request(
            "PATCH", f"/control-implementations/{implementation_id}", payload, headers
        )

    def get_control_implementation(
        self, implementation_id: str, headers: Dict[str, str]
    ):
        """GET /control-implementations/{id}"""
        return self._request(
            "GET", f"/control-implementations/{implementation_id}", None, headers
        )

    def list_control_implementations(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /control-implementations"""
        return self._request("GET", "/control-implementations", params, headers)

    # ------------------------------------------------------------------
    # Assessment engagements
    # ------------------------------------------------------------------

    def create_engagement(self, payload: dict, headers: Dict[str, str]):
        """POST /assessment-engagements"""
        return self._request("POST", "/assessment-engagements", payload, headers)

    def get_engagement(self, engagement_id: str, headers: Dict[str, str]):
        """GET /assessment-engagements/{id}"""
        return self._request(
            "GET", f"/assessment-engagements/{engagement_id}", None, headers
        )

    def list_offering_engagements(
        self, offering_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /offerings/{id}/assessment-engagements"""
        return self._request(
            "GET", f"/offerings/{offering_id}/assessment-engagements", params, headers
        )

    def submit_plan(self, engagement_id: str, payload: dict, headers: Dict[str, str]):
        """POST /assessment-engagements/{id}/plan"""
        return self._request(
            "POST", f"/assessment-engagements/{engagement_id}/plan", payload, headers
        )

    def decide_plan(self, engagement_id: str, payload: dict, headers: Dict[str, str]):
        """POST /assessment-engagements/{id}/plan-approval"""
        return self._request(
            "POST",
            f"/assessment-engagements/{engagement_id}/plan-approval",
            payload,
            headers,
        )

    def deliver_report(
        self, engagement_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /assessment-engagements/{id}/report"""
        return self._request(
            "POST", f"/assessment-engagements/{engagement_id}/report", payload, headers
        )

    # ------------------------------------------------------------------
    # Test slots
    # ------------------------------------------------------------------

    def create_test_slot(self, payload: dict, headers: Dict[str, str]):
        """POST /test-slots"""
        return self._request("POST", "/test-slots", payload, headers)

    def cancel_test_slot(
        self, slot_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ):
        """POST /test-slots/{id}/cancel"""
        return self._request(
            "POST", f"/test-slots/{slot_id}/cancel", payload or {}, headers
        )

    def list_test_slots(
        self, engagement_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /assessment-engagements/{id}/test-slots"""
        return self._request(
            "GET", f"/assessment-engagements/{engagement_id}/test-slots", params, headers
        )

    # ------------------------------------------------------------------
    # Plan-of-action items
    # ------------------------------------------------------------------

    def create_poam_item(self, payload: dict, headers: Dict[str, str]):
        """POST /poam-items"""
        return self._request("POST", "/poam-items", payload, headers)

    def get_poam_item(self, poam_item_id: str, headers: Dict[str, str]):
        """GET /poam-items/{id}"""
        return self._request("GET", f"/poam-items/{poam_item_id}", None, headers)

    def list_poam_items(self, headers: Dict[str, str], params: Optional[dict] = None):
        """GET /poam-items"""
        return self._request("GET", "/poam-items", params, headers)

    def advance_remediation(
        self, poam_item_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /poam-items/{id}/remediation"""
        return self._request(
            "POST", f"/poam-items/{poam_item_id}/remediation", payload, headers
        )

    # ------------------------------------------------------------------
    # Deviation requests
    # ------------------------------------------------------------------

    def create_deviation_request(self, payload: dict, headers: Dict[str, str]):
        """POST /deviation-requests"""
        return self._request("POST", "/deviation-requests", payload, headers)

    def route_deviation(self, deviation_id: str, payload: dict, headers: Dict[str, str]):
        """POST /deviation-requests/{id}/route"""
        return self._request(
            "POST", f"/deviation-requests/{deviation_id}/route", payload, headers
        )

    def decide_deviation(
        self, deviation_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /deviation-requests/{id}/decision"""
        return self._request(
            "POST", f"/deviation-requests/{deviation_id}/decision", payload, headers
        )

    def get_deviation_request(self, deviation_id: str, headers: Dict[str, str]):
        """GET /deviation-requests/{id}"""
        return self._request(
            "GET", f"/deviation-requests/{deviation_id}", None, headers
        )

    def list_deviation_requests(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /deviation-requests"""
        return self._request("GET", "/deviation-requests", params, headers)

    # ------------------------------------------------------------------
    # Authorization packages
    # ------------------------------------------------------------------

    def create_package(self, payload: dict, headers: Dict[str, str]):
        """POST /authorization-packages"""
        return self._request("POST", "/authorization-packages", payload, headers)

    def submit_package(
        self, package_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ):
        """POST /authorization-packages/{id}/submit"""
        return self._request(
            "POST", f"/authorization-packages/{package_id}/submit", payload or {}, headers
        )

    def review_package(
        self, package_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ):
        """POST /authorization-packages/{id}/review"""
        return self._request(
            "POST", f"/authorization-packages/{package_id}/review", payload or {}, headers
        )

    def request_package_revision(
        self, package_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /authorization-packages/{id}/revision-request"""
        return self._request(
            "POST",
            f"/authorization-packages/{package_id}/revision-request",
            payload,
            headers,
        )

    def decide_package(self, package_id: str, payload: dict, headers: Dict[str, str]):
        """POST /authorization-packages/{id}/decision"""
        return self._request(
            "POST", f"/authorization-packages/{package_id}/decision", payload, headers
        )

    def get_package(self, package_id: str, headers: Dict[str, str]):
        """GET /authorization-packages/{id}"""
        return self._request(
            "GET", f"/authorization-packages/{package_id}", None, headers
        )

    def list_packages(self, headers: Dict[str, str], params: Optional[dict] = None):
        """GET /authorization-packages"""
        return self._request("GET", "/authorization-packages", params, headers)

    # ------------------------------------------------------------------
    # Authorizations
    # ------------------------------------------------------------------

    def get_authorization(self, authorization_id: str, headers: Dict[str, str]):
        """GET /authorizations/{id}"""
        return self._request(
            "GET", f"/authorizations/{authorization_id}", None, headers
        )

    def list_authorizations(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /authorizations"""
        return self._request("GET", "/authorizations", params, headers)

    def get_risk_summary(self, authorization_id: str, headers: Dict[str, str]):
        """GET /authorizations/{id}/risk-summary"""
        return self._request(
            "GET", f"/authorizations/{authorization_id}/risk-summary", None, headers
        )

    # ------------------------------------------------------------------
    # Monitoring periods and scan submissions
    # ------------------------------------------------------------------

    def create_monitoring_period(
        self, authorization_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /authorizations/{id}/monitoring-periods"""
        return self._request(
            "POST",
            f"/authorizations/{authorization_id}/monitoring-periods",
            payload,
            headers,
        )

    def list_monitoring_periods(
        self,
        authorization_id: str,
        headers: Dict[str, str],
        params: Optional[dict] = None,
    ):
        """GET /authorizations/{id}/monitoring-periods"""
        return self._request(
            "GET",
            f"/authorizations/{authorization_id}/monitoring-periods",
            params,
            headers,
        )

    def get_monitoring_period(self, period_id: str, headers: Dict[str, str]):
        """GET /monitoring-periods/{id}"""
        return self._request("GET", f"/monitoring-periods/{period_id}", None, headers)

    def create_scan_submission(
        self, period_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /monitoring-periods/{id}/scan-submissions"""
        return self._request(
            "POST", f"/monitoring-periods/{period_id}/scan-submissions", payload, headers
        )

    def list_scan_submissions(
        self, period_id: str, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /monitoring-periods/{id}/scan-submissions"""
        return self._request(
            "GET", f"/monitoring-periods/{period_id}/scan-submissions", params, headers
        )

    def close_monitoring_period(
        self, period_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ):
        """POST /monitoring-periods/{id}/close"""
        return self._request(
            "POST", f"/monitoring-periods/{period_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Significant change requests
    # ------------------------------------------------------------------

    def create_change_request(self, payload: dict, headers: Dict[str, str]):
        """POST /significant-change-requests"""
        return self._request("POST", "/significant-change-requests", payload, headers)

    def decide_change_request(
        self, change_request_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /significant-change-requests/{id}/decision"""
        return self._request(
            "POST",
            f"/significant-change-requests/{change_request_id}/decision",
            payload,
            headers,
        )

    def get_change_request(self, change_request_id: str, headers: Dict[str, str]):
        """GET /significant-change-requests/{id}"""
        return self._request(
            "GET", f"/significant-change-requests/{change_request_id}", None, headers
        )

    def list_change_requests(
        self, headers: Dict[str, str], params: Optional[dict] = None
    ):
        """GET /significant-change-requests"""
        return self._request("GET", "/significant-change-requests", params, headers)

    # ------------------------------------------------------------------
    # Reuse grants
    # ------------------------------------------------------------------

    def create_reuse_grant(self, payload: dict, headers: Dict[str, str]):
        """POST /reuse-grants"""
        return self._request("POST", "/reuse-grants", payload, headers)

    def grant_package_access(
        self, grant_id: str, headers: Dict[str, str], payload: Optional[dict] = None
    ):
        """POST /reuse-grants/{id}/package-access"""
        return self._request(
            "POST", f"/reuse-grants/{grant_id}/package-access", payload or {}, headers
        )

    def record_incremental_review(
        self, grant_id: str, payload: dict, headers: Dict[str, str]
    ):
        """POST /reuse-grants/{id}/incremental-review"""
        return self._request(
            "POST", f"/reuse-grants/{grant_id}/incremental-review", payload, headers
        )

    def revoke_reuse_grant(self, grant_id: str, payload: dict, headers: Dict[str, str]):
        """POST /reuse-grants/{id}/revoke"""
        return self._request(
            "POST", f"/reuse-grants/{grant_id}/revoke", payload, headers
        )

    def get_reuse_grant(self, grant_id: str, headers: Dict[str, str]):
        """GET /reuse-grants/{id}"""
        return self._request("GET", f"/reuse-grants/{grant_id}", None, headers)

    def list_reuse_grants(self, headers: Dict[str, str], params: Optional[dict] = None):
        """GET /reuse-grants"""
        return self._request("GET", "/reuse-grants", params, headers)
