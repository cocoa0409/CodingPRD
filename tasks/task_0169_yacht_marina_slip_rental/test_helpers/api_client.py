"""API client: one method per endpoint defined in the PRD.

Subclass of GenericApiClient — the base `_request()` handles HTTP
plumbing. All endpoints are mounted under `/marinas` per PRD §4.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ======================================================================
    # Marina — PRD §3.1
    # ======================================================================
    def create_marina(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/marinas", payload, headers)

    def get_marina(self, marina_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/marinas/{marina_id}", headers=headers,
        )

    def clock_advance(self, marina_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/marinas/{marina_id}/_clock/advance",
            payload, headers,
        )

    def ops_run(self, marina_id: str,
                headers: Dict[str, str],
                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/marinas/{marina_id}/_ops/run",
            payload, headers,
        )

    # ======================================================================
    # Boater — PRD §3.2
    # ======================================================================
    def create_boater(self, marina_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/marinas/{marina_id}/boaters", payload, headers,
        )

    def get_boater(self, marina_id: str, boater_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/marinas/{marina_id}/boaters/{boater_id}",
            headers=headers,
        )

    # ======================================================================
    # Vessel — PRD §3.2
    # ======================================================================
    def create_vessel(self, marina_id: str, boater_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/boaters/{boater_id}/vessels",
            payload, headers,
        )

    def get_vessel(self, marina_id: str, vessel_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/marinas/{marina_id}/vessels/{vessel_id}",
            headers=headers,
        )

    # ======================================================================
    # Slip — PRD §3.3
    # ======================================================================
    def create_slip(self, marina_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/marinas/{marina_id}/slips", payload, headers,
        )

    def get_slip(self, marina_id: str, slip_id: str,
                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/marinas/{marina_id}/slips/{slip_id}",
            headers=headers,
        )

    def patch_slip_status(self, marina_id: str, slip_id: str,
                          payload: Dict[str, Any],
                          headers: Dict[str, str]):
        """PRD §3.3: PATCH slip status; If-Match header carries the
        slip's current version."""
        return self._request(
            "PATCH", f"/marinas/{marina_id}/slips/{slip_id}/status",
            payload, headers,
        )

    # ======================================================================
    # Reservation — PRD §3.4, §3.5
    # ======================================================================
    def create_reservation(self, marina_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/marinas/{marina_id}/reservations", payload, headers,
        )

    def get_reservation(self, marina_id: str, reservation_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/marinas/{marina_id}/reservations/{reservation_id}",
            headers=headers,
        )

    def list_reservations(self, marina_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/marinas/{marina_id}/reservations",
            headers=headers, params=params,
        )

    def approve_reservation(self, marina_id: str, reservation_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/reservations/{reservation_id}/approve",
            payload, headers,
        )

    def check_in_reservation(self, marina_id: str, reservation_id: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/reservations/{reservation_id}/check-in",
            payload, headers,
        )

    def check_out_reservation(self, marina_id: str, reservation_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/reservations/{reservation_id}/check-out",
            payload, headers,
        )

    def cancel_reservation(self, marina_id: str, reservation_id: str,
                           headers: Dict[str, str],
                           payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/reservations/{reservation_id}/cancel",
            payload, headers,
        )

    # ======================================================================
    # Waitlist — PRD §3.7
    # ======================================================================
    def create_waitlist_entry(self, marina_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/marinas/{marina_id}/waitlist", payload, headers,
        )

    def get_waitlist_entry(self, marina_id: str, waitlist_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/marinas/{marina_id}/waitlist/{waitlist_id}",
            headers=headers,
        )

    def cancel_waitlist_entry(self, marina_id: str, waitlist_id: str,
                              headers: Dict[str, str],
                              payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/waitlist/{waitlist_id}/cancel",
            payload, headers,
        )

    # ======================================================================
    # Slip Transfer Request — PRD §3.7
    # ======================================================================
    def create_transfer_request(self, marina_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST", f"/marinas/{marina_id}/transfer-requests",
            payload, headers,
        )

    def offer_transfer_request(self, marina_id: str, request_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/transfer-requests/{request_id}/offer",
            payload, headers,
        )

    def accept_transfer_request(self, marina_id: str, request_id: str,
                                headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/transfer-requests/{request_id}/accept",
            payload, headers,
        )

    def decline_transfer_request(self, marina_id: str, request_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/transfer-requests/{request_id}/decline",
            payload, headers,
        )

    def requeue_transfer_request(self, marina_id: str, request_id: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/transfer-requests/{request_id}/requeue",
            payload, headers,
        )

    # ======================================================================
    # Pump-out — PRD §3.8
    # ======================================================================
    def create_pump_out_job(self, marina_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/marinas/{marina_id}/pump-out-jobs",
            payload, headers,
        )

    def complete_pump_out_job(self, marina_id: str, job_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/pump-out-jobs/{job_id}/complete",
            payload, headers,
        )

    def cancel_pump_out_job(self, marina_id: str, job_id: str,
                            headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/pump-out-jobs/{job_id}/cancel",
            payload, headers,
        )

    # ======================================================================
    # Utility readings / settlement — PRD §3.6
    # ======================================================================
    def create_utility_reading(self, marina_id: str,
                               reservation_id: str,
                               payload: Dict[str, Any],
                               headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/marinas/{marina_id}/reservations/{reservation_id}"
             "/utility-readings"),
            payload, headers,
        )

    def get_utility_settlement(self, marina_id: str,
                               reservation_id: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET",
            (f"/marinas/{marina_id}/reservations/{reservation_id}"
             "/utility-settlement"),
            headers=headers,
        )

    # ======================================================================
    # Insurance — PRD §3.2
    # ======================================================================
    def create_policy(self, marina_id: str, boater_id: str,
                      payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/boaters/{boater_id}/policies",
            payload, headers,
        )

    def get_policy(self, marina_id: str, policy_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "GET", f"/marinas/{marina_id}/policies/{policy_id}",
            headers=headers,
        )

    def cancel_policy(self, marina_id: str, policy_id: str,
                      headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/policies/{policy_id}/cancel",
            payload, headers,
        )

    # ======================================================================
    # Tow Assist — PRD §3.2, §3.8
    # ======================================================================
    def create_tow_contract(self, marina_id: str, boater_id: str,
                            payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/marinas/{marina_id}/boaters/{boater_id}/tow-contracts",
            payload, headers,
        )

    def get_tow_contract(self, marina_id: str, contract_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/marinas/{marina_id}/tow-contracts/{contract_id}",
            headers=headers,
        )

    def create_tow_event(self, marina_id: str, contract_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            (f"/marinas/{marina_id}/tow-contracts/{contract_id}"
             "/tow-events"),
            payload, headers,
        )


# Module-level singleton used by tests + fixtures.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
