"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Units ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/evs/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/evs/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/evs/units/{unit_id}", headers=headers)

    def run_ops_run(self, unit_id, headers):
        return self._request("POST", f"/evs/units/{unit_id}/ops-runs", {}, headers)

    def list_turnaround_snapshots(self, unit_id, headers, params=None):
        return self._request(
            "GET", f"/evs/units/{unit_id}/turnaround-snapshots",
            headers=headers, params=params,
        )

    def get_turnaround_snapshot(self, snapshot_id, headers):
        return self._request(
            "GET", f"/evs/turnaround-snapshots/{snapshot_id}", headers=headers
        )

    # --- Beds ---
    def create_bed(self, payload, headers):
        return self._request("POST", "/evs/beds", payload, headers)

    def list_beds(self, headers, params=None):
        return self._request("GET", "/evs/beds", headers=headers, params=params)

    def get_bed(self, bed_id, headers):
        return self._request("GET", f"/evs/beds/{bed_id}", headers=headers)

    def discharge_bed(self, bed_id, payload, headers):
        return self._request(
            "POST", f"/evs/beds/{bed_id}/discharge", payload, headers
        )

    def admit_bed(self, bed_id, headers):
        return self._request("POST", f"/evs/beds/{bed_id}/admit", {}, headers)

    def mark_soiled_bed(self, bed_id, headers):
        return self._request("POST", f"/evs/beds/{bed_id}/mark-soiled", {}, headers)

    # --- Maintenance windows ---
    def create_maintenance_window(self, payload, headers):
        return self._request("POST", "/evs/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, headers, params=None):
        return self._request(
            "GET", "/evs/maintenance-windows", headers=headers, params=params
        )

    def get_maintenance_window(self, window_id, headers):
        return self._request(
            "GET", f"/evs/maintenance-windows/{window_id}", headers=headers
        )

    def activate_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/evs/maintenance-windows/{window_id}/activate", {}, headers
        )

    def close_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/evs/maintenance-windows/{window_id}/close", {}, headers
        )

    def cancel_maintenance_window(self, window_id, headers):
        return self._request(
            "POST", f"/evs/maintenance-windows/{window_id}/cancel", {}, headers
        )

    # --- Clean requests ---
    def create_clean_request(self, payload, headers):
        return self._request("POST", "/evs/clean-requests", payload, headers)

    def list_clean_requests(self, headers, params=None):
        return self._request(
            "GET", "/evs/clean-requests", headers=headers, params=params
        )

    def get_clean_request(self, request_id, headers):
        return self._request(
            "GET", f"/evs/clean-requests/{request_id}", headers=headers
        )

    def assign_clean_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/evs/clean-requests/{request_id}/assign", payload, headers
        )

    def reassign_clean_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/evs/clean-requests/{request_id}/reassign", payload, headers
        )

    def unassign_clean_request(self, request_id, headers):
        return self._request(
            "POST", f"/evs/clean-requests/{request_id}/unassign", {}, headers
        )

    def start_clean_request(self, request_id, headers):
        return self._request(
            "POST", f"/evs/clean-requests/{request_id}/start", {}, headers
        )

    def complete_clean_request(self, request_id, headers):
        return self._request(
            "POST", f"/evs/clean-requests/{request_id}/complete", {}, headers
        )

    def cancel_clean_request(self, request_id, headers):
        return self._request(
            "POST", f"/evs/clean-requests/{request_id}/cancel", {}, headers
        )

    def pull_clean_request(self, headers):
        return self._request("POST", "/evs/clean-requests/pull", {}, headers)

    # --- Staff ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/evs/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/evs/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/evs/staff/{staff_id}", headers=headers)

    def get_staff_productivity(self, staff_id, headers):
        return self._request(
            "GET", f"/evs/staff/{staff_id}/productivity", headers=headers
        )

    def clock_in_staff(self, staff_id, headers):
        return self._request(
            "POST", f"/evs/staff/{staff_id}/clock-in", {}, headers
        )

    def clock_out_staff(self, staff_id, headers):
        return self._request(
            "POST", f"/evs/staff/{staff_id}/clock-out", {}, headers
        )

    def break_start_staff(self, staff_id, headers):
        return self._request(
            "POST", f"/evs/staff/{staff_id}/break-start", {}, headers
        )

    def break_end_staff(self, staff_id, headers):
        return self._request(
            "POST", f"/evs/staff/{staff_id}/break-end", {}, headers
        )

    # --- Quality audits ---
    def create_quality_audit(self, payload, headers):
        return self._request("POST", "/evs/quality-audits", payload, headers)

    def list_quality_audits(self, headers, params=None):
        return self._request(
            "GET", "/evs/quality-audits", headers=headers, params=params
        )

    def get_quality_audit(self, audit_id, headers):
        return self._request("GET", f"/evs/quality-audits/{audit_id}", headers=headers)

    def void_quality_audit(self, audit_id, headers):
        return self._request(
            "POST", f"/evs/quality-audits/{audit_id}/void", {}, headers
        )

    # --- Supplies ---
    def create_supply_item(self, payload, headers):
        return self._request("POST", "/evs/supply-items", payload, headers)

    def list_supply_items(self, headers, params=None):
        return self._request("GET", "/evs/supply-items", headers=headers, params=params)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"/evs/supply-items/{item_id}", headers=headers)

    def restock_supply_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/evs/supply-items/{item_id}/restock", payload, headers
        )

    def recount_supply_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/evs/supply-items/{item_id}/recount", payload, headers
        )

    def list_supply_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/evs/supply-ledger-entries", headers=headers, params=params
        )

    def get_supply_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/evs/supply-ledger-entries/{entry_id}", headers=headers
        )

    # --- Outbreaks ---
    def create_outbreak_event(self, payload, headers):
        return self._request("POST", "/evs/outbreak-events", payload, headers)

    def list_outbreak_events(self, headers, params=None):
        return self._request(
            "GET", "/evs/outbreak-events", headers=headers, params=params
        )

    def get_outbreak_event(self, event_id, headers):
        return self._request(
            "GET", f"/evs/outbreak-events/{event_id}", headers=headers
        )

    def activate_outbreak_event(self, event_id, headers):
        return self._request(
            "POST", f"/evs/outbreak-events/{event_id}/activate", {}, headers
        )

    def lift_outbreak_event(self, event_id, headers):
        return self._request(
            "POST", f"/evs/outbreak-events/{event_id}/lift", {}, headers
        )

    def cancel_outbreak_event(self, event_id, headers):
        return self._request(
            "POST", f"/evs/outbreak-events/{event_id}/cancel", {}, headers
        )

    # --- Bed-ready notifications ---
    def list_bed_ready_notifications(self, headers, params=None):
        return self._request(
            "GET", "/evs/bed-ready-notifications", headers=headers, params=params
        )

    def get_bed_ready_notification(self, notification_id, headers):
        return self._request(
            "GET", f"/evs/bed-ready-notifications/{notification_id}", headers=headers
        )

    def acknowledge_bed_ready_notification(self, notification_id, headers):
        return self._request(
            "POST",
            f"/evs/bed-ready-notifications/{notification_id}/acknowledge",
            {},
            headers,
        )

    # --- Placement demands ---
    def create_placement_demand(self, payload, headers):
        return self._request("POST", "/evs/placement-demands", payload, headers)

    def list_placement_demands(self, headers, params=None):
        return self._request(
            "GET", "/evs/placement-demands", headers=headers, params=params
        )

    def get_placement_demand(self, demand_id, headers):
        return self._request(
            "GET", f"/evs/placement-demands/{demand_id}", headers=headers
        )

    def cancel_placement_demand(self, demand_id, headers):
        return self._request(
            "POST", f"/evs/placement-demands/{demand_id}/cancel", {}, headers
        )

    def regrade_placement_demand(self, demand_id, payload, headers):
        return self._request(
            "POST", f"/evs/placement-demands/{demand_id}/regrade", payload, headers
        )

    # --- Clean standards ---
    def create_clean_standard(self, payload, headers):
        return self._request("POST", "/evs/clean-standards", payload, headers)

    def list_clean_standards(self, headers, params=None):
        return self._request(
            "GET", "/evs/clean-standards", headers=headers, params=params
        )

    def get_clean_standard(self, clean_type, headers):
        return self._request(
            "GET", f"/evs/clean-standards/{clean_type}", headers=headers
        )

    def update_clean_standard(self, clean_type, payload, headers):
        return self._request(
            "PUT", f"/evs/clean-standards/{clean_type}", payload, headers
        )


api_client = ApiClient()
