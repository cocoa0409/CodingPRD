"""API client: one method per endpoint defined in the PRD (§4, mounted under /advisory)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PlatformAdmin only)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/advisory/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Clients
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/advisory/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/advisory/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/advisory/clients/{client_id}", headers=headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"/advisory/clients/{client_id}/activate", {}, headers)

    def terminate_client(self, client_id, headers):
        return self._request("POST", f"/advisory/clients/{client_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Benchmarks
    # ------------------------------------------------------------------
    def create_benchmark(self, payload, headers):
        return self._request("POST", "/advisory/benchmarks", payload, headers)

    def list_benchmarks(self, headers, params=None):
        return self._request("GET", "/advisory/benchmarks", headers=headers, params=params)

    def retire_benchmark(self, benchmark_id, headers):
        return self._request("POST", f"/advisory/benchmarks/{benchmark_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Investment policy statements
    # ------------------------------------------------------------------
    def create_ips(self, payload, headers):
        return self._request("POST", "/advisory/ips-policies", payload, headers)

    def list_ips(self, headers, params=None):
        return self._request("GET", "/advisory/ips-policies", headers=headers, params=params)

    def get_ips(self, ips_id, headers):
        return self._request("GET", f"/advisory/ips-policies/{ips_id}", headers=headers)

    def replace_allocation_targets(self, ips_id, payload, headers):
        return self._request("PUT", f"/advisory/ips-policies/{ips_id}/allocation-targets",
                             payload, headers)

    def list_allocation_targets(self, ips_id, headers, params=None):
        return self._request("GET", f"/advisory/ips-policies/{ips_id}/allocation-targets",
                             headers=headers, params=params)

    def submit_ips(self, ips_id, headers):
        return self._request("POST", f"/advisory/ips-policies/{ips_id}/submit", {}, headers)

    def compliance_approve_ips(self, ips_id, headers):
        return self._request("POST", f"/advisory/ips-policies/{ips_id}/compliance-approve",
                             {}, headers)

    def compliance_reject_ips(self, ips_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/advisory/ips-policies/{ips_id}/compliance-reject",
                             payload, headers)

    def client_sign_ips(self, ips_id, headers):
        return self._request("POST", f"/advisory/ips-policies/{ips_id}/client-sign", {}, headers)

    def client_decline_ips(self, ips_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/advisory/ips-policies/{ips_id}/client-decline",
                             payload, headers)

    def complete_review_ips(self, ips_id, headers):
        return self._request("POST", f"/advisory/ips-policies/{ips_id}/complete-review",
                             {}, headers)

    # ------------------------------------------------------------------
    # Portfolios
    # ------------------------------------------------------------------
    def create_portfolio(self, payload, headers):
        return self._request("POST", "/advisory/portfolios", payload, headers)

    def list_portfolios(self, headers, params=None):
        return self._request("GET", "/advisory/portfolios", headers=headers, params=params)

    def get_portfolio(self, portfolio_id, headers):
        return self._request("GET", f"/advisory/portfolios/{portfolio_id}", headers=headers)

    def activate_portfolio(self, portfolio_id, headers):
        return self._request("POST", f"/advisory/portfolios/{portfolio_id}/activate", {}, headers)

    def freeze_portfolio(self, portfolio_id, headers):
        return self._request("POST", f"/advisory/portfolios/{portfolio_id}/freeze", {}, headers)

    def unfreeze_portfolio(self, portfolio_id, headers):
        return self._request("POST", f"/advisory/portfolios/{portfolio_id}/unfreeze", {}, headers)

    def close_portfolio(self, portfolio_id, headers):
        return self._request("POST", f"/advisory/portfolios/{portfolio_id}/close", {}, headers)

    def create_cash_movement(self, portfolio_id, payload, headers):
        return self._request("POST", f"/advisory/portfolios/{portfolio_id}/cash-movements",
                             payload, headers)

    # ------------------------------------------------------------------
    # Securities
    # ------------------------------------------------------------------
    def create_security(self, payload, headers):
        return self._request("POST", "/advisory/securities", payload, headers)

    def list_securities(self, headers, params=None):
        return self._request("GET", "/advisory/securities", headers=headers, params=params)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/advisory/securities/{security_id}", headers=headers)

    def reprice_security(self, security_id, new_price_cents, headers):
        return self._request("POST", f"/advisory/securities/{security_id}/reprice",
                             {"new_price_cents": new_price_cents}, headers)

    def set_trading_status(self, security_id, trading_status, headers):
        return self._request("POST", f"/advisory/securities/{security_id}/set-trading-status",
                             {"trading_status": trading_status}, headers)

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------
    def create_position(self, payload, headers):
        return self._request("POST", "/advisory/positions", payload, headers)

    def list_positions(self, headers, params=None):
        return self._request("GET", "/advisory/positions", headers=headers, params=params)

    def get_position(self, position_id, headers):
        return self._request("GET", f"/advisory/positions/{position_id}", headers=headers)

    # ------------------------------------------------------------------
    # Restricted list
    # ------------------------------------------------------------------
    def create_restricted_list_entry(self, payload, headers):
        return self._request("POST", "/advisory/restricted-list-entries", payload, headers)

    def list_restricted_list_entries(self, headers, params=None):
        return self._request("GET", "/advisory/restricted-list-entries",
                             headers=headers, params=params)

    def get_restricted_list_entry(self, entry_id, headers):
        return self._request("GET", f"/advisory/restricted-list-entries/{entry_id}",
                             headers=headers)

    def terminate_restricted_list_entry(self, entry_id, headers):
        return self._request("POST", f"/advisory/restricted-list-entries/{entry_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Rebalance proposals
    # ------------------------------------------------------------------
    def create_rebalance_proposal(self, payload, headers):
        return self._request("POST", "/advisory/rebalance-proposals", payload, headers)

    def list_rebalance_proposals(self, headers, params=None):
        return self._request("GET", "/advisory/rebalance-proposals",
                             headers=headers, params=params)

    def get_rebalance_proposal(self, proposal_id, headers):
        return self._request("GET", f"/advisory/rebalance-proposals/{proposal_id}",
                             headers=headers)

    def approve_proposal(self, proposal_id, headers):
        return self._request("POST", f"/advisory/rebalance-proposals/{proposal_id}/approve",
                             {}, headers)

    def request_changes_proposal(self, proposal_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST",
                             f"/advisory/rebalance-proposals/{proposal_id}/request-changes",
                             payload, headers)

    def revise_proposal(self, proposal_id, headers):
        return self._request("POST", f"/advisory/rebalance-proposals/{proposal_id}/revise",
                             {}, headers)

    def reject_proposal(self, proposal_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/advisory/rebalance-proposals/{proposal_id}/reject",
                             payload, headers)

    def cancel_proposal(self, proposal_id, headers):
        return self._request("POST", f"/advisory/rebalance-proposals/{proposal_id}/cancel",
                             {}, headers)

    def execute_proposal(self, proposal_id, headers):
        return self._request("POST", f"/advisory/rebalance-proposals/{proposal_id}/execute",
                             {}, headers)

    # ------------------------------------------------------------------
    # Trade instructions
    # ------------------------------------------------------------------
    def list_trade_instructions(self, headers, params=None):
        return self._request("GET", "/advisory/trade-instructions",
                             headers=headers, params=params)

    def get_trade_instruction(self, trade_id, headers):
        return self._request("GET", f"/advisory/trade-instructions/{trade_id}", headers=headers)

    def release_trade(self, trade_id, headers):
        return self._request("POST", f"/advisory/trade-instructions/{trade_id}/release",
                             {}, headers)

    def void_trade(self, trade_id, headers):
        return self._request("POST", f"/advisory/trade-instructions/{trade_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Withdrawal requests
    # ------------------------------------------------------------------
    def create_withdrawal_request(self, payload, headers):
        return self._request("POST", "/advisory/withdrawal-requests", payload, headers)

    def list_withdrawal_requests(self, headers, params=None):
        return self._request("GET", "/advisory/withdrawal-requests",
                             headers=headers, params=params)

    def get_withdrawal_request(self, withdrawal_id, headers):
        return self._request("GET", f"/advisory/withdrawal-requests/{withdrawal_id}",
                             headers=headers)

    def model_withdrawal(self, withdrawal_id, headers):
        return self._request("POST",
                             f"/advisory/withdrawal-requests/{withdrawal_id}/model-impact",
                             {}, headers)

    def approve_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/advisory/withdrawal-requests/{withdrawal_id}/approve",
                             {}, headers)

    def reject_withdrawal(self, withdrawal_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/advisory/withdrawal-requests/{withdrawal_id}/reject",
                             payload, headers)

    def cancel_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/advisory/withdrawal-requests/{withdrawal_id}/cancel",
                             {}, headers)

    def settle_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/advisory/withdrawal-requests/{withdrawal_id}/settle",
                             {}, headers)

    # ------------------------------------------------------------------
    # Performance reports
    # ------------------------------------------------------------------
    def create_performance_report(self, payload, headers):
        return self._request("POST", "/advisory/performance-reports", payload, headers)

    def list_performance_reports(self, headers, params=None):
        return self._request("GET", "/advisory/performance-reports",
                             headers=headers, params=params)

    def get_performance_report(self, report_id, headers):
        return self._request("GET", f"/advisory/performance-reports/{report_id}",
                             headers=headers)

    def finalize_performance_report(self, report_id, headers):
        return self._request("POST",
                             f"/advisory/performance-reports/{report_id}/finalize",
                             {}, headers)

    # ------------------------------------------------------------------
    # IPS amendments
    # ------------------------------------------------------------------
    def create_ips_amendment(self, payload, headers):
        return self._request("POST", "/advisory/ips-amendments", payload, headers)

    def list_ips_amendments(self, headers, params=None):
        return self._request("GET", "/advisory/ips-amendments", headers=headers, params=params)

    def get_ips_amendment(self, amendment_id, headers):
        return self._request("GET", f"/advisory/ips-amendments/{amendment_id}", headers=headers)

    def submit_ips_amendment(self, amendment_id, headers):
        return self._request("POST", f"/advisory/ips-amendments/{amendment_id}/submit",
                             {}, headers)

    def vote_ips_amendment(self, amendment_id, decision, headers):
        return self._request("POST", f"/advisory/ips-amendments/{amendment_id}/vote",
                             {"decision": decision}, headers)

    def finalize_ips_amendment(self, amendment_id, ratified_minute_id,
                               expected_ips_version, headers):
        return self._request("POST", f"/advisory/ips-amendments/{amendment_id}/finalize",
                             {"ratified_minute_id": ratified_minute_id,
                              "expected_ips_version": expected_ips_version}, headers)

    def withdraw_ips_amendment(self, amendment_id, headers):
        return self._request("POST", f"/advisory/ips-amendments/{amendment_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Committee minutes
    # ------------------------------------------------------------------
    def create_committee_minute(self, payload, headers):
        return self._request("POST", "/advisory/committee-minutes", payload, headers)

    def list_committee_minutes(self, headers, params=None):
        return self._request("GET", "/advisory/committee-minutes",
                             headers=headers, params=params)

    def get_committee_minute(self, minute_id, headers):
        return self._request("GET", f"/advisory/committee-minutes/{minute_id}", headers=headers)

    def ratify_committee_minute(self, minute_id, headers):
        return self._request("POST", f"/advisory/committee-minutes/{minute_id}/ratify",
                             {}, headers)

    # ------------------------------------------------------------------
    # Cash flow events (read-only ledger)
    # ------------------------------------------------------------------
    def list_cash_flow_events(self, headers, params=None):
        return self._request("GET", "/advisory/cash-flow-events",
                             headers=headers, params=params)

    def get_cash_flow_event(self, event_id, headers):
        return self._request("GET", f"/advisory/cash-flow-events/{event_id}", headers=headers)

    # ------------------------------------------------------------------
    # Operations checkpoint
    # ------------------------------------------------------------------
    def run_compliance_checkpoint(self, headers):
        return self._request("POST", "/advisory/compliance-checkpoints", {}, headers)


api_client = ApiClient()
