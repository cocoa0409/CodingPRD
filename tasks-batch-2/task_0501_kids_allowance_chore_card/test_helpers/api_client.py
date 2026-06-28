"""API client: one method per endpoint defined in the PRD (Kids Allowance & Chore Card)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Family ───────────────────────────────────────
    def create_family(self, payload, headers):
        return self._request("POST", "/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/families/{family_id}", headers=headers)

    def deposit(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/deposit", payload, headers)

    def set_alert_thresholds(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/alert-thresholds", payload, headers)

    def suspend_family(self, family_id, headers):
        return self._request("POST", f"/families/{family_id}/suspend", {}, headers)

    def reactivate_family(self, family_id, headers):
        return self._request("POST", f"/families/{family_id}/reactivate", {}, headers)

    # ─── ChildAccount ─────────────────────────────────
    def create_child_account(self, family_id, payload, headers):
        return self._request("POST", f"/families/{family_id}/child-accounts", payload, headers)

    def list_child_accounts(self, family_id, headers, params=None):
        return self._request("GET", f"/families/{family_id}/child-accounts", headers=headers, params=params)

    def get_child_account(self, child_id, headers):
        return self._request("GET", f"/child-accounts/{child_id}", headers=headers)

    def archive_child_account(self, child_id, headers):
        return self._request("POST", f"/child-accounts/{child_id}/archive", {}, headers)

    def fund_jar(self, child_id, payload, headers):
        return self._request("POST", f"/child-accounts/{child_id}/fund-jar", payload, headers)

    # ─── Jar ──────────────────────────────────────────
    def list_jars(self, child_id, headers, params=None):
        return self._request("GET", f"/child-accounts/{child_id}/jars", headers=headers, params=params)

    def get_jar(self, jar_id, headers):
        return self._request("GET", f"/jars/{jar_id}", headers=headers)

    # ─── Chore + ChoreCompletion ──────────────────────
    def create_chore(self, child_id, payload, headers):
        return self._request("POST", f"/child-accounts/{child_id}/chores", payload, headers)

    def list_chores(self, child_id, headers, params=None):
        return self._request("GET", f"/child-accounts/{child_id}/chores", headers=headers, params=params)

    def get_chore(self, chore_id, headers):
        return self._request("GET", f"/chores/{chore_id}", headers=headers)

    def submit_chore(self, chore_id, headers):
        return self._request("POST", f"/chores/{chore_id}/submit", {}, headers)

    def reopen_chore(self, chore_id, headers):
        return self._request("POST", f"/chores/{chore_id}/reopen", {}, headers)

    def delete_chore(self, chore_id, headers):
        return self._request("DELETE", f"/chores/{chore_id}", headers=headers)

    def list_completions(self, chore_id, headers, params=None):
        return self._request("GET", f"/chores/{chore_id}/completions", headers=headers, params=params)

    def get_completion(self, completion_id, headers):
        return self._request("GET", f"/chore-completions/{completion_id}", headers=headers)

    def approve_completion(self, completion_id, headers):
        return self._request("POST", f"/chore-completions/{completion_id}/approve", {}, headers)

    def kick_back_completion(self, completion_id, headers):
        return self._request("POST", f"/chore-completions/{completion_id}/kick-back", {}, headers)

    def resubmit_completion(self, completion_id, headers):
        return self._request("POST", f"/chore-completions/{completion_id}/resubmit", {}, headers)

    def deny_completion(self, completion_id, headers):
        return self._request("POST", f"/chore-completions/{completion_id}/deny", {}, headers)

    # ─── DebitCard + CardControl + Transaction ────────
    def list_debit_cards(self, child_id, headers, params=None):
        return self._request("GET", f"/child-accounts/{child_id}/debit-cards", headers=headers, params=params)

    def get_debit_card(self, card_id, headers):
        return self._request("GET", f"/debit-cards/{card_id}", headers=headers)

    def lock_card(self, card_id, payload, headers):
        return self._request("POST", f"/debit-cards/{card_id}/lock", payload, headers)

    def unlock_card(self, card_id, payload, headers):
        return self._request("POST", f"/debit-cards/{card_id}/unlock", payload, headers)

    def create_control(self, card_id, payload, headers):
        return self._request("POST", f"/debit-cards/{card_id}/controls", payload, headers)

    def list_controls(self, card_id, headers, params=None):
        return self._request("GET", f"/debit-cards/{card_id}/controls", headers=headers, params=params)

    def delete_control(self, control_id, headers):
        return self._request("DELETE", f"/card-controls/{control_id}", headers=headers)

    def authorize(self, card_id, payload, headers):
        return self._request("POST", f"/debit-cards/{card_id}/authorizations", payload, headers)

    def list_transactions(self, card_id, headers, params=None):
        return self._request("GET", f"/debit-cards/{card_id}/transactions", headers=headers, params=params)

    def get_transaction(self, txn_id, headers):
        return self._request("GET", f"/transactions/{txn_id}", headers=headers)

    def settle_transaction(self, txn_id, payload, headers):
        return self._request("POST", f"/transactions/{txn_id}/settle", payload, headers)

    def reverse_transaction(self, txn_id, headers):
        return self._request("POST", f"/transactions/{txn_id}/reverse", {}, headers)

    def list_alerts(self, txn_id, headers, params=None):
        return self._request("GET", f"/transactions/{txn_id}/alerts", headers=headers, params=params)

    # ─── AllowanceSchedule + AllowanceRun ─────────────
    def create_allowance_schedule(self, child_id, payload, headers):
        return self._request("POST", f"/child-accounts/{child_id}/allowance-schedules", payload, headers)

    def list_allowance_schedules(self, child_id, headers, params=None):
        return self._request("GET", f"/child-accounts/{child_id}/allowance-schedules", headers=headers, params=params)

    def get_allowance_schedule(self, sched_id, headers):
        return self._request("GET", f"/allowance-schedules/{sched_id}", headers=headers)

    def pause_schedule(self, sched_id, headers):
        return self._request("POST", f"/allowance-schedules/{sched_id}/pause", {}, headers)

    def resume_schedule(self, sched_id, headers):
        return self._request("POST", f"/allowance-schedules/{sched_id}/resume", {}, headers)

    def cancel_schedule(self, sched_id, headers):
        return self._request("DELETE", f"/allowance-schedules/{sched_id}", headers=headers)

    def list_runs(self, sched_id, headers, params=None):
        return self._request("GET", f"/allowance-schedules/{sched_id}/runs", headers=headers, params=params)

    def run_due_allowances(self, headers):
        return self._request("POST", "/_scheduler/run-due-allowances", {}, headers)

    # ─── InterestMatchConfig + InterestAccrual ────────
    def get_child_interest_config(self, child_id, headers):
        return self._request("GET", f"/child-accounts/{child_id}/interest-match-config", headers=headers)

    def get_interest_config(self, cfg_id, headers):
        return self._request("GET", f"/interest-match-configs/{cfg_id}", headers=headers)

    def configure_interest(self, cfg_id, payload, headers):
        return self._request("PUT", f"/interest-match-configs/{cfg_id}", payload, headers)

    def accrue(self, cfg_id, payload, headers):
        return self._request("POST", f"/interest-match-configs/{cfg_id}/accrue", payload, headers)

    def list_accruals(self, cfg_id, headers, params=None):
        return self._request("GET", f"/interest-match-configs/{cfg_id}/accruals", headers=headers, params=params)

    # ─── InvestmentAccount + InvestmentOrder ──────────
    def enable_investing(self, child_id, headers):
        return self._request("POST", f"/child-accounts/{child_id}/investment-account", {}, headers)

    def get_child_investment_account(self, child_id, headers):
        return self._request("GET", f"/child-accounts/{child_id}/investment-account", headers=headers)

    def get_investment_account(self, inv_id, headers):
        return self._request("GET", f"/investment-accounts/{inv_id}", headers=headers)

    def fund_investment(self, inv_id, payload, headers):
        return self._request("POST", f"/investment-accounts/{inv_id}/fund", payload, headers)

    def place_order(self, inv_id, payload, headers):
        return self._request("POST", f"/investment-accounts/{inv_id}/orders", payload, headers)

    def list_orders(self, inv_id, headers, params=None):
        return self._request("GET", f"/investment-accounts/{inv_id}/orders", headers=headers, params=params)

    def close_investment_account(self, inv_id, headers):
        return self._request("POST", f"/investment-accounts/{inv_id}/close", {}, headers)

    # ─── Logical clock ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
