"""API client: one method per endpoint defined in PRD §4.

Subclass of GenericApiClient — the base _request() method handles
HTTP plumbing. Tests pass headers explicitly because PRD §2.1
requires X-User-ID and X-User-Role on every request.

PRD §1: "The API is mounted under the prefix /vehicles and its sibling
top-level resource paths (/owners, /transfer-applications,
/emissions-inspections, /titles, /lien-records, /real-id-applications,
/plates, /transfer-applications/{id}/fee-ledger, and an admin-only
/_clock/advance)."
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Vehicles — PRD §3.2, §3.3, §4
    # =======================================================================
    def create_vehicle(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/vehicles/{vehicle_id}", headers=headers,
        )

    def list_vehicles(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/vehicles", headers=headers, params=params,
        )

    def post_salvage_event(self, vehicle_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/salvage-event",
            payload, headers,
        )

    # =======================================================================
    # Owners — PRD §3.1, §4
    # =======================================================================
    def create_owner(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/owners/{owner_id}", headers=headers,
        )

    # =======================================================================
    # REAL ID — PRD §3.10, §4
    # =======================================================================
    def create_real_id_application(self, owner_id: str,
                                   payload: Dict[str, Any],
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/owners/{owner_id}/real-id-applications",
            payload, headers,
        )

    def start_review_real_id(self, app_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/real-id-applications/{app_id}/start-review",
            None, headers,
        )

    def approve_real_id(self, app_id: str,
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/real-id-applications/{app_id}/approve",
            None, headers,
        )

    def reject_real_id(self, app_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/real-id-applications/{app_id}/reject",
            None, headers,
        )

    def resubmit_real_id(self, app_id: str,
                         payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/real-id-applications/{app_id}/resubmit",
            payload, headers,
        )

    def revoke_real_id(self, app_id: str,
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/real-id-applications/{app_id}/revoke",
            None, headers,
        )

    # =======================================================================
    # Transfer applications — PRD §3.4, §4
    # =======================================================================
    def create_transfer_application(self, vehicle_id: str,
                                    payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/transfer-applications",
            payload, headers,
        )

    def get_transfer_application(self, app_id: str,
                                 headers: Dict[str, str]):
        return self._request(
            "GET", f"/transfer-applications/{app_id}", headers=headers,
        )

    def list_transfer_applications(self, headers: Dict[str, str],
                                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/transfer-applications",
            headers=headers, params=params,
        )

    def verify_vin(self, vehicle_id: str, app_id: str,
                   headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/vehicles/{vehicle_id}/transfer-applications/{app_id}/verify-vin",
            None, headers,
        )

    def approve_salvage(self, app_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/transfer-applications/{app_id}/approve-salvage",
            payload, headers,
        )

    def assess_fees(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-applications/{app_id}/assess-fees",
            None, headers,
        )

    def mark_paid(self, app_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-applications/{app_id}/mark-paid",
            None, headers,
        )

    def issue_plate(self, app_id: str,
                    payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-applications/{app_id}/issue-plate",
            payload, headers,
        )

    def withdraw_application(self, app_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/transfer-applications/{app_id}/withdraw",
            None, headers,
        )

    def list_fee_ledger(self, app_id: str,
                        headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/transfer-applications/{app_id}/fee-ledger",
            headers=headers, params=params,
        )

    # =======================================================================
    # Emissions inspections — PRD §3.5, §4
    # =======================================================================
    def create_emissions_inspection(self, payload: Dict[str, Any],
                                    headers: Dict[str, str]):
        return self._request(
            "POST", "/emissions-inspections", payload, headers,
        )

    def start_emissions_inspection(self, inspection_id: str,
                                   headers: Dict[str, str]):
        return self._request(
            "POST", f"/emissions-inspections/{inspection_id}/start",
            None, headers,
        )

    def record_emissions_result(self, inspection_id: str,
                                payload: Dict[str, Any],
                                headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/emissions-inspections/{inspection_id}/record-result",
            payload, headers,
        )

    def cancel_emissions_inspection(self, inspection_id: str,
                                    headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/emissions-inspections/{inspection_id}",
            headers=headers,
        )

    # =======================================================================
    # Lien records — PRD §3.6, §4
    # =======================================================================
    def create_lien_record(self, title_id: str,
                           payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/titles/{title_id}/lien-records", payload, headers,
        )

    def release_lien(self, lien_id: str,
                     payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/lien-records/{lien_id}/release",
            payload, headers,
        )

    # =======================================================================
    # Plates — PRD §3.9, §4
    # =======================================================================
    def get_plate(self, plate_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/plates/{plate_id}", headers=headers,
        )

    def suspend_plate(self, plate_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/plates/{plate_id}/suspend", None, headers,
        )

    def reinstate_plate(self, plate_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/plates/{plate_id}/reinstate", None, headers,
        )

    def surrender_plate(self, plate_id: str,
                        payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/plates/{plate_id}/surrender", payload, headers,
        )

    # =======================================================================
    # Logical clock — PRD §3.8, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
