"""API client: one method per endpoint defined in PRD §4.

Each method delegates to GenericApiClient._request and returns the raw
Response object. Tests pass headers explicitly because PRD §2.1 requires
X-User-ID and X-User-Role on every call.
"""
from __future__ import annotations
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # =======================================================================
    # Regions
    # =======================================================================
    def create_region(self, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request("POST", "/regions", payload, headers)

    def get_region(self, region_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/regions/{region_id}", headers=headers,
        )

    def patch_region(self, region_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/regions/{region_id}", payload, headers,
        )

    def get_region_loss_rate(self, region_id: str,
                             headers: Dict[str, str]):
        return self._request(
            "GET", f"/regions/{region_id}/loss-rate", headers=headers,
        )

    # =======================================================================
    # Geofences
    # =======================================================================
    def create_geofence(self, region_id: str, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request(
            "POST", f"/regions/{region_id}/geofences", payload, headers,
        )

    def patch_geofence(self, geofence_id: str, payload: Dict[str, Any],
                       headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/geofences/{geofence_id}", payload, headers,
        )

    def list_geofences(self, region_id: str, headers: Dict[str, str],
                       params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/regions/{region_id}/geofences",
            headers=headers, params=params,
        )

    # =======================================================================
    # Bikes
    # =======================================================================
    def create_bike(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/bikes", payload, headers)

    def get_bike(self, bike_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/bikes/{bike_id}", headers=headers,
        )

    def patch_bike(self, bike_id: str, payload: Dict[str, Any],
                   headers: Dict[str, str]):
        return self._request(
            "PATCH", f"/bikes/{bike_id}", payload, headers,
        )

    def shelf_bike(self, region_id: str, bike_id: str,
                   payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/regions/{region_id}/bikes/{bike_id}/shelf",
            payload, headers,
        )

    def recall_bike(self, bike_id: str, headers: Dict[str, str],
                    payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/bikes/{bike_id}/recall",
            payload or {}, headers,
        )

    def release_recall_bike(self, bike_id: str, headers: Dict[str, str],
                            payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/bikes/{bike_id}/release-recall",
            payload or {}, headers,
        )

    def fault_report_bike(self, bike_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/bikes/{bike_id}/fault-report", payload, headers,
        )

    def scrap_bike(self, bike_id: str, headers: Dict[str, str],
                   payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/bikes/{bike_id}/scrap",
            payload or {}, headers,
        )

    def list_bikes(self, region_id: str, headers: Dict[str, str],
                   params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", f"/regions/{region_id}/bikes",
            headers=headers, params=params,
        )

    # =======================================================================
    # Riders
    # =======================================================================
    def create_rider(self, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/riders/{rider_id}", headers=headers,
        )

    def credit_wallet(self, rider_id: str, payload: Dict[str, Any],
                      headers: Dict[str, str]):
        return self._request(
            "POST", f"/riders/{rider_id}/wallet/credit", payload, headers,
        )

    def buy_monthly_pass(self, rider_id: str, headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/riders/{rider_id}/monthly-pass",
            payload or {}, headers,
        )

    def grant_free_minutes(self, rider_id: str, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request(
            "POST", f"/riders/{rider_id}/free-minutes/grant",
            payload, headers,
        )

    # =======================================================================
    # Rides
    # =======================================================================
    def create_ride(self, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request("POST", "/rides", payload, headers)

    def get_ride(self, ride_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/rides/{ride_id}", headers=headers,
        )

    def end_ride(self, ride_id: str, payload: Dict[str, Any],
                 headers: Dict[str, str]):
        return self._request(
            "POST", f"/rides/{ride_id}/end", payload, headers,
        )

    def fault_report_ride(self, ride_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/rides/{ride_id}/fault-report", payload, headers,
        )

    def dispute_ride(self, ride_id: str, payload: Dict[str, Any],
                     headers: Dict[str, str]):
        return self._request(
            "POST", f"/rides/{ride_id}/dispute", payload, headers,
        )

    def adjust_ride(self, ride_id: str, payload: Dict[str, Any],
                    headers: Dict[str, str]):
        return self._request(
            "POST", f"/rides/{ride_id}/adjust", payload, headers,
        )

    def void_ride(self, ride_id: str, headers: Dict[str, str],
                  payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/rides/{ride_id}/void", payload or {}, headers,
        )

    # =======================================================================
    # Work Orders
    # =======================================================================
    def create_workorder(self, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request("POST", "/workorders", payload, headers)

    def assign_workorder(self, workorder_id: str, payload: Dict[str, Any],
                         headers: Dict[str, str]):
        return self._request(
            "POST", f"/workorders/{workorder_id}/assign", payload, headers,
        )

    def resolve_workorder(self, workorder_id: str, payload: Dict[str, Any],
                          headers: Dict[str, str]):
        return self._request(
            "POST", f"/workorders/{workorder_id}/resolve", payload, headers,
        )

    def cancel_workorder(self, workorder_id: str,
                         headers: Dict[str, str],
                         payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/workorders/{workorder_id}/cancel",
            payload or {}, headers,
        )

    def list_workorders(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/workorders", headers=headers, params=params,
        )

    def get_workorder(self, workorder_id: str, headers: Dict[str, str]):
        # PRD §4 does not enumerate a GET /workorders/{id} singleton; tests
        # discover work orders via the list endpoint with a tight filter.
        return self._request(
            "GET", f"/workorders/{workorder_id}", headers=headers,
        )

    # =======================================================================
    # Transfers
    # =======================================================================
    def create_transfer(self, payload: Dict[str, Any],
                        headers: Dict[str, str]):
        return self._request("POST", "/transfers", payload, headers)

    def dispatch_transfer(self, transfer_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transfers/{transfer_id}/dispatch",
            payload or {}, headers,
        )

    def complete_transfer(self, transfer_id: str,
                          headers: Dict[str, str],
                          payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transfers/{transfer_id}/complete",
            payload or {}, headers,
        )

    def cancel_transfer(self, transfer_id: str,
                        headers: Dict[str, str],
                        payload: Optional[Dict[str, Any]] = None):
        return self._request(
            "POST", f"/transfers/{transfer_id}/cancel",
            payload or {}, headers,
        )

    def get_transfer(self, transfer_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/transfers/{transfer_id}", headers=headers,
        )

    # =======================================================================
    # Loss records
    # =======================================================================
    def create_loss_record(self, payload: Dict[str, Any],
                           headers: Dict[str, str]):
        return self._request("POST", "/loss-records", payload, headers)

    def list_loss_records(self, headers: Dict[str, str],
                          params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/loss-records", headers=headers, params=params,
        )

    # =======================================================================
    # Audit logs
    # =======================================================================
    def list_audit_logs(self, headers: Dict[str, str],
                        params: Optional[Dict[str, Any]] = None):
        return self._request(
            "GET", "/audit-logs", headers=headers, params=params,
        )

    # =======================================================================
    # Test-driving endpoints
    # =======================================================================
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
        return self._request("POST", "/_events/emit", payload, headers)


api_client = ApiClient()


__all__ = ["ApiClient", "api_client"]
