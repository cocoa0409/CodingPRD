"""API client — one method per endpoint declared in PRD §4.

Subclass of GenericApiClient; the base _request() method handles HTTP
plumbing. Tests pass headers explicitly because PRD §2.1 requires both
X-User-ID and X-User-Role on every request.

Path prefixes per PRD §1: /customers, /transit-centers, /drivers,
/parcels, /routes, /appointments, /_clock.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Customers — PRD §3.1, §4
    # =======================================================================
    def create_customer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/customers/{customer_id}", headers=headers,
        )

    def patch_customer(self, customer_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/customers/{customer_id}", payload, headers,
        )

    def create_address(self, customer_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/customers/{customer_id}/addresses",
            payload, headers,
        )

    # =======================================================================
    # Transit centers — PRD §3.2, §4
    # =======================================================================
    def create_transit_center(self, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", "/transit-centers", payload, headers,
        )

    def get_transit_center(self, center_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET", f"/transit-centers/{center_id}", headers=headers,
        )

    # =======================================================================
    # Drivers — PRD §3.2, §4
    # =======================================================================
    def create_driver(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/drivers", payload, headers)

    def driver_check_in(self, driver_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/drivers/{driver_id}/check-in", None, headers,
        )

    def driver_check_out(self, driver_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/drivers/{driver_id}/check-out", None, headers,
        )

    # =======================================================================
    # Parcels — PRD §3.3, §3.5, §4
    # =======================================================================
    def create_parcel(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/parcels", payload, headers)

    def get_parcel(self, parcel_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/parcels/{parcel_id}", headers=headers,
        )

    def list_parcels(self, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/parcels", headers=headers, params=params,
        )

    def patch_parcel(self, parcel_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/parcels/{parcel_id}", payload, headers,
        )

    def induct_parcel_to_hub(self, parcel_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/induct-to-hub", None, headers,
        )

    def sort_parcel(self, parcel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/sort", None, headers,
        )

    def create_attempt(self, parcel_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/attempts", payload, headers,
        )

    def reattempt_parcel(self, parcel_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/reattempt", None, headers,
        )

    def return_to_sender(self, parcel_id: str,
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/return-to-sender",
            None, headers,
        )

    # =======================================================================
    # Routes — PRD §3.4, §4
    # =======================================================================
    def create_route(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/routes/{route_id}", headers=headers,
        )

    def create_stop(self, route_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/routes/{route_id}/stops", payload, headers,
        )

    def delete_stop(self, route_id: str, stop_id: str,
                    headers: Dict[str, str]):
        return self._request(
            "DELETE", f"/routes/{route_id}/stops/{stop_id}",
            headers=headers,
        )

    def dispatch_route(self, route_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/routes/{route_id}/dispatch", None, headers,
        )

    def close_route(self, route_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/routes/{route_id}/close", None, headers,
        )

    def cancel_route(self, route_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/routes/{route_id}/cancel", None, headers,
        )

    # =======================================================================
    # Appointments — PRD §3.5, §4
    # =======================================================================
    def create_appointment(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", "/appointments", payload, headers,
        )

    def accept_appointment(self, appointment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/appointments/{appointment_id}/accept",
            None, headers,
        )

    def reject_appointment(self, appointment_id: str,
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/appointments/{appointment_id}/reject",
            None, headers,
        )

    # =======================================================================
    # Test-only logical clock — PRD §2.11, §4
    # =======================================================================
    def advance_clock(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", payload, headers,
        )


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
