"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- GrowerOperation ---
    def create_operation(self, payload, headers):
        return self._request("POST", "/advisory/operations", payload, headers)

    def get_operation(self, operation_id, headers):
        return self._request("GET", f"/advisory/operations/{operation_id}", headers=headers)

    def get_performance_report(self, operation_id, headers, params=None):
        return self._request(
            "GET", f"/advisory/operations/{operation_id}/performance-report",
            headers=headers, params=params,
        )

    def get_cash_flow_projection(self, operation_id, headers, params=None):
        return self._request(
            "GET", f"/advisory/operations/{operation_id}/cash-flow-projection",
            headers=headers, params=params,
        )

    # --- ProductionBaseline ---
    def create_baseline(self, payload, headers):
        return self._request("POST", "/advisory/production-baselines", payload, headers)

    def get_baseline(self, baseline_id, headers):
        return self._request("GET", f"/advisory/production-baselines/{baseline_id}", headers=headers)

    def list_baselines(self, headers, params=None):
        return self._request("GET", "/advisory/production-baselines", headers=headers, params=params)

    def certify_baseline(self, baseline_id, headers):
        return self._request("POST", f"/advisory/production-baselines/{baseline_id}/certify", headers=headers)

    # --- InsurancePolicy ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/advisory/insurance-policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/advisory/insurance-policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/advisory/insurance-policies", headers=headers, params=params)

    def bind_policy(self, policy_id, headers):
        return self._request("POST", f"/advisory/insurance-policies/{policy_id}/bind", headers=headers)

    def file_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/advisory/insurance-policies/{policy_id}/file-claim", payload, headers)

    # --- MarketingPlan ---
    def create_plan(self, payload, headers):
        return self._request("POST", "/advisory/marketing-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/advisory/marketing-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/advisory/marketing-plans", headers=headers, params=params)

    def amend_plan(self, plan_id, payload, headers):
        return self._request("PUT", f"/advisory/marketing-plans/{plan_id}", payload, headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/advisory/marketing-plans/{plan_id}/activate", headers=headers)

    def suspend_plan(self, plan_id, headers):
        return self._request("POST", f"/advisory/marketing-plans/{plan_id}/suspend", headers=headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/advisory/marketing-plans/{plan_id}/resume", headers=headers)

    def close_plan(self, plan_id, headers):
        return self._request("POST", f"/advisory/marketing-plans/{plan_id}/close", headers=headers)

    # --- PriceTarget ---
    def create_price_target(self, payload, headers):
        return self._request("POST", "/advisory/price-targets", payload, headers)

    def get_price_target(self, target_id, headers):
        return self._request("GET", f"/advisory/price-targets/{target_id}", headers=headers)

    def list_price_targets(self, headers, params=None):
        return self._request("GET", "/advisory/price-targets", headers=headers, params=params)

    def cancel_price_target(self, target_id, headers):
        return self._request("POST", f"/advisory/price-targets/{target_id}/cancel", headers=headers)

    # --- MarketTick ---
    def create_market_tick(self, payload, headers):
        return self._request("POST", "/advisory/market-ticks", payload, headers)

    # --- HedgeRecommendation ---
    def create_recommendation(self, payload, headers):
        return self._request("POST", "/advisory/hedge-recommendations", payload, headers)

    def get_recommendation(self, recommendation_id, headers):
        return self._request("GET", f"/advisory/hedge-recommendations/{recommendation_id}", headers=headers)

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/advisory/hedge-recommendations", headers=headers, params=params)

    def accept_recommendation(self, recommendation_id, headers):
        return self._request("POST", f"/advisory/hedge-recommendations/{recommendation_id}/accept", headers=headers)

    def reject_recommendation(self, recommendation_id, headers):
        return self._request("POST", f"/advisory/hedge-recommendations/{recommendation_id}/reject", headers=headers)

    def execute_recommendation(self, recommendation_id, headers):
        return self._request("POST", f"/advisory/hedge-recommendations/{recommendation_id}/execute", headers=headers)

    # --- BrokeragePosition ---
    def get_position(self, position_id, headers):
        return self._request("GET", f"/advisory/brokerage-positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/advisory/brokerage-positions", headers=headers, params=params)

    def offset_position(self, position_id, headers):
        return self._request("POST", f"/advisory/brokerage-positions/{position_id}/offset", headers=headers)

    # --- MarginAccount ---
    def create_margin_account(self, payload, headers):
        return self._request("POST", "/advisory/margin-accounts", payload, headers)

    def get_margin_account(self, account_id, headers):
        return self._request("GET", f"/advisory/margin-accounts/{account_id}", headers=headers)

    def list_margin_accounts(self, headers, params=None):
        return self._request("GET", "/advisory/margin-accounts", headers=headers, params=params)

    def fund_margin_account(self, account_id, payload, headers):
        return self._request("POST", f"/advisory/margin-accounts/{account_id}/fund", payload, headers)

    def liquidate_margin_account(self, account_id, headers):
        return self._request("POST", f"/advisory/margin-accounts/{account_id}/liquidate", headers=headers)

    # --- Buyer ---
    def create_buyer(self, payload, headers):
        return self._request("POST", "/advisory/buyers", payload, headers)

    def get_buyer(self, buyer_id, headers):
        return self._request("GET", f"/advisory/buyers/{buyer_id}", headers=headers)

    def list_buyers(self, headers, params=None):
        return self._request("GET", "/advisory/buyers", headers=headers, params=params)

    def approve_buyer(self, buyer_id, headers):
        return self._request("POST", f"/advisory/buyers/{buyer_id}/approve", headers=headers)

    def suspend_buyer(self, buyer_id, headers):
        return self._request("POST", f"/advisory/buyers/{buyer_id}/suspend", headers=headers)

    # --- SalesContract ---
    def create_contract(self, payload, headers):
        return self._request("POST", "/advisory/sales-contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/advisory/sales-contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/advisory/sales-contracts", headers=headers, params=params)

    def fix_price(self, contract_id, payload, headers):
        return self._request("POST", f"/advisory/sales-contracts/{contract_id}/fix-price", payload, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/advisory/sales-contracts/{contract_id}/cancel", headers=headers)

    def default_contract(self, contract_id, headers):
        return self._request("POST", f"/advisory/sales-contracts/{contract_id}/default", headers=headers)

    # --- DeliveryTicket ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/advisory/delivery-tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/advisory/delivery-tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/advisory/delivery-tickets", headers=headers, params=params)

    def confirm_ticket(self, ticket_id, headers):
        return self._request("POST", f"/advisory/delivery-tickets/{ticket_id}/confirm", headers=headers)

    def void_ticket(self, ticket_id, headers):
        return self._request("POST", f"/advisory/delivery-tickets/{ticket_id}/void", headers=headers)

    # --- StorageLot ---
    def create_storage_lot(self, payload, headers):
        return self._request("POST", "/advisory/storage-lots", payload, headers)

    def get_storage_lot(self, lot_id, headers):
        return self._request("GET", f"/advisory/storage-lots/{lot_id}", headers=headers)

    def list_storage_lots(self, headers, params=None):
        return self._request("GET", "/advisory/storage-lots", headers=headers, params=params)

    def withdraw_storage_lot(self, lot_id, headers):
        return self._request("POST", f"/advisory/storage-lots/{lot_id}/withdraw", headers=headers)

    def get_storage_breakeven(self, lot_id, headers):
        return self._request("GET", f"/advisory/storage-lots/{lot_id}/breakeven", headers=headers)

    # --- AdvisoryAgreement ---
    def create_agreement(self, payload, headers):
        return self._request("POST", "/advisory/advisory-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/advisory/advisory-agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/advisory/advisory-agreements", headers=headers, params=params)

    def submit_agreement(self, agreement_id, headers):
        return self._request("POST", f"/advisory/advisory-agreements/{agreement_id}/submit", headers=headers)

    def deliver_disclosure(self, agreement_id, headers):
        return self._request("POST", f"/advisory/advisory-agreements/{agreement_id}/deliver-disclosure", headers=headers)

    def acknowledge_disclosure(self, agreement_id, headers):
        return self._request("POST", f"/advisory/advisory-agreements/{agreement_id}/acknowledge-disclosure", headers=headers)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/advisory/advisory-agreements/{agreement_id}/sign", headers=headers)

    def amend_agreement(self, agreement_id, payload, headers):
        return self._request("PUT", f"/advisory/advisory-agreements/{agreement_id}", payload, headers)

    def certify_compliance(self, agreement_id, headers):
        return self._request("POST", f"/advisory/advisory-agreements/{agreement_id}/certify-compliance", headers=headers)

    def get_fee_statement(self, agreement_id, headers, params=None):
        return self._request("GET", f"/advisory/advisory-agreements/{agreement_id}/fee-statement", headers=headers, params=params)

    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/advisory/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
