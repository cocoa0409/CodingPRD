"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Employee ────────────────────────────────────────────────────
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def update_employee_status(self, employee_id, payload, headers):
        return self._request("PATCH", f"/employees/{employee_id}/status", payload, headers)

    # ─── W4Form ──────────────────────────────────────────────────────
    def create_w4_form(self, payload, headers):
        return self._request("POST", "/w4-forms", payload, headers)

    def file_w4_form(self, w4_id, headers):
        return self._request("POST", f"/w4-forms/{w4_id}/file", headers=headers)

    def get_w4_form(self, w4_id, headers):
        return self._request("GET", f"/w4-forms/{w4_id}", headers=headers)

    def list_w4_forms(self, headers, params=None):
        return self._request("GET", "/w4-forms", headers=headers, params=params)

    # ─── PaycheckRun ─────────────────────────────────────────────────
    def create_paycheck_run(self, payload, headers):
        return self._request("POST", "/paycheck-runs", payload, headers)

    def approve_paycheck_run(self, run_id, headers):
        return self._request("POST", f"/paycheck-runs/{run_id}/approve", headers=headers)

    def reject_paycheck_run(self, run_id, headers):
        return self._request("POST", f"/paycheck-runs/{run_id}/reject", headers=headers)

    def pay_paycheck_run(self, run_id, payload, headers):
        return self._request("POST", f"/paycheck-runs/{run_id}/pay", payload, headers)

    def void_paycheck_run(self, run_id, headers):
        return self._request("POST", f"/paycheck-runs/{run_id}/void", headers=headers)

    def get_paycheck_run(self, run_id, headers):
        return self._request("GET", f"/paycheck-runs/{run_id}", headers=headers)

    def list_paycheck_runs(self, headers, params=None):
        return self._request("GET", "/paycheck-runs", headers=headers, params=params)

    def list_paychecks_for_run(self, run_id, headers, params=None):
        return self._request("GET", f"/paycheck-runs/{run_id}/paychecks", headers=headers, params=params)

    # ─── Paycheck ────────────────────────────────────────────────────
    def create_paycheck(self, payload, headers):
        return self._request("POST", "/paychecks", payload, headers)

    def get_paycheck(self, paycheck_id, headers):
        return self._request("GET", f"/paychecks/{paycheck_id}", headers=headers)

    def list_paychecks(self, headers, params=None):
        return self._request("GET", "/paychecks", headers=headers, params=params)

    def list_garnishment_deductions_for_paycheck(self, paycheck_id, headers, params=None):
        return self._request("GET", f"/paychecks/{paycheck_id}/garnishment-deductions", headers=headers, params=params)

    # ─── GarnishmentOrder ────────────────────────────────────────────
    def create_garnishment_order(self, payload, headers):
        return self._request("POST", "/garnishment-orders", payload, headers)

    def suspend_garnishment_order(self, order_id, headers):
        return self._request("POST", f"/garnishment-orders/{order_id}/suspend", headers=headers)

    def reactivate_garnishment_order(self, order_id, headers):
        return self._request("POST", f"/garnishment-orders/{order_id}/reactivate", headers=headers)

    def release_garnishment_order(self, order_id, headers):
        return self._request("POST", f"/garnishment-orders/{order_id}/release", headers=headers)

    def get_garnishment_order(self, order_id, headers):
        return self._request("GET", f"/garnishment-orders/{order_id}", headers=headers)

    def list_garnishment_orders(self, headers, params=None):
        return self._request("GET", "/garnishment-orders", headers=headers, params=params)

    # ─── GarnishmentDeduction ────────────────────────────────────────
    def get_garnishment_deduction(self, deduction_id, headers):
        return self._request("GET", f"/garnishment-deductions/{deduction_id}", headers=headers)

    def list_garnishment_deductions(self, headers, params=None):
        return self._request("GET", "/garnishment-deductions", headers=headers, params=params)

    # ─── Remittance ──────────────────────────────────────────────────
    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/remittances/{remittance_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/remittances", headers=headers, params=params)

    def close_remittance_period(self, remittance_id, headers):
        return self._request("POST", f"/remittances/{remittance_id}/close-period", headers=headers)

    def remit_remittance(self, remittance_id, payload, headers):
        return self._request("POST", f"/remittances/{remittance_id}/remit", payload, headers)

    # ─── TaxRateTable ────────────────────────────────────────────────
    def create_tax_rate_table(self, payload, headers):
        return self._request("POST", "/tax-rate-tables", payload, headers)

    def list_tax_rate_tables(self, headers, params=None):
        return self._request("GET", "/tax-rate-tables", headers=headers, params=params)

    # ─── Test-driving endpoints (PRD §2.10) ──────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def set_employee_ytd(self, employee_id, payload, headers):
        return self._request("POST", f"/_employees/{employee_id}/set_ytd", payload, headers)


api_client = ApiClient()
