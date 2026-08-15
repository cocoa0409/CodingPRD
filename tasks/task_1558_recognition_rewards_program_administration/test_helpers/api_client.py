"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/api/programs/{program_id}", headers=headers)

    def update_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/api/programs/{program_id}", payload, headers)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/activate", {}, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/api/programs/{program_id}/suspend", {}, headers)

    def run_anniversary_scan(self, program_id, headers):
        return self._request(
            "POST", f"/api/programs/{program_id}/anniversary-scans", {}, headers
        )

    def finalize_tax_year(self, program_id, tax_year, headers):
        return self._request(
            "POST", f"/api/programs/{program_id}/finalize-tax-year",
            {"tax_year": tax_year}, headers,
        )

    def get_participation_analytics(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/api/programs/{program_id}/analytics/participation",
            headers=headers, params=params,
        )

    # --- Departments ---
    def create_department(self, payload, headers):
        return self._request("POST", "/api/departments", payload, headers)

    def get_department(self, department_id, headers):
        return self._request("GET", f"/api/departments/{department_id}", headers=headers)

    # --- Employees ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/api/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/api/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/api/employees", headers=headers, params=params)

    def create_compensation_adjustment(self, employee_id, ytd_supplemental_wages_cents, headers):
        return self._request(
            "POST", f"/api/employees/{employee_id}/compensation-adjustments",
            {"ytd_supplemental_wages_cents": ytd_supplemental_wages_cents}, headers,
        )

    def reinstate_employee(self, employee_id, headers):
        return self._request(
            "POST", f"/api/employees/{employee_id}/reinstate", {}, headers
        )

    def list_ledger_entries(self, employee_id, headers, params=None):
        return self._request(
            "GET", f"/api/employees/{employee_id}/ledger-entries",
            headers=headers, params=params,
        )

    def create_points_adjustment(self, employee_id, payload, headers):
        return self._request(
            "POST", f"/api/employees/{employee_id}/points-adjustments", payload, headers
        )

    # --- Point budgets ---
    def create_budget(self, payload, headers):
        return self._request("POST", "/api/budgets", payload, headers)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/api/budgets/{budget_id}", headers=headers)

    def list_budgets(self, headers, params=None):
        return self._request("GET", "/api/budgets", headers=headers, params=params)

    def create_budget_adjustment(self, budget_id, payload, headers):
        return self._request(
            "POST", f"/api/budgets/{budget_id}/adjustments", payload, headers
        )

    # --- Nominations ---
    def create_nomination(self, payload, headers):
        return self._request("POST", "/api/nominations", payload, headers)

    def get_nomination(self, nomination_id, headers):
        return self._request("GET", f"/api/nominations/{nomination_id}", headers=headers)

    def list_nominations(self, headers, params=None):
        return self._request("GET", "/api/nominations", headers=headers, params=params)

    def approve_nomination(self, nomination_id, expected_nomination_version, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/approve",
            {"expected_nomination_version": expected_nomination_version}, headers,
        )

    def reject_nomination(self, nomination_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/reject", payload, headers
        )

    def return_nomination_for_revision(self, nomination_id, feedback, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/return-for-revision",
            {"feedback": feedback}, headers,
        )

    def resubmit_nomination(self, nomination_id, payload, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/resubmit", payload, headers
        )

    def cancel_nomination(self, nomination_id, headers):
        return self._request(
            "POST", f"/api/nominations/{nomination_id}/cancel", {}, headers
        )

    # --- Awards ---
    def get_award(self, award_id, headers):
        return self._request("GET", f"/api/awards/{award_id}", headers=headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/api/awards", headers=headers, params=params)

    def revoke_award(self, award_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/api/awards/{award_id}/revoke", payload, headers
        )

    # --- Fulfillment vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/api/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/api/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/api/vendors/{vendor_id}/suspend", {}, headers)

    def reactivate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/api/vendors/{vendor_id}/reactivate", {}, headers)

    # --- Catalog items ---
    def create_catalog_item(self, payload, headers):
        return self._request("POST", "/api/catalog-items", payload, headers)

    def get_catalog_item(self, catalog_item_id, headers):
        return self._request("GET", f"/api/catalog-items/{catalog_item_id}", headers=headers)

    def list_catalog_items(self, headers, params=None):
        return self._request("GET", "/api/catalog-items", headers=headers, params=params)

    def update_catalog_item(self, catalog_item_id, payload, headers):
        return self._request(
            "PATCH", f"/api/catalog-items/{catalog_item_id}", payload, headers
        )

    # --- Redemption orders ---
    def create_redemption_order(self, payload, headers):
        return self._request("POST", "/api/redemption-orders", payload, headers)

    def get_redemption_order(self, order_id, headers):
        return self._request(
            "GET", f"/api/redemption-orders/{order_id}", headers=headers
        )

    def list_redemption_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/redemption-orders", headers=headers, params=params
        )

    def submit_redemption_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/redemption-orders/{order_id}/submit", {}, headers
        )

    def mark_redemption_order_shipped(self, order_id, headers):
        return self._request(
            "POST", f"/api/redemption-orders/{order_id}/mark-shipped", {}, headers
        )

    def mark_redemption_order_delivered(self, order_id, headers):
        return self._request(
            "POST", f"/api/redemption-orders/{order_id}/mark-delivered", {}, headers
        )

    def cancel_redemption_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/redemption-orders/{order_id}/cancel", {}, headers
        )

    def request_redemption_order_return(self, order_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/api/redemption-orders/{order_id}/request-return", payload, headers
        )

    def complete_redemption_order_return(self, order_id, headers):
        return self._request(
            "POST", f"/api/redemption-orders/{order_id}/complete-return", {}, headers
        )

    # --- Tax records ---
    def get_tax_record(self, tax_record_id, headers):
        return self._request("GET", f"/api/tax-records/{tax_record_id}", headers=headers)

    def list_tax_records(self, headers, params=None):
        return self._request("GET", "/api/tax-records", headers=headers, params=params)

    # --- Accrual runs ---
    def create_accrual_run(self, payload, headers):
        return self._request("POST", "/api/accrual-runs", payload, headers)

    def get_accrual_run(self, accrual_run_id, headers):
        return self._request(
            "GET", f"/api/accrual-runs/{accrual_run_id}", headers=headers
        )

    def list_accrual_runs(self, headers, params=None):
        return self._request("GET", "/api/accrual-runs", headers=headers, params=params)

    def reconcile_accrual_run(self, accrual_run_id, headers):
        return self._request(
            "POST", f"/api/accrual-runs/{accrual_run_id}/reconcile", {}, headers
        )

    def close_accrual_run(self, accrual_run_id, headers):
        return self._request(
            "POST", f"/api/accrual-runs/{accrual_run_id}/close", {}, headers
        )

    def void_accrual_run(self, accrual_run_id, headers):
        return self._request(
            "POST", f"/api/accrual-runs/{accrual_run_id}/void", {}, headers
        )

    # --- Abuse flags ---
    def create_abuse_flag(self, payload, headers):
        return self._request("POST", "/api/abuse-flags", payload, headers)

    def get_abuse_flag(self, abuse_flag_id, headers):
        return self._request("GET", f"/api/abuse-flags/{abuse_flag_id}", headers=headers)

    def list_abuse_flags(self, headers, params=None):
        return self._request("GET", "/api/abuse-flags", headers=headers, params=params)

    def review_abuse_flag(self, abuse_flag_id, headers):
        return self._request(
            "POST", f"/api/abuse-flags/{abuse_flag_id}/review", {}, headers
        )

    def confirm_abuse_flag(self, abuse_flag_id, headers):
        return self._request(
            "POST", f"/api/abuse-flags/{abuse_flag_id}/confirm", {}, headers
        )

    def dismiss_abuse_flag(self, abuse_flag_id, headers):
        return self._request(
            "POST", f"/api/abuse-flags/{abuse_flag_id}/dismiss", {}, headers
        )

    # --- Anniversary events ---
    def get_anniversary_event(self, anniversary_event_id, headers):
        return self._request(
            "GET", f"/api/anniversary-events/{anniversary_event_id}", headers=headers
        )

    def list_anniversary_events(self, headers, params=None):
        return self._request(
            "GET", "/api/anniversary-events", headers=headers, params=params
        )


api_client = ApiClient()
