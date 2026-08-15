"""API client: one method per endpoint defined in the PRD endpoint table (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # Fresh TCP connection per request. Under per-test-server isolation the
        # server restarts between tests, so a pooled keep-alive connection can
        # point at a dead socket; the next POST then fails with a spurious
        # ConnectionError / IncompleteRead instead of reaching the server.
        self.session.headers["Connection"] = "close"

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/trading/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/trading/accounts/{account_id}", headers=headers)

    def set_account_status(self, account_id, payload, headers):
        return self._request("POST", f"/trading/accounts/{account_id}/status", payload, headers)

    # --- Securities ---
    def create_security(self, payload, headers):
        return self._request("POST", "/trading/securities", payload, headers)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/trading/securities/{security_id}", headers=headers)

    def set_security_status(self, security_id, payload, headers):
        return self._request("POST", f"/trading/securities/{security_id}/status", payload, headers)

    # --- Brokers ---
    def create_broker(self, payload, headers):
        return self._request("POST", "/trading/brokers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/trading/brokers/{broker_id}", headers=headers)

    def set_broker_status(self, broker_id, payload, headers):
        return self._request("POST", f"/trading/brokers/{broker_id}/status", payload, headers)

    # --- Commission budgets ---
    def create_commission_budget(self, account_id, payload, headers):
        return self._request("POST", f"/trading/accounts/{account_id}/commission-budgets", payload, headers)

    def get_commission_budget(self, budget_id, headers):
        return self._request("GET", f"/trading/commission-budgets/{budget_id}", headers=headers)

    def list_commission_budgets(self, headers, params=None):
        return self._request("GET", "/trading/commission-budgets", headers=headers, params=params)

    # --- Restrictions ---
    def create_restriction(self, payload, headers):
        return self._request("POST", "/trading/restrictions", payload, headers)

    def get_restriction(self, restriction_id, headers):
        return self._request("GET", f"/trading/restrictions/{restriction_id}", headers=headers)

    def list_restrictions(self, headers, params=None):
        return self._request("GET", "/trading/restrictions", headers=headers, params=params)

    def activate_restriction(self, restriction_id, headers):
        return self._request("POST", f"/trading/restrictions/{restriction_id}/activate", headers=headers)

    def suspend_restriction(self, restriction_id, headers):
        return self._request("POST", f"/trading/restrictions/{restriction_id}/suspend", headers=headers)

    def retire_restriction(self, restriction_id, headers):
        return self._request("POST", f"/trading/restrictions/{restriction_id}/retire", headers=headers)

    # --- Orders ---
    def create_order(self, payload, headers):
        return self._request("POST", "/trading/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/trading/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/trading/orders", headers=headers, params=params)

    def compliance_check_order(self, order_id, headers):
        return self._request("POST", f"/trading/orders/{order_id}/compliance-check", headers=headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/trading/orders/{order_id}/cancel", headers=headers)

    # --- Blocks, fills ---
    def create_block(self, payload, headers):
        return self._request("POST", "/trading/blocks", payload, headers)

    def get_block(self, block_id, headers):
        return self._request("GET", f"/trading/blocks/{block_id}", headers=headers)

    def list_blocks(self, headers, params=None):
        return self._request("GET", "/trading/blocks", headers=headers, params=params)

    def attach_order_to_block(self, block_id, payload, headers):
        return self._request("POST", f"/trading/blocks/{block_id}/orders", payload, headers)

    def detach_order_from_block(self, block_id, order_id, headers):
        return self._request("DELETE", f"/trading/blocks/{block_id}/orders/{order_id}", headers=headers)

    def cancel_block(self, block_id, headers):
        return self._request("POST", f"/trading/blocks/{block_id}/cancel", headers=headers)

    def route_block(self, block_id, payload, headers):
        return self._request("POST", f"/trading/blocks/{block_id}/route", payload, headers)

    def record_fill(self, block_id, payload, headers):
        return self._request("POST", f"/trading/blocks/{block_id}/fills", payload, headers)

    def list_block_fills(self, block_id, headers, params=None):
        return self._request("GET", f"/trading/blocks/{block_id}/fills", headers=headers, params=params)

    # --- Allocation plans and lines ---
    def create_allocation_plan(self, block_id, payload, headers):
        return self._request("POST", f"/trading/blocks/{block_id}/allocation-plans", payload, headers)

    def get_allocation_plan(self, plan_id, headers):
        return self._request("GET", f"/trading/allocation-plans/{plan_id}", headers=headers)

    def list_block_allocation_plans(self, block_id, headers, params=None):
        return self._request("GET", f"/trading/blocks/{block_id}/allocation-plans", headers=headers, params=params)

    def propose_plan(self, plan_id, headers):
        return self._request("POST", f"/trading/allocation-plans/{plan_id}/propose", headers=headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/trading/allocation-plans/{plan_id}/approve", headers=headers)

    def return_plan(self, plan_id, headers):
        return self._request("POST", f"/trading/allocation-plans/{planId}/return".format(planId=plan_id), headers=headers)

    def post_plan(self, plan_id, headers):
        return self._request("POST", f"/trading/allocation-plans/{plan_id}/post", headers=headers)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/trading/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/trading/allocations", headers=headers, params=params)

    # --- Trade errors ---
    def flag_allocation_error(self, allocation_id, payload, headers):
        return self._request("POST", f"/trading/allocations/{allocation_id}/flag-error", payload, headers)

    def get_trade_error(self, error_id, headers):
        return self._request("GET", f"/trading/trade-errors/{error_id}", headers=headers)

    def list_trade_errors(self, headers, params=None):
        return self._request("GET", "/trading/trade-errors", headers=headers, params=params)

    def correct_trade_error(self, error_id, payload, headers):
        return self._request("POST", f"/trading/trade-errors/{error_id}/correct", payload, headers)

    def dismiss_trade_error(self, error_id, headers):
        return self._request("POST", f"/trading/trade-errors/{error_id}/dismiss", headers=headers)

    # --- Settlement instructions ---
    def get_settlement_instruction(self, instruction_id, headers):
        return self._request("GET", f"/trading/settlement-instructions/{instruction_id}", headers=headers)

    def list_settlement_instructions(self, headers, params=None):
        return self._request("GET", "/trading/settlement-instructions", headers=headers, params=params)

    def instruct_settlement(self, instruction_id, headers):
        return self._request("POST", f"/trading/settlement-instructions/{instruction_id}/instruct", headers=headers)

    def settle_settlement(self, instruction_id, headers):
        return self._request("POST", f"/trading/settlement-instructions/{instruction_id}/settle", headers=headers)

    def fail_settlement(self, instruction_id, payload, headers):
        return self._request("POST", f"/trading/settlement-instructions/{instruction_id}/fail", payload, headers)

    def repair_settlement(self, instruction_id, headers):
        return self._request("POST", f"/trading/settlement-instructions/{instruction_id}/repair", headers=headers)

    def run_fail_monitor(self, headers):
        return self._request("POST", "/trading/settlement-instructions/run-fail-monitor", headers=headers)

    # --- Positions, audit, clock ---
    def get_position(self, position_id, headers):
        return self._request("GET", f"/trading/positions/{position_id}", headers=headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/trading/positions", headers=headers, params=params)

    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/trading/audit-events", headers=headers, params=params)

    def set_clock(self, payload, headers):
        return self._request("POST", "/trading/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
