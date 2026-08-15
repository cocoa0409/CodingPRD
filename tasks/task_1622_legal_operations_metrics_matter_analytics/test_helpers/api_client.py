"""API client: one method per endpoint defined in the PRD (all under /legal-ops)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/legal-ops/departments", payload, headers)

    def list_departments(self, headers, params=None):
        return self._request("GET", "/legal-ops/departments", headers=headers, params=params)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/legal-ops/departments/{department_id}", headers=headers)

    def update_department(self, department_id, payload, headers):
        return self._request("PATCH", f"/legal-ops/departments/{department_id}", payload, headers)

    # --- Fiscal periods ---
    def create_fiscal_period(self, payload, headers):
        return self._request("POST", "/legal-ops/fiscal-periods", payload, headers)

    def list_fiscal_periods(self, headers, params=None):
        return self._request("GET", "/legal-ops/fiscal-periods", headers=headers, params=params)

    def get_fiscal_period(self, period_id, headers):
        return self._request("GET", f"/legal-ops/fiscal-periods/{period_id}", headers=headers)

    def soft_close_fiscal_period(self, period_id, headers):
        return self._request("POST", f"/legal-ops/fiscal-periods/{period_id}/soft-close", {}, headers)

    def hard_close_fiscal_period(self, period_id, headers):
        return self._request("POST", f"/legal-ops/fiscal-periods/{period_id}/hard-close", {}, headers)

    def reopen_fiscal_period(self, period_id, headers):
        return self._request("POST", f"/legal-ops/fiscal-periods/{period_id}/reopen", {}, headers)

    # --- Practice areas ---
    def create_practice_area(self, payload, headers):
        return self._request("POST", "/legal-ops/practice-areas", payload, headers)

    def list_practice_areas(self, headers, params=None):
        return self._request("GET", "/legal-ops/practice-areas", headers=headers, params=params)

    def get_practice_area(self, practice_area_id, headers):
        return self._request("GET", f"/legal-ops/practice-areas/{practice_area_id}", headers=headers)

    def archive_practice_area(self, practice_area_id, headers):
        return self._request("POST", f"/legal-ops/practice-areas/{practice_area_id}/archive", {}, headers)

    # --- Matter types ---
    def create_matter_type(self, practice_area_id, payload, headers):
        return self._request(
            "POST", f"/legal-ops/practice-areas/{practice_area_id}/matter-types", payload, headers
        )

    def list_matter_types(self, practice_area_id, headers, params=None):
        return self._request(
            "GET", f"/legal-ops/practice-areas/{practice_area_id}/matter-types",
            headers=headers, params=params,
        )

    def get_matter_type(self, matter_type_id, headers):
        return self._request("GET", f"/legal-ops/matter-types/{matter_type_id}", headers=headers)

    # --- Outside counsel firms ---
    def create_firm(self, payload, headers):
        return self._request("POST", "/legal-ops/firms", payload, headers)

    def list_firms(self, headers, params=None):
        return self._request("GET", "/legal-ops/firms", headers=headers, params=params)

    def get_firm(self, firm_id, headers):
        return self._request("GET", f"/legal-ops/firms/{firm_id}", headers=headers)

    def suspend_firm(self, firm_id, headers):
        return self._request("POST", f"/legal-ops/firms/{firm_id}/suspend", {}, headers)

    # --- In-house counsel ---
    def create_counsel(self, payload, headers):
        return self._request("POST", "/legal-ops/in-house-counsel", payload, headers)

    def list_counsel(self, headers, params=None):
        return self._request("GET", "/legal-ops/in-house-counsel", headers=headers, params=params)

    def get_counsel(self, counsel_id, headers):
        return self._request("GET", f"/legal-ops/in-house-counsel/{counsel_id}", headers=headers)

    def get_counsel_utilization(self, counsel_id, headers):
        return self._request(
            "GET", f"/legal-ops/in-house-counsel/{counsel_id}/utilization", headers=headers
        )

    # --- Matters ---
    def create_matter(self, payload, headers):
        return self._request("POST", "/legal-ops/matters", payload, headers)

    def list_matters(self, headers, params=None):
        return self._request("GET", "/legal-ops/matters", headers=headers, params=params)

    def get_matter(self, matter_id, headers):
        return self._request("GET", f"/legal-ops/matters/{matter_id}", headers=headers)

    def update_matter(self, matter_id, payload, headers):
        return self._request("PATCH", f"/legal-ops/matters/{matter_id}", payload, headers)

    def activate_matter(self, matter_id, headers):
        return self._request("POST", f"/legal-ops/matters/{matter_id}/activate", {}, headers)

    def hold_matter(self, matter_id, headers):
        return self._request("POST", f"/legal-ops/matters/{matter_id}/hold", {}, headers)

    def resume_matter(self, matter_id, headers):
        return self._request("POST", f"/legal-ops/matters/{matter_id}/resume", {}, headers)

    def close_matter(self, matter_id, payload, headers):
        return self._request("POST", f"/legal-ops/matters/{matter_id}/close", payload, headers)

    def reopen_matter(self, matter_id, headers):
        return self._request("POST", f"/legal-ops/matters/{matter_id}/reopen", {}, headers)

    def archive_matter(self, matter_id, headers):
        return self._request("POST", f"/legal-ops/matters/{matter_id}/archive", {}, headers)

    def get_matter_cost_model(self, matter_id, headers):
        return self._request("GET", f"/legal-ops/matters/{matter_id}/cost-model", headers=headers)

    # --- Matter assignments ---
    def create_assignment(self, matter_id, payload, headers):
        return self._request("POST", f"/legal-ops/matters/{matter_id}/assignments", payload, headers)

    def list_matter_assignments(self, matter_id, headers, params=None):
        return self._request(
            "GET", f"/legal-ops/matters/{matter_id}/assignments", headers=headers, params=params
        )

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/legal-ops/matter-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/legal-ops/matter-assignments/{assignment_id}", headers=headers)

    def release_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/legal-ops/matter-assignments/{assignment_id}/release", {}, headers
        )

    # --- Budgets ---
    def create_budget(self, payload, headers):
        return self._request("POST", "/legal-ops/budgets", payload, headers)

    def list_budgets(self, headers, params=None):
        return self._request("GET", "/legal-ops/budgets", headers=headers, params=params)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/legal-ops/budgets/{budget_id}", headers=headers)

    def update_budget(self, budget_id, payload, headers):
        return self._request("PATCH", f"/legal-ops/budgets/{budget_id}", payload, headers)

    # --- Accruals ---
    def create_accrual(self, payload, headers):
        return self._request("POST", "/legal-ops/accruals", payload, headers)

    def list_accruals(self, headers, params=None):
        return self._request("GET", "/legal-ops/accruals", headers=headers, params=params)

    def get_accrual(self, accrual_id, headers):
        return self._request("GET", f"/legal-ops/accruals/{accrual_id}", headers=headers)

    def release_accrual(self, accrual_id, headers):
        return self._request("POST", f"/legal-ops/accruals/{accrual_id}/release", {}, headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/legal-ops/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/legal-ops/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/legal-ops/invoices/{invoice_id}", headers=headers)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/legal-ops/invoices/{invoice_id}/approve", {}, headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/legal-ops/invoices/{invoice_id}/pay", {}, headers)

    def reject_invoice(self, invoice_id, headers):
        return self._request("POST", f"/legal-ops/invoices/{invoice_id}/reject", {}, headers)

    # --- Spend lines (read-only ledger) ---
    def list_spend_lines(self, headers, params=None):
        return self._request("GET", "/legal-ops/spend-lines", headers=headers, params=params)

    def get_spend_line(self, spend_line_id, headers):
        return self._request("GET", f"/legal-ops/spend-lines/{spend_line_id}", headers=headers)

    # --- Dashboards ---
    def create_dashboard(self, payload, headers):
        return self._request("POST", "/legal-ops/dashboards", payload, headers)

    def list_dashboards(self, headers, params=None):
        return self._request("GET", "/legal-ops/dashboards", headers=headers, params=params)

    def get_dashboard(self, dashboard_id, headers):
        return self._request("GET", f"/legal-ops/dashboards/{dashboard_id}", headers=headers)

    def publish_dashboard(self, dashboard_id, payload, headers):
        return self._request(
            "POST", f"/legal-ops/dashboards/{dashboard_id}/publish", payload, headers
        )

    # --- Reporting (computed reads) ---
    def get_spend_by_practice_area(self, headers, params=None):
        return self._request(
            "GET", "/legal-ops/reports/spend-by-practice-area", headers=headers, params=params
        )

    def get_spend_by_firm(self, headers, params=None):
        return self._request(
            "GET", "/legal-ops/reports/spend-by-firm", headers=headers, params=params
        )

    def get_cycle_time_benchmark(self, headers, params=None):
        return self._request(
            "GET", "/legal-ops/reports/cycle-time-benchmark", headers=headers, params=params
        )

    # --- Test-driving logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/legal-ops/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
