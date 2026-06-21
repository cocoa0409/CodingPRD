"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    # --- Site ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    def list_sites(self, headers, params=None):
        return self._request("GET", "/sites", headers=headers, params=params)

    def archive_site(self, site_id, headers):
        return self._request("POST", f"/sites/{site_id}/archive", {}, headers)

    # --- ServiceContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", {}, headers)

    # --- CrewMember ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/crew", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crew/{crew_id}", headers=headers)

    def deactivate_crew(self, crew_id, headers):
        return self._request("POST", f"/crew/{crew_id}/deactivate", {}, headers)

    # --- RecurringSchedule ---
    def create_schedule(self, payload, headers):
        return self._request("POST", "/schedules", payload, headers)

    def get_schedule(self, schedule_id, headers):
        return self._request("GET", f"/schedules/{schedule_id}", headers=headers)

    def list_schedules(self, headers, params=None):
        return self._request("GET", "/schedules", headers=headers, params=params)

    def pause_schedule(self, schedule_id, headers):
        return self._request("POST", f"/schedules/{schedule_id}/pause", {}, headers)

    def resume_schedule(self, schedule_id, headers):
        return self._request("POST", f"/schedules/{schedule_id}/resume", {}, headers)

    # --- Visit ---
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def start_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/start", {}, headers)

    def complete_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/complete", {}, headers)

    def miss_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/miss", {}, headers)

    def cancel_visit(self, visit_id, headers):
        return self._request("POST", f"/visits/{visit_id}/cancel", {}, headers)

    # --- TimeEntry ---
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def clock_out_time_entry(self, time_entry_id, payload, headers):
        return self._request("POST", f"/time-entries/{time_entry_id}/clock-out", payload, headers)

    def void_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/time-entries/{time_entry_id}/void", {}, headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/inspections", headers=headers, params=params)

    # --- PeriodicJob ---
    def create_periodic_job(self, payload, headers):
        return self._request("POST", "/periodic-jobs", payload, headers)

    def get_periodic_job(self, periodic_job_id, headers):
        return self._request("GET", f"/periodic-jobs/{periodic_job_id}", headers=headers)

    def list_periodic_jobs(self, headers, params=None):
        return self._request("GET", "/periodic-jobs", headers=headers, params=params)

    def dispatch_periodic_job(self, periodic_job_id, payload, headers):
        return self._request("POST", f"/periodic-jobs/{periodic_job_id}/dispatch", payload, headers)

    def cancel_periodic_job(self, periodic_job_id, headers):
        return self._request("POST", f"/periodic-jobs/{periodic_job_id}/cancel", {}, headers)

    # --- Complaint ---
    def create_complaint(self, payload, headers):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id, headers):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def list_complaints(self, headers, params=None):
        return self._request("GET", "/complaints", headers=headers, params=params)

    def acknowledge_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/acknowledge", {}, headers)

    def schedule_callback(self, complaint_id, payload, headers):
        return self._request("POST", f"/complaints/{complaint_id}/schedule-callback", payload, headers)

    def resolve_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", {}, headers)

    def reopen_complaint(self, complaint_id, headers):
        return self._request("POST", f"/complaints/{complaint_id}/reopen", {}, headers)

    # --- BillingPeriod ---
    def create_billing_period(self, payload, headers):
        return self._request("POST", "/billing-periods", payload, headers)

    def get_billing_period(self, billing_period_id, headers):
        return self._request("GET", f"/billing-periods/{billing_period_id}", headers=headers)

    def list_billing_periods(self, headers, params=None):
        return self._request("GET", "/billing-periods", headers=headers, params=params)

    def close_billing_period(self, billing_period_id, payload, headers):
        return self._request("POST", f"/billing-periods/{billing_period_id}/close", payload, headers)

    def reopen_billing_period(self, billing_period_id, payload, headers):
        return self._request("POST", f"/billing-periods/{billing_period_id}/reopen", payload, headers)

    def invoice_billing_period(self, billing_period_id, headers):
        return self._request("POST", f"/billing-periods/{billing_period_id}/invoice", {}, headers)

    def list_invoice_lines(self, billing_period_id, headers, params=None):
        return self._request("GET", f"/billing-periods/{billing_period_id}/invoice-lines", headers=headers, params=params)

    # --- SupplyOrder ---
    def create_supply_order(self, payload, headers):
        return self._request("POST", "/supply-orders", payload, headers)

    def get_supply_order(self, supply_order_id, headers):
        return self._request("GET", f"/supply-orders/{supply_order_id}", headers=headers)

    def list_supply_orders(self, headers, params=None):
        return self._request("GET", "/supply-orders", headers=headers, params=params)

    def fulfill_supply_order(self, supply_order_id, headers):
        return self._request("POST", f"/supply-orders/{supply_order_id}/fulfill", {}, headers)

    def cancel_supply_order(self, supply_order_id, headers):
        return self._request("POST", f"/supply-orders/{supply_order_id}/cancel", {}, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers=None):
        return self._request("POST", "/_clock/set", payload, headers)


api_client = ApiClient()
