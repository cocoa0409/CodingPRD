"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def update_employer(self, employer_id, payload, headers):
        return self._request("PATCH", f"/employers/{employer_id}", payload, headers)

    # --- StateRule admin ---
    def create_state_rule(self, payload, headers):
        return self._request("POST", "/state-rules", payload, headers)

    def get_state_rule(self, state_code, headers):
        return self._request("GET", f"/state-rules/{state_code}", headers=headers)

    # --- IssuingAuthority ---
    def create_authority(self, payload, headers):
        return self._request("POST", "/authorities", payload, headers)

    def get_authority(self, authority_id, headers):
        return self._request("GET", f"/authorities/{authority_id}", headers=headers)

    def list_authority_remittances(self, authority_id, headers, params=None):
        return self._request(
            "GET", f"/authorities/{authority_id}/remittances", headers=headers, params=params
        )

    def list_authority_orders(self, authority_id, headers, params=None):
        return self._request(
            "GET", f"/authorities/{authority_id}/orders", headers=headers, params=params
        )

    # --- Flat filtered listings ---
    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/statements", headers=headers, params=params)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    def list_payroll_runs(self, headers, params=None):
        return self._request("GET", "/payroll-runs", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/remittances", headers=headers, params=params)

    def get_audit_entry(self, entry_id, headers):
        return self._request("GET", f"/audit-log/{entry_id}", headers=headers)

    def list_audit_log(self, headers, params=None):
        return self._request("GET", "/audit-log", headers=headers, params=params)

    def list_statement_events(self, statement_id, headers, params=None):
        return self._request(
            "GET", f"/statements/{statement_id}/events", headers=headers, params=params
        )

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employer_employees(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/employers/{employer_id}/employees", headers=headers, params=params
        )

    def list_employee_orders(self, employee_id, headers, params=None):
        return self._request(
            "GET", f"/employees/{employee_id}/orders", headers=headers, params=params
        )

    def terminate_employee(self, employee_id, payload, headers):
        return self._request(
            "POST", f"/employees/{employee_id}/terminate", payload, headers
        )

    # --- GarnishmentOrder ---
    def create_order(self, employee_id, payload, headers):
        return self._request("POST", f"/employees/{employee_id}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def validate_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/validate", {}, headers)

    def reject_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/reject", payload, headers)

    def notify_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/notify", {}, headers)

    def activate_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/activate", {}, headers)

    def suspend_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/suspend", payload, headers)

    def resume_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/resume", {}, headers)

    def answer_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/answer", payload, headers)

    def terminate_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/terminate", payload, headers)

    def refund_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/refund", payload, headers)

    def list_order_events(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/orders/{order_id}/events", headers=headers, params=params
        )

    # --- PayrollRun / PayStatement ---
    def create_payroll_run(self, payload, headers):
        return self._request("POST", "/payroll-runs", payload, headers)

    def get_payroll_run(self, run_id, headers):
        return self._request("GET", f"/payroll-runs/{run_id}", headers=headers)

    def list_employer_payroll_runs(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/employers/{employer_id}/payroll-runs", headers=headers, params=params
        )

    def create_statement(self, run_id, payload, headers):
        return self._request(
            "POST", f"/payroll-runs/{run_id}/statements", payload, headers
        )

    def list_run_statements(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/payroll-runs/{run_id}/statements", headers=headers, params=params
        )

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/statements/{statement_id}", headers=headers)

    def pay_run(self, run_id, payload, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/pay", payload, headers)

    def void_run(self, run_id, headers):
        return self._request("POST", f"/payroll-runs/{run_id}/void", {}, headers)

    def list_run_events(self, run_id, headers, params=None):
        return self._request(
            "GET", f"/payroll-runs/{run_id}/events", headers=headers, params=params
        )

    # --- Remittance ---
    def create_remittance(self, payload, headers):
        return self._request("POST", "/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/remittances/{remittance_id}", headers=headers)

    def list_employer_remittances(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/employers/{employer_id}/remittances", headers=headers, params=params
        )

    def confirm_remittance(self, remittance_id, headers):
        return self._request("POST", f"/remittances/{remittance_id}/confirm", {}, headers)

    def cancel_remittance(self, remittance_id, headers):
        return self._request("POST", f"/remittances/{remittance_id}/cancel", {}, headers)

    # --- Audit ---
    def list_employer_audit_log(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/employers/{employer_id}/audit-log", headers=headers, params=params
        )


api_client = ApiClient()
