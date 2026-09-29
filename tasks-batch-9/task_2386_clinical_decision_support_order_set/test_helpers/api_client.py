"""API client: one method per endpoint defined by the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Clinical Decision Support Governance API client.

    The governance surface is mounted under /cds; the two test-driving
    capabilities (firing ingest and the logical clock) sit outside it.
    """

    # ------------------------------------------------------------------
    # Clinicians
    # ------------------------------------------------------------------
    def create_clinician(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cds/clinicians", payload, headers)

    def get_clinician(self, clinician_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cds/clinicians/{clinician_id}", headers=headers)

    # ------------------------------------------------------------------
    # Content requests
    # ------------------------------------------------------------------
    def create_content_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cds/content-requests", payload, headers)

    def list_content_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cds/content-requests", headers=headers, params=params)

    def get_content_request(self, content_request_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cds/content-requests/{content_request_id}", headers=headers
        )

    def triage_content_request(
        self, content_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/content-requests/{content_request_id}/triage", payload, headers
        )

    def resubmit_content_request(
        self, content_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/content-requests/{content_request_id}/resubmit", payload, headers
        )

    def create_order_set(
        self, content_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/content-requests/{content_request_id}/order-sets", payload, headers
        )

    def create_alert(
        self, content_request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/content-requests/{content_request_id}/alerts", payload, headers
        )

    # ------------------------------------------------------------------
    # Order sets
    # ------------------------------------------------------------------
    def list_order_sets(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cds/order-sets", headers=headers, params=params)

    def get_order_set(self, order_set_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cds/order-sets/{order_set_id}", headers=headers)

    def create_order_set_item(
        self, order_set_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/order-sets/{order_set_id}/items", payload, headers
        )

    def list_order_set_items(
        self, order_set_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/cds/order-sets/{order_set_id}/items", headers=headers, params=params
        )

    def record_pharmacy_signoff(
        self, order_set_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/order-sets/{order_set_id}/pharmacy-signoff", payload, headers
        )

    def submit_order_set_for_peer_review(
        self, order_set_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/cds/order-sets/{order_set_id}/submit-for-peer-review",
            payload,
            headers,
        )

    def publish_order_set(
        self, order_set_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/order-sets/{order_set_id}/publish", payload, headers
        )

    # ------------------------------------------------------------------
    # Review assignments
    # ------------------------------------------------------------------
    def create_review_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cds/review-assignments", payload, headers)

    def list_review_assignments(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/cds/review-assignments", headers=headers, params=params
        )

    def get_review_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cds/review-assignments/{assignment_id}", headers=headers
        )

    def cast_review_vote(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/review-assignments/{assignment_id}/cast", payload, headers
        )

    def withdraw_review_assignment(
        self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/review-assignments/{assignment_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------
    def list_alerts(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cds/alerts", headers=headers, params=params)

    def get_alert(self, alert_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cds/alerts/{alert_id}", headers=headers)

    def activate_alert(self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/cds/alerts/{alert_id}/activate", payload, headers)

    def suspend_alert(self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/cds/alerts/{alert_id}/suspend", payload, headers)

    def resume_alert(self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/cds/alerts/{alert_id}/resume", payload, headers)

    def retire_alert(self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/cds/alerts/{alert_id}/retire", payload, headers)

    def create_burden_window(
        self, alert_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/alerts/{alert_id}/burden-windows", payload, headers
        )

    def list_burden_windows(
        self, alert_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/cds/alerts/{alert_id}/burden-windows", headers=headers, params=params
        )

    def close_burden_window(
        self,
        alert_id: str,
        window_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/cds/alerts/{alert_id}/burden-windows/{window_id}/close",
            payload,
            headers,
        )

    def reopen_burden_window(
        self,
        alert_id: str,
        window_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/cds/alerts/{alert_id}/burden-windows/{window_id}/reopen",
            payload,
            headers,
        )

    def list_override_events(
        self, alert_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/cds/alerts/{alert_id}/override-events", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Vendor content releases and rule deltas
    # ------------------------------------------------------------------
    def create_vendor_release(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cds/vendor-releases", payload, headers)

    def list_vendor_releases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/cds/vendor-releases", headers=headers, params=params)

    def get_vendor_release(self, release_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cds/vendor-releases/{release_id}", headers=headers)

    def create_vendor_rule_delta(
        self, release_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/vendor-releases/{release_id}/deltas", payload, headers
        )

    def list_vendor_rule_deltas(
        self, release_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/cds/vendor-releases/{release_id}/deltas", headers=headers, params=params
        )

    def run_vendor_release_impact_analysis(
        self, release_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/cds/vendor-releases/{release_id}/run-impact-analysis",
            payload,
            headers,
        )

    def activate_vendor_release(
        self, release_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/vendor-releases/{release_id}/activate", payload, headers
        )

    def disposition_vendor_rule_delta(
        self, delta_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/vendor-rule-deltas/{delta_id}/disposition", payload, headers
        )

    # ------------------------------------------------------------------
    # Downtime events
    # ------------------------------------------------------------------
    def create_downtime_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cds/downtime-events", payload, headers)

    def get_downtime_event(self, downtime_event_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/cds/downtime-events/{downtime_event_id}", headers=headers
        )

    def activate_downtime_event(
        self, downtime_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/downtime-events/{downtime_event_id}/activate", payload, headers
        )

    def close_downtime_event(
        self, downtime_event_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/downtime-events/{downtime_event_id}/close", payload, headers
        )

    # ------------------------------------------------------------------
    # Adherence measurement
    # ------------------------------------------------------------------
    def create_adherence_measurement(
        self, order_set_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/cds/order-sets/{order_set_id}/adherence-measurements",
            payload,
            headers,
        )

    def list_adherence_measurements(
        self, order_set_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/cds/order-sets/{order_set_id}/adherence-measurements",
            headers=headers,
            params=params,
        )

    def finalize_adherence_measurement(
        self, measurement_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/adherence-measurements/{measurement_id}/finalize", payload, headers
        )

    # ------------------------------------------------------------------
    # Annual review tasks and operational control
    # ------------------------------------------------------------------
    def list_annual_review_tasks(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", "/cds/annual-review-tasks", headers=headers, params=params
        )

    def get_annual_review_task(self, task_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/cds/annual-review-tasks/{task_id}", headers=headers)

    def attest_annual_review_task(
        self, task_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/cds/annual-review-tasks/{task_id}/attest", payload, headers
        )

    def run_expiration_sweep(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/cds/_ops/run-expiration-sweep", payload, headers)

    def ingest_alert_firings(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/alert-firings", payload, headers)

    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
