"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Operator ---
    def create_operator(self, payload, headers):
        return self._request("POST", "/v1/operators", payload, headers)

    def get_operator(self, operator_id, headers):
        return self._request("GET", f"/v1/operators/{operator_id}", headers=headers)

    def transition_operator(self, operator_id, payload, headers):
        return self._request(
            "POST", f"/v1/operators/{operator_id}/transitions", payload, headers
        )

    # --- Vehicle ---
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/v1/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/v1/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/v1/vehicles", headers=headers, params=params)

    # --- Permit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/v1/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/v1/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/v1/permits", headers=headers, params=params)

    def transition_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/v1/permits/{permit_id}/transitions", payload, headers
        )

    # --- StagingLot ---
    def create_staging_lot(self, payload, headers):
        return self._request("POST", "/v1/staging-lots", payload, headers)

    # --- QueueEntry ---
    def create_queue_entry(self, payload, headers):
        return self._request("POST", "/v1/queue-entries", payload, headers)

    def get_queue_entry(self, queue_entry_id, headers):
        return self._request(
            "GET", f"/v1/queue-entries/{queue_entry_id}", headers=headers
        )

    def list_queue_entries(self, headers, params=None):
        return self._request(
            "GET", "/v1/queue-entries", headers=headers, params=params
        )

    def transition_queue_entry(self, queue_entry_id, payload, headers):
        return self._request(
            "POST", f"/v1/queue-entries/{queue_entry_id}/transitions", payload, headers
        )

    # --- CurbZone ---
    def create_curb_zone(self, payload, headers):
        return self._request("POST", "/v1/curb-zones", payload, headers)

    # --- CurbAssignment ---
    def create_curb_assignment(self, payload, headers):
        return self._request("POST", "/v1/curb-assignments", payload, headers)

    def get_curb_assignment(self, curb_assignment_id, headers):
        return self._request(
            "GET", f"/v1/curb-assignments/{curb_assignment_id}", headers=headers
        )

    def list_curb_assignments(self, headers, params=None):
        return self._request(
            "GET", "/v1/curb-assignments", headers=headers, params=params
        )

    # --- Trip ---
    def create_trip(self, payload, headers):
        return self._request("POST", "/v1/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/v1/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/v1/trips", headers=headers, params=params)

    def transition_trip(self, trip_id, payload, headers):
        return self._request(
            "POST", f"/v1/trips/{trip_id}/transitions", payload, headers
        )

    # --- Violation ---
    def create_violation(self, payload, headers):
        return self._request("POST", "/v1/violations", payload, headers)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/v1/violations/{violation_id}", headers=headers)

    def list_violations(self, headers, params=None):
        return self._request("GET", "/v1/violations", headers=headers, params=params)

    def transition_violation(self, violation_id, payload, headers):
        return self._request(
            "POST", f"/v1/violations/{violation_id}/transitions", payload, headers
        )

    # --- SettlementStatement ---
    def create_settlement(self, payload, headers):
        return self._request("POST", "/v1/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request(
            "GET", f"/v1/settlements/{settlement_id}", headers=headers
        )

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/v1/settlements", headers=headers, params=params)

    def transition_settlement(self, settlement_id, payload, headers):
        return self._request(
            "POST", f"/v1/settlements/{settlement_id}/transitions", payload, headers
        )


api_client = ApiClient()
