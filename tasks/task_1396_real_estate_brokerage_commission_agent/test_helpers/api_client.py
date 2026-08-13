"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/brokerage/_clock/set_current_utc", payload, headers)

    # --- Agents ---
    def create_agent(self, payload, headers):
        return self._request("POST", "/brokerage/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/brokerage/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/brokerage/agents", headers=headers, params=params)

    def patch_agent(self, agent_id, payload, headers):
        return self._request("PATCH", f"/brokerage/agents/{agent_id}", payload, headers)

    def activate_agent(self, agent_id, headers):
        return self._request("POST", f"/brokerage/agents/{agent_id}/activate", {}, headers)

    def suspend_agent(self, agent_id, headers):
        return self._request("POST", f"/brokerage/agents/{agent_id}/suspend", {}, headers)

    def reinstate_agent(self, agent_id, headers):
        return self._request("POST", f"/brokerage/agents/{agent_id}/reinstate", {}, headers)

    def terminate_agent(self, agent_id, headers):
        return self._request("POST", f"/brokerage/agents/{agent_id}/terminate", {}, headers)

    # --- Plans ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/brokerage/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/brokerage/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/brokerage/plans", headers=headers, params=params)

    def put_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"/brokerage/plans/{plan_id}", payload, headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/brokerage/plans/{plan_id}/activate", {}, headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/brokerage/plans/{plan_id}/retire", {}, headers)

    # --- Enrollments ---
    def create_enrollment(self, agent_id, payload, headers):
        return self._request("POST", f"/brokerage/agents/{agent_id}/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/brokerage/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/brokerage/enrollments", headers=headers, params=params)

    # --- Anniversary periods ---
    def get_anniversary_period(self, period_id, headers):
        return self._request("GET", f"/brokerage/anniversary-periods/{period_id}", headers=headers)

    def list_anniversary_periods(self, headers, params=None):
        return self._request("GET", "/brokerage/anniversary-periods", headers=headers, params=params)

    # --- Deals ---
    def create_deal(self, payload, headers):
        return self._request("POST", "/brokerage/deals", payload, headers)

    def get_deal(self, deal_id, headers):
        return self._request("GET", f"/brokerage/deals/{deal_id}", headers=headers)

    def list_deals(self, headers, params=None):
        return self._request("GET", "/brokerage/deals", headers=headers, params=params)

    def put_deal(self, deal_id, payload, headers):
        return self._request("PUT", f"/brokerage/deals/{deal_id}", payload, headers)

    def submit_deal(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/submit", {}, headers)

    def withdraw_deal(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/withdraw", {}, headers)

    def fall_through_deal(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/fall-through", {}, headers)

    def close_deal(self, deal_id, payload, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/close", payload, headers)

    def void_deal(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/void", {}, headers)

    def payout_estimate(self, deal_id, headers):
        return self._request("GET", f"/brokerage/deals/{deal_id}/payout-estimate", headers=headers)

    def settle_deal(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/settle", {}, headers)

    def unsettle_deal(self, deal_id, headers):
        return self._request("POST", f"/brokerage/deals/{deal_id}/unsettle", {}, headers)

    # --- Settlements ---
    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/brokerage/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/brokerage/settlements", headers=headers, params=params)

    # --- Disbursement legs ---
    def get_leg(self, leg_id, headers):
        return self._request("GET", f"/brokerage/disbursement-legs/{leg_id}", headers=headers)

    def list_legs(self, headers, params=None):
        return self._request("GET", "/brokerage/disbursement-legs", headers=headers, params=params)

    def authorize_leg(self, leg_id, headers):
        return self._request("POST", f"/brokerage/disbursement-legs/{leg_id}/authorize", {}, headers)

    def release_leg(self, leg_id, headers):
        return self._request("POST", f"/brokerage/disbursement-legs/{leg_id}/release", {}, headers)

    def void_leg(self, leg_id, headers):
        return self._request("POST", f"/brokerage/disbursement-legs/{leg_id}/void", {}, headers)

    # --- Ledger entries ---
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/brokerage/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/brokerage/ledger-entries", headers=headers, params=params)

    def create_debit_adjustment(self, agent_id, payload, headers):
        return self._request("POST", f"/brokerage/agents/{agent_id}/debit-adjustments", payload, headers)

    # --- Tax forms ---
    def create_tax_form(self, agent_id, payload, headers):
        return self._request("POST", f"/brokerage/agents/{agent_id}/tax-forms", payload, headers)

    def get_tax_form(self, tax_form_id, headers):
        return self._request("GET", f"/brokerage/tax-forms/{tax_form_id}", headers=headers)

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/brokerage/tax-forms", headers=headers, params=params)

    def finalize_tax_form(self, tax_form_id, headers):
        return self._request("POST", f"/brokerage/tax-forms/{tax_form_id}/finalize", {}, headers)

    def void_tax_form(self, tax_form_id, headers):
        return self._request("POST", f"/brokerage/tax-forms/{tax_form_id}/void", {}, headers)

    # --- Trust ---
    def get_trust_transaction(self, transaction_id, headers):
        return self._request("GET", f"/brokerage/trust-transactions/{transaction_id}", headers=headers)

    def list_trust_transactions(self, headers, params=None):
        return self._request("GET", "/brokerage/trust-transactions", headers=headers, params=params)

    def get_trust_ledger(self, headers):
        return self._request("GET", "/brokerage/trust-ledger", headers=headers)


api_client = ApiClient()
