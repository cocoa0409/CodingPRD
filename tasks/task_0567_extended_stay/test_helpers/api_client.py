"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- CorporateAccount ---
    def create_corporate_account(self, payload, headers):
        return self._request("POST", "/corporate-accounts", payload, headers)

    def get_corporate_account(self, account_id, headers):
        return self._request("GET", f"/corporate-accounts/{account_id}", headers=headers)

    # --- RatePlan ---
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/rate-plans", payload, headers)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/rate-plans/{rate_plan_id}", headers=headers)

    # --- Unit ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    # --- MasterLease ---
    def create_master_lease(self, payload, headers):
        return self._request("POST", "/master-leases", payload, headers)

    def get_master_lease(self, lease_id, headers):
        return self._request("GET", f"/master-leases/{lease_id}", headers=headers)

    def list_master_leases(self, headers, params=None):
        return self._request("GET", "/master-leases", headers=headers, params=params)

    def activate_master_lease(self, lease_id, headers):
        return self._request("POST", f"/master-leases/{lease_id}/activate", {}, headers)

    def suspend_master_lease(self, lease_id, headers):
        return self._request("POST", f"/master-leases/{lease_id}/suspend", {}, headers)

    def resume_master_lease(self, lease_id, headers):
        return self._request("POST", f"/master-leases/{lease_id}/resume", {}, headers)

    def renegotiate_master_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/master-leases/{lease_id}/renegotiate", payload, headers)

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    # --- Stay ---
    def create_stay(self, payload, headers):
        return self._request("POST", "/stays", payload, headers)

    def get_stay(self, stay_id, headers):
        return self._request("GET", f"/stays/{stay_id}", headers=headers)

    def list_stays(self, headers, params=None):
        return self._request("GET", "/stays", headers=headers, params=params)

    def check_in_stay(self, stay_id, headers):
        return self._request("POST", f"/stays/{stay_id}/check-in", {}, headers)

    def depart_stay(self, stay_id, payload, headers):
        return self._request("POST", f"/stays/{stay_id}/depart", payload, headers)

    def cancel_stay(self, stay_id, headers):
        return self._request("POST", f"/stays/{stay_id}/cancel", {}, headers)

    # --- HousekeepingVisit ---
    def create_housekeeping_visit(self, payload, headers):
        return self._request("POST", "/housekeeping-visits", payload, headers)

    def get_housekeeping_visit(self, visit_id, headers):
        return self._request("GET", f"/housekeeping-visits/{visit_id}", headers=headers)

    def list_housekeeping_visits(self, headers, params=None):
        return self._request("GET", "/housekeeping-visits", headers=headers, params=params)

    def complete_housekeeping_visit(self, visit_id, headers):
        return self._request("POST", f"/housekeeping-visits/{visit_id}/complete", {}, headers)

    def cancel_housekeeping_visit(self, visit_id, headers):
        return self._request("POST", f"/housekeeping-visits/{visit_id}/cancel", {}, headers)

    # --- DamageCharge ---
    def create_damage_charge(self, payload, headers):
        return self._request("POST", "/damage-charges", payload, headers)

    def get_damage_charge(self, charge_id, headers):
        return self._request("GET", f"/damage-charges/{charge_id}", headers=headers)

    def list_damage_charges(self, headers, params=None):
        return self._request("GET", "/damage-charges", headers=headers, params=params)

    def charge_damage_charge(self, charge_id, headers):
        return self._request("POST", f"/damage-charges/{charge_id}/charge", {}, headers)

    def dispute_damage_charge(self, charge_id, headers):
        return self._request("POST", f"/damage-charges/{charge_id}/dispute", {}, headers)

    def waive_damage_charge(self, charge_id, headers):
        return self._request("POST", f"/damage-charges/{charge_id}/waive", {}, headers)

    # --- Invoice ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    # --- Turnover ---
    def get_turnover(self, turnover_id, headers):
        return self._request("GET", f"/turnovers/{turnover_id}", headers=headers)

    def list_turnovers(self, headers, params=None):
        return self._request("GET", "/turnovers", headers=headers, params=params)

    def complete_turnover(self, turnover_id, headers):
        return self._request("POST", f"/turnovers/{turnover_id}/complete", {}, headers)


api_client = ApiClient()
