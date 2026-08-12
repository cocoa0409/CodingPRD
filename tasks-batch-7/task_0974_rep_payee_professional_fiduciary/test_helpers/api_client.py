"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Clients ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/activate", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/suspend", headers=headers)

    def terminate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/terminate", headers=headers)

    # --- Benefit entitlements ---
    def create_entitlement(self, payload, headers):
        return self._request("POST", "/benefit-entitlements", payload, headers)

    def list_entitlements(self, headers, params=None):
        return self._request("GET", "/benefit-entitlements", headers=headers, params=params)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/benefit-entitlements/{entitlement_id}", headers=headers)

    def verify_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/benefit-entitlements/{entitlement_id}/verify", headers=headers)

    def terminate_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/benefit-entitlements/{entitlement_id}/terminate", headers=headers)

    # --- Trust accounts ---
    def create_trust_account(self, payload, headers):
        return self._request("POST", "/trust-accounts", payload, headers)

    def list_trust_accounts(self, headers, params=None):
        return self._request("GET", "/trust-accounts", headers=headers, params=params)

    def get_trust_account(self, account_id, headers):
        return self._request("GET", f"/trust-accounts/{account_id}", headers=headers)

    def close_trust_account(self, account_id, headers):
        return self._request("POST", f"/trust-accounts/{account_id}/close", headers=headers)

    def get_account_ledger(self, account_id, headers, params=None):
        return self._request("GET", f"/trust-accounts/{account_id}/ledger", headers=headers, params=params)

    # --- Budget plans ---
    def create_budget_plan(self, payload, headers):
        return self._request("POST", "/budget-plans", payload, headers)

    def list_budget_plans(self, headers, params=None):
        return self._request("GET", "/budget-plans", headers=headers, params=params)

    def get_budget_plan(self, plan_id, headers):
        return self._request("GET", f"/budget-plans/{plan_id}", headers=headers)

    def propose_budget_plan(self, plan_id, headers):
        return self._request("POST", f"/budget-plans/{plan_id}/propose", headers=headers)

    def approve_budget_plan(self, plan_id, headers):
        return self._request("POST", f"/budget-plans/{plan_id}/approve", headers=headers)

    def revise_budget_plan(self, plan_id, headers):
        return self._request("POST", f"/budget-plans/{plan_id}/revise", headers=headers)

    def rebalance_budget_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/budget-plans/{plan_id}/rebalance", payload, headers)

    # --- Disbursements ---
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/disbursements", payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def approve_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/approve", headers=headers)

    def co_approve_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/co-approve", headers=headers)

    def reject_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/reject", headers=headers)

    def release_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/release", headers=headers)

    def return_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/return", headers=headers)

    # --- Deposits ---
    def create_deposit(self, payload, headers):
        return self._request("POST", "/deposits", payload, headers)

    def list_deposits(self, headers, params=None):
        return self._request("GET", "/deposits", headers=headers, params=params)

    def get_deposit(self, deposit_id, headers):
        return self._request("GET", f"/deposits/{deposit_id}", headers=headers)

    def post_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/post", headers=headers)

    def return_deposit(self, deposit_id, headers):
        return self._request("POST", f"/deposits/{deposit_id}/return", headers=headers)

    # --- Court orders ---
    def create_court_order(self, payload, headers):
        return self._request("POST", "/court-orders", payload, headers)

    def list_court_orders(self, headers, params=None):
        return self._request("GET", "/court-orders", headers=headers, params=params)

    def get_court_order(self, order_id, headers):
        return self._request("GET", f"/court-orders/{order_id}", headers=headers)

    def grant_court_order(self, order_id, headers):
        return self._request("POST", f"/court-orders/{order_id}/grant", headers=headers)

    # --- Surety bonds ---
    def create_surety_bond(self, payload, headers):
        return self._request("POST", "/surety-bonds", payload, headers)

    def list_surety_bonds(self, headers, params=None):
        return self._request("GET", "/surety-bonds", headers=headers, params=params)

    def get_surety_bond(self, bond_id, headers):
        return self._request("GET", f"/surety-bonds/{bond_id}", headers=headers)

    def activate_surety_bond(self, bond_id, headers):
        return self._request("POST", f"/surety-bonds/{bond_id}/activate", headers=headers)

    # --- Accounting reports ---
    def create_accounting_report(self, payload, headers):
        return self._request("POST", "/accounting-reports", payload, headers)

    def list_accounting_reports(self, headers, params=None):
        return self._request("GET", "/accounting-reports", headers=headers, params=params)

    def get_accounting_report(self, report_id, headers):
        return self._request("GET", f"/accounting-reports/{report_id}", headers=headers)

    def submit_accounting_report(self, report_id, headers):
        return self._request("POST", f"/accounting-reports/{report_id}/submit", headers=headers)

    def accept_accounting_report(self, report_id, headers):
        return self._request("POST", f"/accounting-reports/{report_id}/accept", headers=headers)

    def reject_accounting_report(self, report_id, headers):
        return self._request("POST", f"/accounting-reports/{report_id}/reject", headers=headers)

    # --- Spend-down plans ---
    def create_spend_down_plan(self, payload, headers):
        return self._request("POST", "/spend-down-plans", payload, headers)

    def list_spend_down_plans(self, headers, params=None):
        return self._request("GET", "/spend-down-plans", headers=headers, params=params)

    def get_spend_down_plan(self, plan_id, headers):
        return self._request("GET", f"/spend-down-plans/{plan_id}", headers=headers)

    def activate_spend_down_plan(self, plan_id, headers):
        return self._request("POST", f"/spend-down-plans/{plan_id}/activate", headers=headers)

    def finalize_spend_down_plan(self, plan_id, headers):
        return self._request("POST", f"/spend-down-plans/{plan_id}/finalize", headers=headers)

    # --- Audit cases ---
    def create_audit_case(self, payload, headers):
        return self._request("POST", "/audit-cases", payload, headers)

    def list_audit_cases(self, headers, params=None):
        return self._request("GET", "/audit-cases", headers=headers, params=params)

    def get_audit_case(self, audit_id, headers):
        return self._request("GET", f"/audit-cases/{audit_id}", headers=headers)

    def issue_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/audit-cases/{audit_id}/issue-findings", payload, headers)

    def close_audit_case(self, audit_id, headers):
        return self._request("POST", f"/audit-cases/{audit_id}/close", headers=headers)

    # --- Conservators ---
    def create_conservator(self, payload, headers):
        return self._request("POST", "/conservators", payload, headers)

    def list_conservators(self, headers, params=None):
        return self._request("GET", "/conservators", headers=headers, params=params)

    def get_conservator(self, conservator_id, headers):
        return self._request("GET", f"/conservators/{conservator_id}", headers=headers)

    def suspend_conservator(self, conservator_id, headers):
        return self._request("POST", f"/conservators/{conservator_id}/suspend", headers=headers)

    def discharge_conservator(self, conservator_id, headers):
        return self._request("POST", f"/conservators/{conservator_id}/discharge", headers=headers)

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
