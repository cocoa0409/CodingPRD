"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Vessels ---
    def create_vessel(self, payload, headers):
        return self._request("POST", "/yard/vessels", payload, headers)

    def get_vessel(self, vessel_id, headers):
        return self._request("GET", f"/yard/vessels/{vessel_id}",
                             headers=headers)

    def list_vessels(self, headers, params=None):
        return self._request("GET", "/yard/vessels", params or {}, headers)

    # --- Insurance certificates ---
    def create_insurance_certificate(self, payload, headers):
        return self._request("POST", "/yard/insurance-certificates",
                             payload, headers)

    def list_insurance_certificates(self, vessel_id, headers, params=None):
        return self._request("GET",
                             f"/yard/vessels/{vessel_id}/insurance-certificates",
                             params or {}, headers)

    # --- Refit jobs ---
    def create_refit_job(self, payload, headers):
        return self._request("POST", "/yard/refit-jobs", payload, headers)

    def get_refit_job(self, job_id, headers):
        return self._request("GET", f"/yard/refit-jobs/{job_id}",
                             headers=headers)

    def list_refit_jobs(self, vessel_id, headers, params=None):
        return self._request("GET", f"/yard/vessels/{vessel_id}/refit-jobs",
                             params or {}, headers)

    def patch_refit_job(self, job_id, payload, headers):
        return self._request("PATCH", f"/yard/refit-jobs/{job_id}",
                             payload, headers)

    def submit_refit_job(self, job_id, headers):
        return self._request("POST", f"/yard/refit-jobs/{job_id}/submit",
                             {}, headers)

    def cancel_refit_job(self, job_id, headers, payload=None):
        return self._request("POST", f"/yard/refit-jobs/{job_id}/cancel",
                             payload or {}, headers)

    def get_statement(self, job_id, headers):
        return self._request("GET", f"/yard/refit-jobs/{job_id}/statement",
                             headers=headers)

    def record_sea_trial(self, job_id, payload, headers):
        return self._request("POST",
                             f"/yard/refit-jobs/{job_id}/record-sea-trial",
                             payload, headers)

    # --- Lift slots ---
    def create_lift_slot(self, payload, headers):
        return self._request("POST", "/yard/lift-slots", payload, headers)

    def list_lift_slots(self, job_id, headers, params=None):
        return self._request("GET", f"/yard/refit-jobs/{job_id}/lift-slots",
                             params or {}, headers)

    def complete_lift_slot(self, slot_id, headers):
        return self._request("POST", f"/yard/lift-slots/{slot_id}/complete",
                             {}, headers)

    def cancel_lift_slot(self, slot_id, headers):
        return self._request("POST", f"/yard/lift-slots/{slot_id}/cancel",
                             {}, headers)

    # --- Yard rows & stands ---
    def create_yard_row(self, payload, headers):
        return self._request("POST", "/yard/yard-rows", payload, headers)

    def get_yard_row(self, row_id, headers):
        return self._request("GET", f"/yard/yard-rows/{row_id}",
                             headers=headers)

    def create_stand_assignment(self, payload, headers):
        return self._request("POST", "/yard/stand-assignments",
                             payload, headers)

    def get_stand_assignment(self, assignment_id, headers):
        return self._request("GET",
                             f"/yard/stand-assignments/{assignment_id}",
                             headers=headers)

    def list_stand_assignments(self, headers, params=None):
        return self._request("GET", "/yard/stand-assignments",
                             params or {}, headers)

    def release_stand_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/yard/stand-assignments/{assignment_id}/release",
            {}, headers)

    # --- Work orders & labor ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/yard/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/yard/work-orders/{work_order_id}",
                             headers=headers)

    def list_work_orders(self, job_id, headers, params=None):
        return self._request("GET", f"/yard/refit-jobs/{job_id}/work-orders",
                             params or {}, headers)

    def approve_work_order(self, work_order_id, headers):
        return self._request("POST",
                             f"/yard/work-orders/{work_order_id}/approve",
                             {}, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST",
                             f"/yard/work-orders/{work_order_id}/start",
                             {}, headers)

    def request_change_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST", f"/yard/work-orders/{work_order_id}/request-change",
            payload, headers)

    def requote_work_order(self, work_order_id, payload, headers):
        return self._request("POST",
                             f"/yard/work-orders/{work_order_id}/requote",
                             payload, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST",
                             f"/yard/work-orders/{work_order_id}/complete",
                             {}, headers)

    def create_labor_entry(self, payload, headers):
        return self._request("POST", "/yard/labor-entries", payload, headers)

    def list_labor_entries(self, work_order_id, headers, params=None):
        return self._request("GET",
                             f"/yard/work-orders/{work_order_id}/labor-entries",
                             params or {}, headers)

    # --- Parts ---
    def create_part(self, payload, headers):
        return self._request("POST", "/yard/parts", payload, headers)

    def list_parts(self, job_id, headers, params=None):
        return self._request("GET", f"/yard/refit-jobs/{job_id}/parts",
                             params or {}, headers)

    def inspect_part(self, part_id, payload, headers):
        return self._request("POST", f"/yard/parts/{part_id}/inspect",
                             payload, headers)

    # --- Environmental events & compliance holds ---
    def create_environmental_event(self, payload, headers):
        return self._request("POST", "/yard/environmental-events",
                             payload, headers)

    def list_environmental_events(self, job_id, headers, params=None):
        return self._request(
            "GET", f"/yard/refit-jobs/{job_id}/environmental-events",
            params or {}, headers)

    def remediate_environmental_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/yard/environmental-events/{event_id}/remediate",
            payload, headers)

    def create_compliance_hold(self, payload, headers):
        return self._request("POST", "/yard/compliance-holds",
                             payload, headers)

    def list_compliance_holds(self, job_id, headers, params=None):
        return self._request("GET",
                             f"/yard/refit-jobs/{job_id}/compliance-holds",
                             params or {}, headers)

    def release_compliance_hold(self, hold_id, headers):
        return self._request("POST",
                             f"/yard/compliance-holds/{hold_id}/release",
                             {}, headers)

    # --- Ledger ---
    def create_ledger_entry(self, payload, headers):
        return self._request("POST", "/yard/ledger-entries", payload, headers)

    def list_ledger_entries(self, job_id, headers, params=None):
        return self._request("GET",
                             f"/yard/refit-jobs/{job_id}/ledger-entries",
                             params or {}, headers)

    def void_ledger_entry(self, entry_id, headers):
        return self._request("POST", f"/yard/ledger-entries/{entry_id}/void",
                             {}, headers)

    # --- Ops & logical clock ---
    def run_daily_close(self, headers):
        return self._request("POST", "/yard/ops/run-daily-close", {}, headers)

    def set_current_utc(self, payload, headers):
        return self._request("POST", "/yard/_clock/set_current_utc",
                             payload, headers)


api_client = ApiClient()
