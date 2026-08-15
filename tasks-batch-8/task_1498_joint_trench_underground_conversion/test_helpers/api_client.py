"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/api/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def project_lifecycle(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/lifecycle", payload, headers)

    def replan_project(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/replan", payload, headers)

    # --- UtilityParticipation ---
    def create_participation(self, payload, headers):
        return self._request("POST", "/api/participations", payload, headers)

    def list_participations(self, headers, params=None):
        return self._request("GET", "/api/participations", headers=headers, params=params)

    def get_participation(self, participation_id, headers):
        return self._request("GET", f"/api/participations/{participation_id}", headers=headers)

    def transition_participation(self, participation_id, payload, headers):
        return self._request("POST", f"/api/participations/{participation_id}/transition", payload, headers)

    # --- TrenchSegment ---
    def create_trench_segment(self, payload, headers):
        return self._request("POST", "/api/trench-segments", payload, headers)

    def list_trench_segments(self, headers, params=None):
        return self._request("GET", "/api/trench-segments", headers=headers, params=params)

    def get_trench_segment(self, segment_id, headers):
        return self._request("GET", f"/api/trench-segments/{segment_id}", headers=headers)

    def schedule_trench_segment(self, segment_id, payload, headers):
        return self._request("POST", f"/api/trench-segments/{segment_id}/schedule", payload, headers)

    def transition_trench_segment(self, segment_id, payload, headers):
        return self._request("POST", f"/api/trench-segments/{segment_id}/transition", payload, headers)

    # --- OccupancySlot ---
    def create_occupancy_slot(self, payload, headers):
        return self._request("POST", "/api/occupancy-slots", payload, headers)

    def list_occupancy_slots(self, headers, params=None):
        return self._request("GET", "/api/occupancy-slots", headers=headers, params=params)

    def get_occupancy_slot(self, slot_id, headers):
        return self._request("GET", f"/api/occupancy-slots/{slot_id}", headers=headers)

    def transition_occupancy_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/api/occupancy-slots/{slot_id}/transition", payload, headers)

    # --- Parcel ---
    def create_parcel(self, payload, headers):
        return self._request("POST", "/api/parcels", payload, headers)

    def list_parcels(self, headers, params=None):
        return self._request("GET", "/api/parcels", headers=headers, params=params)

    def get_parcel(self, parcel_id, headers):
        return self._request("GET", f"/api/parcels/{parcel_id}", headers=headers)

    # --- Easement ---
    def create_easement(self, payload, headers):
        return self._request("POST", "/api/easements", payload, headers)

    def list_easements(self, headers, params=None):
        return self._request("GET", "/api/easements", headers=headers, params=params)

    def get_easement(self, easement_id, headers):
        return self._request("GET", f"/api/easements/{easement_id}", headers=headers)

    def transition_easement(self, easement_id, payload, headers):
        return self._request("POST", f"/api/easements/{easement_id}/transition", payload, headers)

    # --- Permit ---
    def create_permit(self, payload, headers):
        return self._request("POST", "/api/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/api/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/api/permits/{permit_id}", headers=headers)

    def transition_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/api/permits/{permit_id}/transition", payload, headers)

    # --- ServiceConversion ---
    def create_service_conversion(self, payload, headers):
        return self._request("POST", "/api/service-conversions", payload, headers)

    def list_service_conversions(self, headers, params=None):
        return self._request("GET", "/api/service-conversions", headers=headers, params=params)

    def get_service_conversion(self, conversion_id, headers):
        return self._request("GET", f"/api/service-conversions/{conversion_id}", headers=headers)

    def work_transition(self, conversion_id, payload, headers):
        return self._request("POST", f"/api/service-conversions/{conversion_id}/work-transition", payload, headers)

    def temp_service_transition(self, conversion_id, payload, headers):
        return self._request("POST", f"/api/service-conversions/{conversion_id}/temp-service-transition", payload, headers)

    # --- OutageWindow ---
    def create_outage_window(self, payload, headers):
        return self._request("POST", "/api/outage-windows", payload, headers)

    def list_outage_windows(self, headers, params=None):
        return self._request("GET", "/api/outage-windows", headers=headers, params=params)

    def get_outage_window(self, outage_id, headers):
        return self._request("GET", f"/api/outage-windows/{outage_id}", headers=headers)

    def transition_outage_window(self, outage_id, payload, headers):
        return self._request("POST", f"/api/outage-windows/{outage_id}/transition", payload, headers)

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/api/change-orders", payload, headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/api/change-orders", headers=headers, params=params)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/api/change-orders/{change_order_id}", headers=headers)

    def transition_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/api/change-orders/{change_order_id}/transition", payload, headers)

    # --- ActualCostEntry ---
    def create_actual_cost_entry(self, payload, headers):
        return self._request("POST", "/api/actual-cost-entries", payload, headers)

    def list_actual_cost_entries(self, headers, params=None):
        return self._request("GET", "/api/actual-cost-entries", headers=headers, params=params)

    def get_actual_cost_entry(self, entry_id, headers):
        return self._request("GET", f"/api/actual-cost-entries/{entry_id}", headers=headers)

    # --- TrueUpRun / Invoice ---
    def create_true_up_run(self, payload, headers):
        return self._request("POST", "/api/true-up-runs", payload, headers)

    def list_true_up_runs(self, headers, params=None):
        return self._request("GET", "/api/true-up-runs", headers=headers, params=params)

    def get_true_up_run(self, run_id, headers):
        return self._request("GET", f"/api/true-up-runs/{run_id}", headers=headers)

    def transition_true_up_run(self, run_id, payload, headers):
        return self._request("POST", f"/api/true-up-runs/{run_id}/transition", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def transition_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/transition", payload, headers)

    # --- RestorationTask ---
    def create_restoration_task(self, payload, headers):
        return self._request("POST", "/api/restoration-tasks", payload, headers)

    def list_restoration_tasks(self, headers, params=None):
        return self._request("GET", "/api/restoration-tasks", headers=headers, params=params)

    def get_restoration_task(self, task_id, headers):
        return self._request("GET", f"/api/restoration-tasks/{task_id}", headers=headers)

    def transition_restoration_task(self, task_id, payload, headers):
        return self._request("POST", f"/api/restoration-tasks/{task_id}/transition", payload, headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
