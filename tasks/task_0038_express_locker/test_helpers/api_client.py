"""API client: one method per endpoint defined in PRD §4.

Every method delegates to GenericApiClient._request and returns the raw
Response object so tests assert status codes against the framework
validators directly.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # LockerMachine (PRD §3.1, §4)
    # =====================================================================
    def create_locker_machine(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request("POST", "/locker-machines", payload, headers)

    def list_locker_machines(self, headers: Dict[str, str],
                             params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/locker-machines", headers=headers, params=params,
        )

    def get_locker_machine(self, machine_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/locker-machines/{machine_id}", headers=headers,
        )

    def heartbeat_locker_machine(self, machine_id: str,
                                 payload: Dict[str, Any],
                                 headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/locker-machines/{machine_id}/heartbeat",
            payload, headers,
        )

    def offline_locker_machine(self, machine_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/locker-machines/{machine_id}/offline",
            payload or {}, headers,
        )

    def list_machine_audit_logs(self, machine_id: str,
                                headers: Dict[str, str],
                                params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/locker-machines/{machine_id}/audit-logs",
            headers=headers, params=params,
        )

    # =====================================================================
    # Compartment (PRD §3.1, §4)
    # =====================================================================
    def create_compartment(self, machine_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/locker-machines/{machine_id}/compartments",
            payload, headers,
        )

    def list_compartments(self, machine_id: str,
                          headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET",
            f"/locker-machines/{machine_id}/compartments",
            headers=headers, params=params,
        )

    def get_compartment(self, machine_id: str, compartment_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/locker-machines/{machine_id}/compartments/{compartment_id}",
            headers=headers,
        )

    def out_of_service_compartment(self, machine_id: str,
                                   compartment_id: str,
                                   headers: Dict[str, str],
                                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/locker-machines/{machine_id}/compartments/"
            f"{compartment_id}/out-of-service",
            payload or {}, headers,
        )

    def in_service_compartment(self, machine_id: str,
                               compartment_id: str,
                               headers: Dict[str, str],
                               payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/locker-machines/{machine_id}/compartments/"
            f"{compartment_id}/in-service",
            payload or {}, headers,
        )

    # =====================================================================
    # Courier (PRD §3.10, §4)
    # =====================================================================
    def create_courier(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/couriers", payload, headers)

    def get_courier(self, courier_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/couriers/{courier_id}", headers=headers,
        )

    def get_courier_rating(self, courier_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/couriers/{courier_id}/rating", headers=headers,
        )

    def restrict_courier(self, courier_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/couriers/{courier_id}/restrict", payload, headers,
        )

    def blacklist_courier(self, courier_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/couriers/{courier_id}/blacklist", payload, headers,
        )

    def reinstate_courier(self, courier_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/couriers/{courier_id}/reinstate",
            payload or {}, headers,
        )

    # =====================================================================
    # Parcel — deposit + pickup workflow (PRD §3.3, §3.4, §3.6, §3.7, §4)
    # =====================================================================
    def create_parcel(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/parcels", payload, headers)

    def list_parcels(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/parcels", headers=headers, params=params,
        )

    def get_parcel(self, parcel_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/parcels/{parcel_id}", headers=headers,
        )

    def list_parcel_fees(self, parcel_id: str,
                         headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parcels/{parcel_id}/fees",
            headers=headers, params=params,
        )

    def confirm_deposit(self, parcel_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/confirm-deposit",
            payload or {}, headers,
        )

    def cancel_deposit(self, parcel_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/cancel-deposit",
            payload or {}, headers,
        )

    def retry_open(self, parcel_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/retry-open",
            payload or {}, headers,
        )

    def correct_wrong_deposit(self, parcel_id: str,
                              payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/correct-wrong-deposit",
            payload, headers,
        )

    def initiate_pickup(self, parcel_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/initiate-pickup",
            payload, headers,
        )

    def pickup_confirm(self, parcel_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/pickup-confirm",
            payload or {}, headers,
        )

    def cancel_pickup(self, parcel_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/cancel-pickup",
            payload or {}, headers,
        )

    def recall_parcel(self, parcel_id: str, headers: Dict[str, str],
                      payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/recall",
            payload or {}, headers,
        )

    def return_to_sender(self, parcel_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/return-to-sender",
            payload or {}, headers,
        )

    def dispose_parcel(self, parcel_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/dispose", payload, headers,
        )

    def waive_fee(self, parcel_id: str, payload: Dict[str, Any],
                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/waive-fee", payload, headers,
        )

    # =====================================================================
    # Disputes (PRD §3.9, §4)
    # =====================================================================
    def open_dispute(self, parcel_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/disputes", payload, headers,
        )

    def resolve_dispute(self, dispute_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/disputes/{dispute_id}/resolve", payload, headers,
        )

    # =====================================================================
    # Settlements (PRD §3.11, §4)
    # =====================================================================
    def create_settlement(self, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request("POST", "/settlements", payload, headers)

    def list_settlements(self, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/settlements", headers=headers, params=params,
        )

    def get_settlement(self, batch_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/settlements/{batch_id}", headers=headers,
        )

    def lock_settlement(self, batch_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/settlements/{batch_id}/lock",
            payload or {}, headers,
        )

    def settle_settlement(self, batch_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/settlements/{batch_id}/settle",
            payload or {}, headers,
        )

    # =====================================================================
    # Test-driving / sync infrastructure (PRD §3.12, §4)
    # =====================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", "/_sweep/run", payload or {}, headers,
        )

    def emit_event(self, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request("POST", "/events/emit", payload, headers)


# Module-level singleton for tests to import via the barrel.
api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
