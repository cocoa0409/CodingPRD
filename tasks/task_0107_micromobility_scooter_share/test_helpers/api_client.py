"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /api prefix. The base _request() method is
inherited from GenericApiClient; each method returns the raw Response so tests
can assert status codes.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Plan ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/api/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/api/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/api/plans", headers=headers, params=params)

    # ---- Zone ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/api/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/api/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/api/zones", headers=headers, params=params)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/api/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/api/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/api/vehicles", headers=headers, params=params)

    def vehicle_maintenance(self, vehicle_id, headers):
        return self._request("POST", f"/api/vehicles/{vehicle_id}/maintenance", {}, headers)

    def vehicle_return_to_service(self, vehicle_id, headers):
        return self._request("POST", f"/api/vehicles/{vehicle_id}/return-to-service", {}, headers)

    def vehicle_retire(self, vehicle_id, headers):
        return self._request("POST", f"/api/vehicles/{vehicle_id}/retire", {}, headers)

    # ---- Rider ----
    def create_rider(self, payload, headers):
        return self._request("POST", "/api/riders", payload, headers)

    def get_rider(self, rider_id, headers):
        return self._request("GET", f"/api/riders/{rider_id}", headers=headers)

    def list_riders(self, headers, params=None):
        return self._request("GET", "/api/riders", headers=headers, params=params)

    def topup_rider(self, rider_id, payload, headers):
        return self._request("POST", f"/api/riders/{rider_id}/topup", payload, headers)

    def change_plan(self, rider_id, payload, headers):
        return self._request("POST", f"/api/riders/{rider_id}/change-plan", payload, headers)

    def suspend_rider(self, rider_id, headers):
        return self._request("POST", f"/api/riders/{rider_id}/suspend", {}, headers)

    def reinstate_rider(self, rider_id, headers):
        return self._request("POST", f"/api/riders/{rider_id}/reinstate", {}, headers)

    def list_rider_wallet_transactions(self, rider_id, headers, params=None):
        return self._request("GET", f"/api/riders/{rider_id}/wallet-transactions",
                             headers=headers, params=params)

    # ---- WalletTransaction (flat reads) ----
    def get_wallet_transaction(self, txn_id, headers):
        return self._request("GET", f"/api/wallet-transactions/{txn_id}", headers=headers)

    def list_wallet_transactions(self, headers, params=None):
        return self._request("GET", "/api/wallet-transactions", headers=headers, params=params)

    # ---- Trip ----
    def create_trip(self, payload, headers):
        return self._request("POST", "/api/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/api/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/api/trips", headers=headers, params=params)

    def list_trip_segments_subresource(self, trip_id, headers, params=None):
        return self._request("GET", f"/api/trips/{trip_id}/segments", headers=headers, params=params)

    def get_trip_segment(self, segment_id, headers):
        return self._request("GET", f"/api/trip-segments/{segment_id}", headers=headers)

    def list_trip_segments(self, headers, params=None):
        return self._request("GET", "/api/trip-segments", headers=headers, params=params)

    def pause_trip(self, trip_id, headers):
        return self._request("POST", f"/api/trips/{trip_id}/pause", {}, headers)

    def resume_trip(self, trip_id, headers):
        return self._request("POST", f"/api/trips/{trip_id}/resume", {}, headers)

    def end_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/api/trips/{trip_id}/end", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/api/trips/{trip_id}/cancel", {}, headers)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/api/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/api/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/api/technicians", headers=headers, params=params)

    # ---- RebalancingTask ----
    def create_rebalancing_task(self, payload, headers):
        return self._request("POST", "/api/rebalancing-tasks", payload, headers)

    def get_rebalancing_task(self, task_id, headers):
        return self._request("GET", f"/api/rebalancing-tasks/{task_id}", headers=headers)

    def list_rebalancing_tasks(self, headers, params=None):
        return self._request("GET", "/api/rebalancing-tasks", headers=headers, params=params)

    def assign_rebalancing_task(self, task_id, payload, headers):
        return self._request("POST", f"/api/rebalancing-tasks/{task_id}/assign", payload, headers)

    def unassign_rebalancing_task(self, task_id, headers):
        return self._request("POST", f"/api/rebalancing-tasks/{task_id}/unassign", {}, headers)

    def complete_rebalancing_task(self, task_id, headers):
        return self._request("POST", f"/api/rebalancing-tasks/{task_id}/complete", {}, headers)

    def cancel_rebalancing_task(self, task_id, headers):
        return self._request("POST", f"/api/rebalancing-tasks/{task_id}/cancel", {}, headers)

    # ---- Fine ----
    def get_fine(self, fine_id, headers):
        return self._request("GET", f"/api/fines/{fine_id}", headers=headers)

    def list_fines(self, headers, params=None):
        return self._request("GET", "/api/fines", headers=headers, params=params)

    def settle_fine(self, fine_id, headers):
        return self._request("POST", f"/api/fines/{fine_id}/settle", {}, headers)

    def dispute_fine(self, fine_id, headers):
        return self._request("POST", f"/api/fines/{fine_id}/dispute", {}, headers)

    def reject_dispute_fine(self, fine_id, headers):
        return self._request("POST", f"/api/fines/{fine_id}/reject-dispute", {}, headers)

    def waive_fine(self, fine_id, headers):
        return self._request("POST", f"/api/fines/{fine_id}/waive", {}, headers)

    # ---- LowIncomeApplication ----
    def create_low_income_application(self, payload, headers):
        return self._request("POST", "/api/low-income-applications", payload, headers)

    def get_low_income_application(self, app_id, headers):
        return self._request("GET", f"/api/low-income-applications/{app_id}", headers=headers)

    def list_low_income_applications(self, headers, params=None):
        return self._request("GET", "/api/low-income-applications", headers=headers, params=params)

    def approve_low_income_application(self, app_id, headers):
        return self._request("POST", f"/api/low-income-applications/{app_id}/approve", {}, headers)

    def reject_low_income_application(self, app_id, headers):
        return self._request("POST", f"/api/low-income-applications/{app_id}/reject", {}, headers)

    # ---- MDSReport ----
    def create_mds_report(self, payload, headers):
        return self._request("POST", "/api/mds-reports", payload, headers)

    def get_mds_report(self, report_id, headers):
        return self._request("GET", f"/api/mds-reports/{report_id}", headers=headers)

    def finalize_mds_report(self, report_id, headers):
        return self._request("POST", f"/api/mds-reports/{report_id}/finalize", {}, headers)

    # ---- Test-driving endpoints ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    def set_battery(self, vehicle_id, payload, headers):
        return self._request("POST", f"/api/_vehicles/{vehicle_id}/set_battery", payload, headers)


api_client = ApiClient()
