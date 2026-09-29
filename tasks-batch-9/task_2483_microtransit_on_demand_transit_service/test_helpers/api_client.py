"""API client: one method per endpoint defined in the PRD (§4).

Every collection is mounted at the top level; there are no nested resource
paths. Creates answer 201, everything else answers 200.
"""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Service zones ────────────────────────────────────────────────────

    def create_service_zone(self, payload, headers):
        return self._request("POST", "/service-zones", payload, headers)

    def activate_service_zone(self, zone_id, headers, payload=None):
        return self._request(
            "POST", f"/service-zones/{zone_id}/activate", payload or {}, headers
        )

    def suspend_service_zone(self, zone_id, headers, payload=None):
        return self._request(
            "POST", f"/service-zones/{zone_id}/suspend", payload or {}, headers
        )

    def get_service_zone(self, zone_id, headers):
        return self._request("GET", f"/service-zones/{zone_id}", headers=headers)

    def list_service_zones(self, headers, params=None):
        return self._request("GET", "/service-zones", headers=headers, params=params)

    # ─── Virtual stops ────────────────────────────────────────────────────

    def create_virtual_stop(self, payload, headers):
        return self._request("POST", "/virtual-stops", payload, headers)

    def approve_virtual_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST", f"/virtual-stops/{stop_id}/approve", payload or {}, headers
        )

    def retire_virtual_stop(self, stop_id, headers, payload=None):
        return self._request(
            "POST", f"/virtual-stops/{stop_id}/retire", payload or {}, headers
        )

    def get_virtual_stop(self, stop_id, headers):
        return self._request("GET", f"/virtual-stops/{stop_id}", headers=headers)

    def list_virtual_stops(self, headers, params=None):
        return self._request("GET", "/virtual-stops", headers=headers, params=params)

    # ─── Transit connections ──────────────────────────────────────────────

    def create_transit_connection(self, payload, headers):
        return self._request("POST", "/transit-connections", payload, headers)

    def get_transit_connection(self, connection_id, headers):
        return self._request(
            "GET", f"/transit-connections/{connection_id}", headers=headers
        )

    def list_transit_connections(self, headers, params=None):
        return self._request(
            "GET", "/transit-connections", headers=headers, params=params
        )

    # ─── Vehicles ─────────────────────────────────────────────────────────

    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def set_vehicle_status(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/status", payload, headers
        )

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ─── Drivers ──────────────────────────────────────────────────────────

    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def set_driver_status(self, driver_id, payload, headers):
        return self._request("POST", f"/drivers/{driver_id}/status", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def list_drivers(self, headers, params=None):
        return self._request("GET", "/drivers", headers=headers, params=params)

    # ─── Riders ───────────────────────────────────────────────────────────

    def create_rider(self, payload, headers):
        return self._request("POST", "/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/riders/{rider_id}", headers=headers)

    def list_riders(self, headers, params=None):
        return self._request("GET", "/riders", headers=headers, params=params)

    # ─── Demand forecasts ─────────────────────────────────────────────────

    def create_demand_forecast(self, payload, headers):
        return self._request("POST", "/demand-forecasts", payload, headers)

    def get_demand_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/demand-forecasts/{forecast_id}", headers=headers
        )

    def list_demand_forecasts(self, headers, params=None):
        return self._request(
            "GET", "/demand-forecasts", headers=headers, params=params
        )

    # ─── Vehicle blocks ───────────────────────────────────────────────────

    def create_vehicle_block(self, payload, headers):
        return self._request("POST", "/vehicle-blocks", payload, headers)

    def open_vehicle_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/vehicle-blocks/{block_id}/open", payload or {}, headers
        )

    def close_vehicle_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/vehicle-blocks/{block_id}/close", payload or {}, headers
        )

    def cancel_vehicle_block(self, block_id, headers, payload=None):
        return self._request(
            "POST", f"/vehicle-blocks/{block_id}/cancel", payload or {}, headers
        )

    def get_vehicle_block(self, block_id, headers):
        return self._request("GET", f"/vehicle-blocks/{block_id}", headers=headers)

    def list_vehicle_blocks(self, headers, params=None):
        return self._request("GET", "/vehicle-blocks", headers=headers, params=params)

    # ─── Trip requests ────────────────────────────────────────────────────

    def create_trip_request(self, payload, headers):
        return self._request("POST", "/trip-requests", payload, headers)

    def match_trip_request(self, trip_id, headers, payload=None):
        return self._request(
            "POST", f"/trip-requests/{trip_id}/match", payload or {}, headers
        )

    def cancel_trip_request(self, trip_id, headers, payload=None):
        return self._request(
            "POST", f"/trip-requests/{trip_id}/cancel", payload or {}, headers
        )

    def refund_trip_request(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/trip-requests/{trip_id}/refund", payload, headers
        )

    def get_trip_request(self, trip_id, headers):
        return self._request("GET", f"/trip-requests/{trip_id}", headers=headers)

    def list_trip_requests(self, headers, params=None):
        return self._request("GET", "/trip-requests", headers=headers, params=params)

    # ─── Pool assignments ─────────────────────────────────────────────────

    def create_pool_assignment(self, payload, headers):
        return self._request("POST", "/pool-assignments", payload, headers)

    def accept_pool_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/pool-assignments/{assignment_id}/accept", payload or {}, headers
        )

    def decline_pool_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pool-assignments/{assignment_id}/decline",
            payload or {},
            headers,
        )

    def board_pool_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"/pool-assignments/{assignment_id}/board", payload or {}, headers
        )

    def complete_pool_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST",
            f"/pool-assignments/{assignment_id}/complete",
            payload or {},
            headers,
        )

    def get_pool_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/pool-assignments/{assignment_id}", headers=headers
        )

    def list_pool_assignments(self, headers, params=None):
        return self._request(
            "GET", "/pool-assignments", headers=headers, params=params
        )

    # ─── Fare transactions (read-only ledger) ─────────────────────────────

    def get_fare_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"/fare-transactions/{transaction_id}", headers=headers
        )

    def list_fare_transactions(self, headers, params=None):
        return self._request(
            "GET", "/fare-transactions", headers=headers, params=params
        )

    # ─── Subsidy reports ──────────────────────────────────────────────────

    def create_subsidy_report(self, payload, headers):
        return self._request("POST", "/subsidy-reports", payload, headers)

    def submit_subsidy_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/subsidy-reports/{report_id}/submit", payload or {}, headers
        )

    def certify_subsidy_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/subsidy-reports/{report_id}/certify", payload or {}, headers
        )

    def reject_subsidy_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/subsidy-reports/{report_id}/reject", payload, headers
        )

    def amend_subsidy_report(self, report_id, headers, payload=None):
        return self._request(
            "POST", f"/subsidy-reports/{report_id}/amend", payload or {}, headers
        )

    def get_subsidy_report(self, report_id, headers):
        return self._request("GET", f"/subsidy-reports/{report_id}", headers=headers)

    def list_subsidy_reports(self, headers, params=None):
        return self._request("GET", "/subsidy-reports", headers=headers, params=params)

    # ─── Logical clock ────────────────────────────────────────────────────

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
