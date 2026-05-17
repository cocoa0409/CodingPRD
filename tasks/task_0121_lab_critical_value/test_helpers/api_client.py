"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the inherited _request() handles the HTTP
plumbing. Headers are passed explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request (the test-driving endpoints
under /_clock and /_sweep still demand a LabDirector caller per PRD §4).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Patients — PRD §3.1 / §4.
    # =======================================================================
    def create_patient(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/patients/{patient_id}", headers=headers,
        )

    def list_patients(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/patients", headers=headers, params=params,
        )

    # =======================================================================
    # Clinicians — PRD §3.1 / §4.
    # =======================================================================
    def create_clinician(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/clinicians", payload, headers)

    def patch_clinician(self, clinician_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/clinicians/{clinician_id}", payload, headers,
        )

    def get_clinician(self, clinician_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/clinicians/{clinician_id}", headers=headers,
        )

    # =======================================================================
    # Test panels — PRD §3.1 / §4.
    # =======================================================================
    def create_test_panel(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/test-panels", payload, headers)

    def get_test_panel(self, panel_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/test-panels/{panel_id}", headers=headers,
        )

    # =======================================================================
    # Lab orders — PRD §3.2 / §4.
    # =======================================================================
    def create_lab_order(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/lab-orders", payload, headers)

    def get_lab_order(self, order_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/lab-orders/{order_id}", headers=headers,
        )

    def list_lab_orders(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/lab-orders", headers=headers, params=params,
        )

    def cancel_lab_order(self, order_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/lab-orders/{order_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Specimens & transport — PRD §3.3 / §4.
    # =======================================================================
    def create_specimen(self, order_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/lab-orders/{order_id}/specimens", payload, headers,
        )

    def get_specimen(self, specimen_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/specimens/{specimen_id}", headers=headers,
        )

    def create_transport_leg(self, specimen_id: str,
                             payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/specimens/{specimen_id}/transport-legs",
            payload, headers,
        )

    def list_transport_legs(self, specimen_id: str,
                            headers: Dict[str, str],
                            params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/specimens/{specimen_id}/transport-legs",
            headers=headers, params=params,
        )

    def arrive_transport_leg(self, leg_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/transport-legs/{leg_id}/arrive", payload, headers,
        )

    def report_break_transport_leg(self, leg_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transport-legs/{leg_id}/report-break",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Results — PRD §3.4 / §4.
    # =======================================================================
    def create_result(self, order_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/lab-orders/{order_id}/results", payload, headers,
        )

    def get_result(self, result_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/results/{result_id}", headers=headers,
        )

    def release_result(self, result_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/results/{result_id}/release", payload, headers,
        )

    def amend_result(self, result_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/results/{result_id}/amend", payload, headers,
        )

    def retract_result(self, result_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/results/{result_id}/retract",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Critical notifications — PRD §3.5 / §4.
    # =======================================================================
    def get_notification(self, notification_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET", f"/notifications/{notification_id}", headers=headers,
        )

    def list_notifications(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/notifications", headers=headers, params=params,
        )

    def acknowledge_notification(self, notification_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/notifications/{notification_id}/acknowledge",
            payload, headers,
        )

    # =======================================================================
    # Retest requests — PRD §3.7 / §4.
    # =======================================================================
    def get_retest_request(self, retest_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/retest-requests/{retest_id}", headers=headers,
        )

    def list_retest_requests(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/retest-requests", headers=headers, params=params,
        )

    def cancel_retest_request(self, retest_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/retest-requests/{retest_id}/cancel",
            payload if payload is not None else {}, headers,
        )

    # =======================================================================
    # Audit events — PRD §3.8 / §4.
    # =======================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-events", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving — clock + sweep. PRD §3.8 / §4 require LabDirector.
    # =======================================================================
    def clock_advance(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def get_clock(self, headers: Dict[str, str]):
        return self._request("GET", "/_clock", headers=headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run",
            payload if payload is not None else {}, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
