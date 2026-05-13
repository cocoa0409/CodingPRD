"""Live Stream Schedule API client — one method per endpoint defined in the PRD.

All endpoints are mounted under ``/live-schedule`` (the prefix is baked into every
method here). The base ``_request`` is inherited from ``GenericApiClient``.
"""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Streamers
    # ------------------------------------------------------------------
    def create_streamer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/streamers", payload, headers)

    def get_streamer(self, streamer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/live-schedule/streamers/{streamer_id}", headers=headers)

    def list_streamers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/live-schedule/streamers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Studios
    # ------------------------------------------------------------------
    def create_studio(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/studios", payload, headers)

    def update_studio(self, studio_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/live-schedule/studios/{studio_id}", payload, headers)

    def create_time_slot(self, studio_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/live-schedule/studios/{studio_id}/time-slots", payload, headers)

    def list_time_slots(self, studio_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/live-schedule/studios/{studio_id}/time-slots", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/products", payload, headers)

    def update_product(self, product_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/live-schedule/products/{product_id}", payload, headers)

    # ------------------------------------------------------------------
    # Applications (CRUD & list)
    # ------------------------------------------------------------------
    def create_application(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/applications", payload, headers)

    def get_application(self, application_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/live-schedule/applications/{application_id}", headers=headers)

    def list_applications(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/live-schedule/applications", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Applications — product associations
    # ------------------------------------------------------------------
    def associate_product(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/products",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Applications — workflow actions
    # ------------------------------------------------------------------
    def submit_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/submit",
            headers=headers,
        )

    def ops_approve(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/ops-approve",
            payload,
            headers,
        )

    def compliance_approve(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/compliance-approve",
            payload,
            headers,
        )

    def withdraw_application(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/withdraw",
            headers=headers,
        )

    def start_live(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/start-live",
            headers=headers,
        )

    def end_live(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/end-live",
            headers=headers,
        )

    def cancel_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/cancel",
            payload,
            headers,
        )

    def force_cancel_application(self, application_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/applications/{application_id}/force-cancel",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Applications — child collections
    # ------------------------------------------------------------------
    def list_approvals(self, application_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request(
            "GET",
            f"/live-schedule/applications/{application_id}/approvals",
            headers=headers,
            params=params,
        )

    def get_invoice(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/live-schedule/applications/{application_id}/invoice",
            headers=headers,
        )

    def get_settlement(self, application_id: str, headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/live-schedule/applications/{application_id}/settlement",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Settlement payout
    # ------------------------------------------------------------------
    def payout_settlement(self, settlement_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/settlements/{settlement_id}/payout",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Violations & appeals
    # ------------------------------------------------------------------
    def create_violation(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/violations", payload, headers)

    def list_violations(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/live-schedule/violations", headers=headers, params=params)

    def file_appeal(self, violation_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/violations/{violation_id}/appeal",
            payload,
            headers,
        )

    def decide_appeal(self, appeal_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/live-schedule/appeals/{appeal_id}/decide",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------
    def list_audit_logs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/live-schedule/audit-logs", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Test-driving endpoints (clock, sweep, events)
    # ------------------------------------------------------------------
    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/live-schedule/_clock/now", headers=headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/_sweep/run", headers=headers)

    def emit_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-schedule/_events/emit", payload, headers)


api_client = ApiClient()
