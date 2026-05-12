"""API client: one method per endpoint defined in the PRD.

Every method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID / X-User-Role on every call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # =====================================================================
    # Test-harness endpoints (PRD §3.5, §4)
    # =====================================================================
    def advance_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", payload, headers)

    def run_sweep(self, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", "/_sweep/run", payload or {}, headers)

    def courier_inbound_handshake(self, payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request("POST", "/_events/courier/inbound", payload, headers)

    # =====================================================================
    # Station (PRD §3.1, §4)
    # =====================================================================
    def create_station(self, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request("POST", "/stations", payload, headers)

    def list_stations(self, headers: Dict[str, str],
                      params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/stations", headers=headers, params=params)

    def get_station(self, station_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/stations/{station_id}", headers=headers)

    def patch_station(self, station_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/stations/{station_id}", payload, headers
        )

    # =====================================================================
    # ShelfZone (PRD §3.1, §4)
    # =====================================================================
    def create_shelf_zone(self, station_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/stations/{station_id}/shelf-zones", payload, headers
        )

    def list_shelf_zones(self, station_id: str, headers: Dict[str, str],
                         params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/stations/{station_id}/shelf-zones",
            headers=headers, params=params,
        )

    # =====================================================================
    # Staff (PRD §3.1, §4)
    # =====================================================================
    def create_staff(self, station_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/stations/{station_id}/staff", payload, headers
        )

    def patch_staff(self, staff_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/staff/{staff_id}", payload, headers
        )

    # =====================================================================
    # Parcels (PRD §3.2, §3.6, §3.7, §4)
    # =====================================================================
    def register_parcel(self, station_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/stations/{station_id}/parcels", payload, headers
        )

    def list_parcels(self, station_id: str, headers: Dict[str, str],
                     params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/stations/{station_id}/parcels",
            headers=headers, params=params,
        )

    def get_parcel(self, parcel_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/parcels/{parcel_id}", headers=headers)

    def reassign_shelf(self, parcel_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/parcels/{parcel_id}/shelf", payload, headers
        )

    def pickup_parcel(self, parcel_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/pickup", payload, headers
        )

    def dispose_parcel(self, parcel_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/dispose", payload or {}, headers
        )

    # =====================================================================
    # Pickup Codes (PRD §3.3, §4)
    # =====================================================================
    def reissue_pickup_code(self, parcel_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/pickup-codes", payload, headers
        )

    def list_pickup_codes(self, parcel_id: str, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parcels/{parcel_id}/pickup-codes",
            headers=headers, params=params,
        )

    # =====================================================================
    # Pickup Authorizations (PRD §3.4, §4)
    # =====================================================================
    def create_authorization(self, parcel_id: str, payload: Dict[str, Any],
                             headers: Dict[str, str]):
        return self._request(
            "POST", f"/parcels/{parcel_id}/authorizations", payload, headers
        )

    def patch_authorization(self, authorization_id: str, payload: Dict[str, Any],
                            headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/authorizations/{authorization_id}", payload, headers
        )

    # =====================================================================
    # Reminders (PRD §3.5, §4)
    # =====================================================================
    def list_reminders(self, parcel_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/parcels/{parcel_id}/reminders",
            headers=headers, params=params,
        )

    # =====================================================================
    # Returns (PRD §3.7, §4)
    # =====================================================================
    def request_return_shipment(self, parcel_id: str, headers: Dict[str, str],
                                payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/parcels/{parcel_id}/return-shipments",
            payload or {}, headers,
        )

    def courier_response(self, return_shipment_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/return-shipments/{return_shipment_id}/courier-response",
            payload, headers,
        )

    def ship_return(self, return_shipment_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/return-shipments/{return_shipment_id}/ship",
            payload, headers,
        )

    # =====================================================================
    # Billing Periods + Bills (PRD §3.9, §4)
    # =====================================================================
    def create_billing_period(self, station_id: str, payload: Dict[str, Any],
                              headers: Dict[str, str]):
        return self._request(
            "POST", f"/stations/{station_id}/billing-periods", payload, headers
        )

    def close_billing_period(self, station_id: str, period_yyyymm: str,
                             headers: Dict[str, str],
                             payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/stations/{station_id}/billing-periods/{period_yyyymm}/close",
            payload or {}, headers,
        )

    def get_billing_period(self, station_id: str, period_yyyymm: str,
                           headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/stations/{station_id}/billing-periods/{period_yyyymm}",
            headers=headers,
        )

    def list_bills(self, billing_period_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/billing-periods/{billing_period_id}/bills",
            headers=headers, params=params,
        )

    def get_bill(self, bill_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bills/{bill_id}", headers=headers)

    def pay_bill(self, bill_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/bills/{bill_id}/payments", payload, headers
        )

    def dispute_bill(self, bill_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/bills/{bill_id}/dispute", payload, headers
        )

    def resolve_dispute(self, bill_id: str, headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/bills/{bill_id}/resolve-dispute",
            payload or {}, headers,
        )

    def write_off_bill(self, bill_id: str, headers: Dict[str, str],
                       payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/bills/{bill_id}/write-off", payload or {}, headers
        )

    # =====================================================================
    # Quality Assessments (PRD §3.10, §4)
    # =====================================================================
    def create_quality_assessment(self, station_id: str,
                                  payload: Dict[str, Any],
                                  headers: Dict[str, str]):
        return self._request(
            "POST", f"/stations/{station_id}/quality-assessments",
            payload, headers,
        )

    def close_quality_assessment(self, station_id: str, period_yyyymm: str,
                                 headers: Dict[str, str],
                                 payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST",
            f"/stations/{station_id}/quality-assessments/{period_yyyymm}/close",
            payload or {}, headers,
        )

    def get_quality_assessment(self, station_id: str, period_yyyymm: str,
                               headers: Dict[str, str]):
        return self._request(
            "GET",
            f"/stations/{station_id}/quality-assessments/{period_yyyymm}",
            headers=headers,
        )

    # =====================================================================
    # Audit + Outbox (PRD §3.11, §4)
    # =====================================================================
    def list_audit_events(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-events", headers=headers, params=params
        )

    def list_system_events(self, headers: Dict[str, str],
                           params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/system-events", headers=headers, params=params
        )


api_client = ApiClient()


__all__ = ["api_client", "ApiClient"]
