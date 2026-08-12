"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Turnaround lifecycle ---
    def create_turnaround(self, payload, headers):
        return self._request("POST", "/turnarounds", payload, headers)

    def get_turnaround(self, turnaround_id, headers):
        return self._request("GET", f"/turnarounds/{turnaround_id}", headers=headers)

    def freeze_scope(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/freeze-scope", payload, headers)

    def advance_turnaround(self, turnaround_id, headers, payload=None):
        return self._request("POST", f"/turnarounds/{turnaround_id}/advance", payload or {}, headers)

    def cancel_turnaround(self, turnaround_id, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/cancel", {}, headers)

    def handover_turnaround(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/handover", payload, headers)

    def get_cost_summary(self, turnaround_id, headers):
        return self._request("GET", f"/turnarounds/{turnaround_id}/cost-summary", headers=headers)

    def run_ops(self, turnaround_id, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/run-ops", {}, headers)

    # --- Work items ---
    def create_work_item(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/work-items", payload, headers)

    def list_work_items(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/work-items", headers=headers, params=params)

    def get_work_item(self, work_item_id, headers):
        return self._request("GET", f"/work-items/{work_item_id}", headers=headers)

    def estimate_work_item(self, work_item_id, payload, headers):
        return self._request("POST", f"/work-items/{work_item_id}/estimate", payload, headers)

    def add_dependency(self, work_item_id, payload, headers):
        return self._request("POST", f"/work-items/{work_item_id}/dependencies", payload, headers)

    def list_work_item_dependencies(self, work_item_id, headers):
        return self._request("GET", f"/work-items/{work_item_id}/dependencies", headers=headers)

    def list_turnaround_dependencies(self, turnaround_id, headers):
        return self._request("GET", f"/turnarounds/{turnaround_id}/dependencies", headers=headers)

    def schedule_work_item(self, work_item_id, headers, payload=None):
        return self._request("POST", f"/work-items/{work_item_id}/schedule", payload or {}, headers)

    def start_work_item(self, work_item_id, headers):
        return self._request("POST", f"/work-items/{work_item_id}/start", {}, headers)

    def hold_work_item(self, work_item_id, headers):
        return self._request("POST", f"/work-items/{work_item_id}/hold", {}, headers)

    def complete_work_item(self, work_item_id, payload, headers):
        return self._request("POST", f"/work-items/{work_item_id}/complete", payload, headers)

    def verify_work_item(self, work_item_id, payload, headers):
        return self._request("POST", f"/work-items/{work_item_id}/verify", payload, headers)

    def list_work_item_permits(self, work_item_id, headers):
        return self._request("GET", f"/work-items/{work_item_id}/permits", headers=headers)

    def list_work_item_discoveries(self, work_item_id, headers):
        return self._request("GET", f"/work-items/{work_item_id}/discoveries", headers=headers)

    def list_work_item_punch_items(self, work_item_id, headers):
        return self._request("GET", f"/work-items/{work_item_id}/punch-items", headers=headers)

    # --- Contractors & workers ---
    def create_contractor(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/contractors", payload, headers)

    def list_contractors(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def mobilize_contractor(self, contractor_id, headers):
        return self._request("POST", f"/contractors/{contractor_id}/mobilize", {}, headers)

    def register_worker(self, contractor_id, payload, headers):
        return self._request("POST", f"/contractors/{contractor_id}/workers", payload, headers)

    def list_workers(self, contractor_id, headers, params=None):
        return self._request("GET", f"/contractors/{contractor_id}/workers", headers=headers, params=params)

    def list_contractor_daily_reports(self, contractor_id, headers, params=None):
        return self._request("GET", f"/contractors/{contractor_id}/daily-reports", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    def vet_worker(self, worker_id, headers):
        return self._request("POST", f"/workers/{worker_id}/vet", {}, headers)

    def badge_worker(self, worker_id, headers):
        return self._request("POST", f"/workers/{worker_id}/badge", {}, headers)

    def badge_transition_worker(self, worker_id, payload, headers):
        return self._request("POST", f"/workers/{worker_id}/badge-transition", payload, headers)

    def list_worker_assignments(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}/assignments", headers=headers)

    # --- Shifts & assignments ---
    def create_shift(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/shifts", payload, headers)

    def list_shifts(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shift_work_items(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}/work-items", headers=headers)

    def lock_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/lock", {}, headers)

    def create_assignment(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/assignments", payload, headers)

    def list_shift_assignments(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}/assignments", headers=headers)

    def complete_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/assignments/{assignment_id}/complete", payload, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", {}, headers)

    # --- Permits & isolations ---
    def create_isolation(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/isolations", payload, headers)

    def list_isolations(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/isolations", headers=headers, params=params)

    def get_isolation(self, isolation_id, headers):
        return self._request("GET", f"/isolations/{isolation_id}", headers=headers)

    def transition_isolation(self, isolation_id, payload, headers):
        return self._request("POST", f"/isolations/{isolation_id}/transition", payload, headers)

    def list_isolation_permits(self, isolation_id, headers):
        return self._request("GET", f"/isolations/{isolation_id}/permits", headers=headers)

    def create_permit(self, work_item_id, payload, headers):
        return self._request("POST", f"/work-items/{work_item_id}/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def transition_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/transition", payload, headers)

    # --- Discovery work & change authorization ---
    def create_discovery(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/discoveries", payload, headers)

    def list_discoveries(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/discoveries", headers=headers, params=params)

    def get_discovery(self, discovery_id, headers):
        return self._request("GET", f"/discoveries/{discovery_id}", headers=headers)

    def list_discovery_work_items(self, discovery_id, headers):
        return self._request("GET", f"/discoveries/{discovery_id}/work-items", headers=headers)

    def triage_discovery(self, discovery_id, headers, payload=None):
        return self._request("POST", f"/discoveries/{discovery_id}/triage", payload or {}, headers)

    def decide_discovery(self, discovery_id, payload, headers):
        return self._request("POST", f"/discoveries/{discovery_id}/decide", payload, headers)

    def appeal_discovery(self, discovery_id, headers):
        return self._request("POST", f"/discoveries/{discovery_id}/appeal", {}, headers)

    # --- Lay-down areas & staging ---
    def create_laydown_area(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/laydown-areas", payload, headers)

    def list_laydown_areas(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/laydown-areas", headers=headers, params=params)

    def get_laydown_area(self, area_id, headers):
        return self._request("GET", f"/laydown-areas/{area_id}", headers=headers)

    def create_reservation(self, area_id, payload, headers):
        return self._request("POST", f"/laydown-areas/{area_id}/reservations", payload, headers)

    def list_reservations(self, area_id, headers, params=None):
        return self._request("GET", f"/laydown-areas/{area_id}/reservations", headers=headers, params=params)

    def stage_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/stage", {}, headers)

    def release_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/release", {}, headers)

    # --- Daily cost/progress reports ---
    def create_daily_report(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/daily-reports", payload, headers)

    def list_daily_reports(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/daily-reports", headers=headers, params=params)

    def get_daily_report(self, report_id, headers):
        return self._request("GET", f"/daily-reports/{report_id}", headers=headers)

    def submit_daily_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/submit", {}, headers)

    def approve_daily_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/approve", {}, headers)

    def reject_daily_report(self, report_id, headers, payload=None):
        return self._request("POST", f"/daily-reports/{report_id}/reject", payload or {}, headers)

    def void_daily_report(self, report_id, headers):
        return self._request("POST", f"/daily-reports/{report_id}/void", {}, headers)

    # --- Punch list & handover ---
    def create_punch_item(self, turnaround_id, payload, headers):
        return self._request("POST", f"/turnarounds/{turnaround_id}/punch-items", payload, headers)

    def list_punch_items(self, turnaround_id, headers, params=None):
        return self._request("GET", f"/turnarounds/{turnaround_id}/punch-items", headers=headers, params=params)

    def get_punch_item(self, punch_item_id, headers):
        return self._request("GET", f"/punch-items/{punch_item_id}", headers=headers)

    def ready_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/punch-items/{punch_item_id}/ready", {}, headers)

    def verify_punch_item(self, punch_item_id, payload, headers):
        return self._request("POST", f"/punch-items/{punch_item_id}/verify", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
