"""API client: one method per endpoint defined in the PRD (§4).

All paths include the /api mount. Methods return raw requests.Response so
tests can assert status codes; validators live in the framework.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- VesselCall ---
    def create_vessel_call(self, payload, headers):
        return self._request("POST", "/api/vessel-calls", payload, headers)

    def list_vessel_calls(self, headers, params=None):
        return self._request("GET", "/api/vessel-calls", headers=headers, params=params)

    def get_vessel_call(self, vessel_id, headers):
        return self._request("GET", f"/api/vessel-calls/{vessel_id}", headers=headers)

    def berth_vessel_call(self, vessel_id, headers):
        return self._request("POST", f"/api/vessel-calls/{vessel_id}/berth", headers=headers)

    def complete_vessel_call(self, vessel_id, headers):
        return self._request("POST", f"/api/vessel-calls/{vessel_id}/complete", headers=headers)

    def cancel_vessel_call(self, vessel_id, headers):
        return self._request("POST", f"/api/vessel-calls/{vessel_id}/cancel", headers=headers)

    # --- ShiftWindow ---
    def create_shift_window(self, payload, headers):
        return self._request("POST", "/api/shift-windows", payload, headers)

    def list_shift_windows(self, headers, params=None):
        return self._request("GET", "/api/shift-windows", headers=headers, params=params)

    def get_shift_window(self, shift_id, headers):
        return self._request("GET", f"/api/shift-windows/{shift_id}", headers=headers)

    def open_shift_window_for_orders(self, shift_id, headers):
        return self._request("POST", f"/api/shift-windows/{shift_id}/open-for-orders", headers=headers)

    def start_shift_window(self, shift_id, headers):
        return self._request("POST", f"/api/shift-windows/{shift_id}/start", headers=headers)

    # --- GangOrder ---
    def create_gang_order(self, payload, headers):
        return self._request("POST", "/api/gang-orders", payload, headers)

    def list_gang_orders(self, headers, params=None):
        return self._request("GET", "/api/gang-orders", headers=headers, params=params)

    def get_gang_order(self, gang_id, headers):
        return self._request("GET", f"/api/gang-orders/{gang_id}", headers=headers)

    def amend_gang_order(self, gang_id, payload, headers):
        return self._request("PATCH", f"/api/gang-orders/{gang_id}", payload, headers)

    def cancel_gang_order(self, gang_id, headers):
        return self._request("POST", f"/api/gang-orders/{gang_id}/cancel", headers=headers)

    def start_gang_work(self, gang_id, headers):
        return self._request("POST", f"/api/gang-orders/{gang_id}/start-work", headers=headers)

    def complete_gang_order(self, gang_id, headers):
        return self._request("POST", f"/api/gang-orders/{gang_id}/complete", headers=headers)

    def dispatch_batch(self, gang_id, payload, headers):
        return self._request("POST", f"/api/gang-orders/{gang_id}/dispatch-batch", payload, headers)

    def get_gang_order_productivity(self, gang_id, headers):
        return self._request("GET", f"/api/gang-orders/{gang_id}/productivity", headers=headers)

    # --- Worker ---
    def create_worker(self, payload, headers):
        return self._request("POST", "/api/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/api/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/api/workers/{worker_id}", headers=headers)

    def update_worker_status(self, worker_id, payload, headers):
        return self._request("PATCH", f"/api/workers/{worker_id}", payload, headers)

    # --- DispatchAssignment ---
    def list_dispatch_assignments(self, headers, params=None):
        return self._request("GET", "/api/dispatch-assignments", headers=headers, params=params)

    def get_dispatch_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/dispatch-assignments/{assignment_id}", headers=headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/dispatch-assignments/{assignment_id}/check-in", headers=headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/dispatch-assignments/{assignment_id}/complete", headers=headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/api/dispatch-assignments/{assignment_id}/no-show", headers=headers)

    def bump_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/dispatch-assignments/{assignment_id}/bump", headers=headers)

    # --- EquipmentUnit ---
    def create_equipment_unit(self, payload, headers):
        return self._request("POST", "/api/equipment-units", payload, headers)

    def list_equipment_units(self, headers, params=None):
        return self._request("GET", "/api/equipment-units", headers=headers, params=params)

    def get_equipment_unit(self, unit_id, headers):
        return self._request("GET", f"/api/equipment-units/{unit_id}", headers=headers)

    def repair_complete_equipment_unit(self, unit_id, headers):
        return self._request("POST", f"/api/equipment-units/{unit_id}/repair-complete", headers=headers)

    # --- EquipmentAssignment ---
    def create_equipment_assignment(self, payload, headers):
        return self._request("POST", "/api/equipment-assignments", payload, headers)

    def list_equipment_assignments(self, headers, params=None):
        return self._request("GET", "/api/equipment-assignments", headers=headers, params=params)

    def get_equipment_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/equipment-assignments/{assignment_id}", headers=headers)

    def report_equipment_breakdown(self, assignment_id, headers):
        return self._request("POST", f"/api/equipment-assignments/{assignment_id}/report-breakdown", headers=headers)

    def release_equipment_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/equipment-assignments/{assignment_id}/release", headers=headers)

    # --- MoveRecord ---
    def create_move_record(self, payload, headers):
        return self._request("POST", "/api/move-records", payload, headers)

    def list_move_records(self, headers, params=None):
        return self._request("GET", "/api/move-records", headers=headers, params=params)

    def get_move_record(self, record_id, headers):
        return self._request("GET", f"/api/move-records/{record_id}", headers=headers)

    def void_move_record(self, record_id, headers):
        return self._request("POST", f"/api/move-records/{record_id}/void", headers=headers)

    # --- DamageClaim ---
    def create_damage_claim(self, payload, headers):
        return self._request("POST", "/api/damage-claims", payload, headers)

    def list_damage_claims(self, headers, params=None):
        return self._request("GET", "/api/damage-claims", headers=headers, params=params)

    def get_damage_claim(self, claim_id, headers):
        return self._request("GET", f"/api/damage-claims/{claim_id}", headers=headers)

    def decide_damage_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/api/damage-claims/{claim_id}/decide", payload, headers)

    def settle_damage_claim(self, claim_id, headers):
        return self._request("POST", f"/api/damage-claims/{claim_id}/settle", headers=headers)

    # --- SafetyIncident ---
    def create_safety_incident(self, payload, headers):
        return self._request("POST", "/api/safety-incidents", payload, headers)

    def list_safety_incidents(self, headers, params=None):
        return self._request("GET", "/api/safety-incidents", headers=headers, params=params)

    def get_safety_incident(self, incident_id, headers):
        return self._request("GET", f"/api/safety-incidents/{incident_id}", headers=headers)

    def clear_safety_incident(self, incident_id, headers):
        return self._request("POST", f"/api/safety-incidents/{incident_id}/clear", headers=headers)

    # --- TimesheetEntry ---
    def create_timesheet_entry(self, payload, headers):
        return self._request("POST", "/api/timesheet-entries", payload, headers)

    def list_timesheet_entries(self, headers, params=None):
        return self._request("GET", "/api/timesheet-entries", headers=headers, params=params)

    def get_timesheet_entry(self, entry_id, headers):
        return self._request("GET", f"/api/timesheet-entries/{entry_id}", headers=headers)

    def submit_timesheet_entry(self, entry_id, headers):
        return self._request("POST", f"/api/timesheet-entries/{entry_id}/submit", headers=headers)

    def approve_timesheet_entry(self, entry_id, headers):
        return self._request("POST", f"/api/timesheet-entries/{entry_id}/approve", headers=headers)

    def reject_timesheet_entry(self, entry_id, headers):
        return self._request("POST", f"/api/timesheet-entries/{entry_id}/reject", headers=headers)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def adjust_invoice(self, invoice_id, payload, headers):
        return self._request("PATCH", f"/api/invoices/{invoice_id}", payload, headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/finalize", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/issue", headers=headers)

    def record_invoice_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/record-payment", payload, headers)

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/dispute", payload, headers)


api_client = ApiClient()
