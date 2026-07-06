"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Client CRUD + onboarding / engagement ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def schedule_kickoff(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/schedule-kickoff", {}, headers)

    def start_ledger_setup(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/start-ledger-setup", {}, headers)

    def complete_onboarding(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/complete-onboarding", {}, headers)

    def activate_engagement(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/activate-engagement", {}, headers)

    def pause_engagement(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/pause-engagement", {}, headers)

    def offboard(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/offboard", {}, headers)

    # --- LedgerAccount ---
    def create_ledger_account(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/ledger-accounts", payload, headers)

    def list_ledger_accounts(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/ledger-accounts",
                             headers=headers, params=params)

    def get_ledger_account(self, account_id, headers):
        return self._request("GET", f"/ledger-accounts/{account_id}", headers=headers)

    def list_ledger_account_children(self, account_id, headers, params=None):
        return self._request("GET", f"/ledger-accounts/{account_id}/children",
                             headers=headers, params=params)

    def archive_ledger_account(self, account_id, headers):
        return self._request("POST", f"/ledger-accounts/{account_id}/archive", {}, headers)

    # --- CatchupProject ---
    def create_catchup_project(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/catchup-projects", payload, headers)

    def list_catchup_projects(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/catchup-projects",
                             headers=headers, params=params)

    def get_catchup_project(self, project_id, headers):
        return self._request("GET", f"/catchup-projects/{project_id}", headers=headers)

    def scope_catchup_project(self, project_id, headers):
        return self._request("POST", f"/catchup-projects/{project_id}/scope", {}, headers)

    def start_catchup_project(self, project_id, headers):
        return self._request("POST", f"/catchup-projects/{project_id}/start", {}, headers)

    def submit_catchup_for_review(self, project_id, headers):
        return self._request("POST", f"/catchup-projects/{project_id}/submit-for-review", {}, headers)

    def reject_catchup_project(self, project_id, headers):
        return self._request("POST", f"/catchup-projects/{project_id}/reject", {}, headers)

    def approve_catchup_project(self, project_id, headers):
        return self._request("POST", f"/catchup-projects/{project_id}/approve", {}, headers)

    def cancel_catchup_project(self, project_id, headers):
        return self._request("POST", f"/catchup-projects/{project_id}/cancel", {}, headers)

    # --- MonthlyClose + CloseTask ---
    def create_monthly_close(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/monthly-closes", payload, headers)

    def list_monthly_closes(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/monthly-closes",
                             headers=headers, params=params)

    def get_monthly_close(self, close_id, headers):
        return self._request("GET", f"/monthly-closes/{close_id}", headers=headers)

    def create_close_task(self, close_id, payload, headers):
        return self._request("POST", f"/monthly-closes/{close_id}/close-tasks", payload, headers)

    def list_close_tasks(self, close_id, headers, params=None):
        return self._request("GET", f"/monthly-closes/{close_id}/close-tasks",
                             headers=headers, params=params)

    def list_close_payroll_runs(self, close_id, headers, params=None):
        return self._request("GET", f"/monthly-closes/{close_id}/payroll-runs",
                             headers=headers, params=params)

    def list_close_retainer_invoices(self, close_id, headers, params=None):
        return self._request("GET", f"/monthly-closes/{close_id}/retainer-invoices",
                             headers=headers, params=params)

    def transition_close_task(self, task_id, payload, headers):
        return self._request("POST", f"/close-tasks/{task_id}/transition", payload, headers)

    def approve_review(self, close_id, headers):
        return self._request("POST", f"/monthly-closes/{close_id}/approve-review", {}, headers)

    def request_changes(self, close_id, payload, headers):
        return self._request("POST", f"/monthly-closes/{close_id}/request-changes", payload, headers)

    def finalize_close(self, close_id, headers):
        return self._request("POST", f"/monthly-closes/{close_id}/finalize", {}, headers)

    # --- ARInvoice ---
    def create_ar_invoice(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/ar-invoices", payload, headers)

    def list_ar_invoices(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/ar-invoices",
                             headers=headers, params=params)

    def get_ar_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ar-invoices/{invoice_id}", headers=headers)

    def dispute_ar_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ar-invoices/{invoice_id}/dispute", {}, headers)

    def resolve_ar_dispute(self, invoice_id, headers):
        return self._request("POST", f"/ar-invoices/{invoice_id}/resolve-dispute", {}, headers)

    def record_ar_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/ar-invoices/{invoice_id}/record-payment", payload, headers)

    def write_off_ar_invoice(self, invoice_id, headers):
        return self._request("POST", f"/ar-invoices/{invoice_id}/write-off", {}, headers)

    def get_ar_summary(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/ar-summary",
                             headers=headers, params=params)

    # --- APBill ---
    def create_ap_bill(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/ap-bills", payload, headers)

    def list_ap_bills(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/ap-bills",
                             headers=headers, params=params)

    def get_ap_bill(self, bill_id, headers):
        return self._request("GET", f"/ap-bills/{bill_id}", headers=headers)

    def approve_ap_bill(self, bill_id, headers):
        return self._request("POST", f"/ap-bills/{bill_id}/approve", {}, headers)

    def schedule_ap_bill(self, bill_id, payload, headers):
        return self._request("POST", f"/ap-bills/{bill_id}/schedule", payload, headers)

    def mark_ap_bill_paid(self, bill_id, headers):
        return self._request("POST", f"/ap-bills/{bill_id}/mark-paid", {}, headers)

    def void_ap_bill(self, bill_id, headers):
        return self._request("POST", f"/ap-bills/{bill_id}/void", {}, headers)

    # --- PayrollRun + PayrollAllocation ---
    def create_payroll_run(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/payroll-runs", payload, headers)

    def list_payroll_runs(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/payroll-runs",
                             headers=headers, params=params)

    def get_payroll_run(self, run_id, headers):
        return self._request("GET", f"/payroll-runs/{run_id}", headers=headers)

    def create_payroll_allocation(self, run_id, payload, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/allocations", payload, headers)

    def list_payroll_allocations(self, run_id, headers, params=None):
        return self._request("GET", f"/payroll-runs/{run_id}/allocations",
                             headers=headers, params=params)

    def allocate_payroll_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/allocate", {}, headers)

    def post_payroll_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/post", {}, headers)

    def reverse_payroll_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/reverse", {}, headers)

    # --- CashFlowForecast + ForecastLine ---
    def create_forecast(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/forecasts", payload, headers)

    def list_forecasts(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/forecasts",
                             headers=headers, params=params)

    def get_forecast(self, forecast_id, headers):
        return self._request("GET", f"/forecasts/{forecast_id}", headers=headers)

    def create_forecast_line(self, forecast_id, payload, headers):
        return self._request("POST", f"/forecasts/{forecast_id}/lines", payload, headers)

    def list_forecast_lines(self, forecast_id, headers, params=None):
        return self._request("GET", f"/forecasts/{forecast_id}/lines",
                             headers=headers, params=params)

    def approve_forecast(self, forecast_id, payload, headers):
        return self._request("POST", f"/forecasts/{forecast_id}/approve", payload, headers)

    # --- TaxHandoff ---
    def create_tax_handoff(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/tax-handoffs", payload, headers)

    def list_tax_handoffs(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/tax-handoffs",
                             headers=headers, params=params)

    def get_tax_handoff(self, handoff_id, headers):
        return self._request("GET", f"/tax-handoffs/{handoff_id}", headers=headers)

    def start_tax_reviews(self, handoff_id, headers):
        return self._request("POST", f"/tax-handoffs/{handoff_id}/start-reviews", {}, headers)

    def books_signoff(self, handoff_id, headers):
        return self._request("POST", f"/tax-handoffs/{handoff_id}/books-signoff", {}, headers)

    def advisory_signoff(self, handoff_id, headers):
        return self._request("POST", f"/tax-handoffs/{handoff_id}/advisory-signoff", {}, headers)

    def deliver_tax_handoff(self, handoff_id, headers):
        return self._request("POST", f"/tax-handoffs/{handoff_id}/deliver", {}, headers)

    def mark_tax_handoff_returned(self, handoff_id, headers):
        return self._request("POST", f"/tax-handoffs/{handoff_id}/mark-returned", {}, headers)

    # --- RetainerInvoice ---
    def issue_retainer_invoice(self, client_id, payload, headers):
        return self._request("POST", f"/clients/{client_id}/retainer-invoices", payload, headers)

    def list_retainer_invoices(self, client_id, headers, params=None):
        return self._request("GET", f"/clients/{client_id}/retainer-invoices",
                             headers=headers, params=params)

    def get_retainer_invoice(self, invoice_id, headers):
        return self._request("GET", f"/retainer-invoices/{invoice_id}", headers=headers)

    def pay_retainer_invoice(self, invoice_id, headers):
        return self._request("POST", f"/retainer-invoices/{invoice_id}/pay", {}, headers)


api_client = ApiClient()
