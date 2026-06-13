"""API client: one method per endpoint defined in the Earned Wage Access PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Employer ----
    def create_employer(self, payload, headers):
        return self._request("POST", "/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/employers/{employer_id}", headers=headers)

    def list_employers(self, headers, params=None):
        return self._request("GET", "/employers", headers=headers, params=params)

    def funding_deposit(self, employer_id, payload, headers):
        return self._request("POST", f"/employers/{employer_id}/funding-deposits", payload, headers)

    # ---- AdvanceLimitPolicy ----
    def create_advance_policy(self, payload, headers):
        return self._request("POST", "/advance-policies", payload, headers)

    def get_advance_policy(self, policy_id, headers):
        return self._request("GET", f"/advance-policies/{policy_id}", headers=headers)

    def list_advance_policies(self, headers, params=None):
        return self._request("GET", "/advance-policies", headers=headers, params=params)

    # ---- FeeSchedule ----
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{fee_schedule_id}", headers=headers)

    def list_fee_schedules(self, headers, params=None):
        return self._request("GET", "/fee-schedules", headers=headers, params=params)

    # ---- PayPeriod ----
    def create_pay_period(self, payload, headers):
        return self._request("POST", "/pay-periods", payload, headers)

    def get_pay_period(self, pay_period_id, headers):
        return self._request("GET", f"/pay-periods/{pay_period_id}", headers=headers)

    def list_pay_periods(self, headers, params=None):
        return self._request("GET", "/pay-periods", headers=headers, params=params)

    def lock_pay_period(self, pay_period_id, headers):
        return self._request("POST", f"/pay-periods/{pay_period_id}/lock", {}, headers)

    def reopen_pay_period(self, pay_period_id, headers):
        return self._request("POST", f"/pay-periods/{pay_period_id}/reopen", {}, headers)

    def run_payday(self, pay_period_id, headers):
        return self._request("POST", f"/pay-periods/{pay_period_id}/run-payday", {}, headers)

    # ---- Worker ----
    def create_worker(self, payload, headers):
        return self._request("POST", "/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/workers", headers=headers, params=params)

    def suspend_worker(self, worker_id, headers):
        return self._request("POST", f"/workers/{worker_id}/suspend", {}, headers)

    def reinstate_worker(self, worker_id, headers):
        return self._request("POST", f"/workers/{worker_id}/reinstate", {}, headers)

    def terminate_worker(self, worker_id, headers):
        return self._request("POST", f"/workers/{worker_id}/terminate", {}, headers)

    # ---- TimeEntry ----
    def create_time_entry(self, payload, headers):
        return self._request("POST", "/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def void_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/time-entries/{time_entry_id}/void", {}, headers)

    # ---- Advance ----
    def create_advance(self, payload, headers):
        return self._request("POST", "/advances", payload, headers)

    def get_advance(self, advance_id, headers):
        return self._request("GET", f"/advances/{advance_id}", headers=headers)

    def list_advances(self, headers, params=None):
        return self._request("GET", "/advances", headers=headers, params=params)

    def approve_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/approve", {}, headers)

    def decline_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/decline", {}, headers)

    def disburse_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/disburse", {}, headers)

    def manual_recoup_advance(self, advance_id, payload, headers):
        return self._request("POST", f"/advances/{advance_id}/manual-recoup", payload, headers)

    def write_off_advance(self, advance_id, headers):
        return self._request("POST", f"/advances/{advance_id}/write-off", {}, headers)

    # ---- RepaymentBatch ----
    def create_repayment_batch(self, payload, headers):
        return self._request("POST", "/repayment-batches", payload, headers)

    def get_repayment_batch(self, batch_id, headers):
        return self._request("GET", f"/repayment-batches/{batch_id}", headers=headers)

    def list_repayment_batches(self, headers, params=None):
        return self._request("GET", "/repayment-batches", headers=headers, params=params)

    def post_repayment_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/repayment-batches/{batch_id}/post", payload, headers)

    def cancel_repayment_batch(self, batch_id, headers):
        return self._request("POST", f"/repayment-batches/{batch_id}/cancel", {}, headers)

    # ---- Repayment ----
    def get_repayment(self, repayment_id, headers):
        return self._request("GET", f"/repayments/{repayment_id}", headers=headers)

    def list_repayments(self, headers, params=None):
        return self._request("GET", "/repayments", headers=headers, params=params)

    # ---- ReconciliationStatement ----
    def create_reconciliation_statement(self, payload, headers):
        return self._request("POST", "/reconciliation-statements", payload, headers)

    def get_reconciliation_statement(self, statement_id, headers):
        return self._request("GET", f"/reconciliation-statements/{statement_id}", headers=headers)

    def list_reconciliation_statements(self, headers, params=None):
        return self._request("GET", "/reconciliation-statements", headers=headers, params=params)

    def sign_reconciliation_statement(self, statement_id, headers):
        return self._request("POST", f"/reconciliation-statements/{statement_id}/sign", {}, headers)


api_client = ApiClient()
