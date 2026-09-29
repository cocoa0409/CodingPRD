"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint surface for the tip pooling / tip credit API."""

    # ------------------------------------------------------------------
    # Locations
    # ------------------------------------------------------------------
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Job roles
    # ------------------------------------------------------------------
    def create_job_role(self, payload, headers):
        return self._request("POST", "/job-roles", payload, headers)

    def get_job_role(self, job_role_id, headers):
        return self._request("GET", f"/job-roles/{job_role_id}", headers=headers)

    def list_job_roles(self, headers, params=None):
        return self._request("GET", "/job-roles", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def list_employees(self, headers, params=None):
        return self._request("GET", "/employees", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Role assignments
    # ------------------------------------------------------------------
    def create_role_assignment(self, payload, headers):
        return self._request("POST", "/role-assignments", payload, headers)

    def get_role_assignment(self, role_assignment_id, headers):
        return self._request(
            "GET", f"/role-assignments/{role_assignment_id}", headers=headers
        )

    def list_role_assignments(self, headers, params=None):
        return self._request("GET", "/role-assignments", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Tip pool policies
    # ------------------------------------------------------------------
    def create_tip_pool_policy(self, payload, headers):
        return self._request("POST", "/tip-pool-policies", payload, headers)

    def get_tip_pool_policy(self, policy_id, headers):
        return self._request("GET", f"/tip-pool-policies/{policy_id}", headers=headers)

    def list_tip_pool_policies(self, headers, params=None):
        return self._request(
            "GET", "/tip-pool-policies", headers=headers, params=params
        )

    def activate_tip_pool_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/tip-pool-policies/{policy_id}/activate", payload, headers
        )

    # ------------------------------------------------------------------
    # Pay periods
    # ------------------------------------------------------------------
    def create_pay_period(self, payload, headers):
        return self._request("POST", "/pay-periods", payload, headers)

    def get_pay_period(self, pay_period_id, headers):
        return self._request("GET", f"/pay-periods/{pay_period_id}", headers=headers)

    def list_pay_periods(self, headers, params=None):
        return self._request("GET", "/pay-periods", headers=headers, params=params)

    def compute_pay_period(self, pay_period_id, headers, payload=None):
        return self._request(
            "POST", f"/pay-periods/{pay_period_id}/compute", payload or {}, headers
        )

    def approve_pay_period(self, pay_period_id, headers, payload=None):
        return self._request(
            "POST", f"/pay-periods/{pay_period_id}/approve", payload or {}, headers
        )

    def reopen_pay_period(self, pay_period_id, headers, payload=None):
        return self._request(
            "POST", f"/pay-periods/{pay_period_id}/reopen", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Shifts
    # ------------------------------------------------------------------
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def close_shift(self, shift_id, headers, payload=None):
        return self._request(
            "POST", f"/shifts/{shift_id}/close", payload or {}, headers
        )

    def declare_tips(self, shift_id, payload, headers):
        return self._request(
            "POST", f"/shifts/{shift_id}/declare-tips", payload, headers
        )

    def void_shift(self, shift_id, headers, payload=None):
        return self._request("POST", f"/shifts/{shift_id}/void", payload or {}, headers)

    # ------------------------------------------------------------------
    # Service charges
    # ------------------------------------------------------------------
    def create_service_charge(self, payload, headers):
        return self._request("POST", "/service-charges", payload, headers)

    def get_service_charge(self, service_charge_id, headers):
        return self._request(
            "GET", f"/service-charges/{service_charge_id}", headers=headers
        )

    def list_service_charges(self, headers, params=None):
        return self._request("GET", "/service-charges", headers=headers, params=params)

    def void_service_charge(self, service_charge_id, headers, payload=None):
        return self._request(
            "POST", f"/service-charges/{service_charge_id}/void", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Shift tip pools
    # ------------------------------------------------------------------
    def create_shift_tip_pool(self, payload, headers):
        return self._request("POST", "/shift-tip-pools", payload, headers)

    def get_shift_tip_pool(self, pool_id, headers):
        return self._request("GET", f"/shift-tip-pools/{pool_id}", headers=headers)

    def list_shift_tip_pools(self, headers, params=None):
        return self._request("GET", "/shift-tip-pools", headers=headers, params=params)

    def distribute_shift_tip_pool(self, pool_id, headers, payload=None):
        return self._request(
            "POST", f"/shift-tip-pools/{pool_id}/distribute", payload or {}, headers
        )

    def reverse_shift_tip_pool(self, pool_id, headers, payload=None):
        return self._request(
            "POST", f"/shift-tip-pools/{pool_id}/reverse", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Pool allocations (append-only ledger, read only)
    # ------------------------------------------------------------------
    def get_pool_allocation(self, allocation_id, headers):
        return self._request(
            "GET", f"/pool-allocations/{allocation_id}", headers=headers
        )

    def list_pool_allocations(self, headers, params=None):
        return self._request("GET", "/pool-allocations", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Pay lines
    # ------------------------------------------------------------------
    def get_pay_line(self, pay_line_id, headers):
        return self._request("GET", f"/pay-lines/{pay_line_id}", headers=headers)

    def list_pay_lines(self, headers, params=None):
        return self._request("GET", "/pay-lines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/disputes", headers=headers, params=params)

    def adjudicate_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/disputes/{dispute_id}/adjudicate", payload, headers
        )

    def close_dispute(self, dispute_id, headers, payload=None):
        return self._request(
            "POST", f"/disputes/{dispute_id}/close", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Back wage corrections
    # ------------------------------------------------------------------
    def create_back_wage_correction(self, payload, headers):
        return self._request("POST", "/back-wage-corrections", payload, headers)

    def get_back_wage_correction(self, correction_id, headers):
        return self._request(
            "GET", f"/back-wage-corrections/{correction_id}", headers=headers
        )

    def list_back_wage_corrections(self, headers, params=None):
        return self._request(
            "GET", "/back-wage-corrections", headers=headers, params=params
        )

    def apply_back_wage_correction(self, correction_id, headers, payload=None):
        return self._request(
            "POST",
            f"/back-wage-corrections/{correction_id}/apply",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
