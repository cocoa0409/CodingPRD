"""Typed HTTP client — one method per endpoint in the PRD endpoint table."""

from typing import Any, Dict, Optional

import requests

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """One method per PRD endpoint. Returns raw responses for status assertions."""

    # ------------------------------------------------------------------ #
    # Logical clock
    # ------------------------------------------------------------------ #
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------------ #
    # Forecast cycles
    # ------------------------------------------------------------------ #
    def list_forecast_cycles(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/forecast-cycles", headers=headers, params=params)

    def get_forecast_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/forecast-cycles/{cycle_id}", headers=headers)

    def create_forecast_cycle(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/forecast-cycles", payload, headers)

    def update_forecast_cycle(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/forecast-cycles/{cycle_id}", payload, headers)

    def lock_inputs(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/forecast-cycles/{cycle_id}/lock-inputs", {}, headers)

    def reopen_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/forecast-cycles/{cycle_id}/reopen", {}, headers)

    def certify_cycle(self, cycle_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/forecast-cycles/{cycle_id}/certify", {}, headers)

    # ------------------------------------------------------------------ #
    # Economic scenarios
    # ------------------------------------------------------------------ #
    def list_cycle_scenarios(
        self, cycle_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/forecast-cycles/{cycle_id}/scenarios", headers=headers, params=params
        )

    def create_scenario(
        self, cycle_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/forecast-cycles/{cycle_id}/scenarios", payload, headers)

    def get_scenario(self, scenario_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/economic-scenarios/{scenario_id}", headers=headers)

    def update_scenario(
        self, scenario_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/economic-scenarios/{scenario_id}", payload, headers)

    def delete_scenario(self, scenario_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("DELETE", f"/economic-scenarios/{scenario_id}", headers=headers)

    # ------------------------------------------------------------------ #
    # Computed previews
    # ------------------------------------------------------------------ #
    def get_scenario_estimates(
        self, cycle_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET",
            f"/forecast-cycles/{cycle_id}/scenario-estimates",
            headers=headers,
            params=params,
        )

    def get_error_history(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/revenue-sources/{source_id}/error-history", headers=headers)

    def get_fund_adequacy(self, fund_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reserve-funds/{fund_id}/adequacy", headers=headers)

    # ------------------------------------------------------------------ #
    # Consensus rounds
    # ------------------------------------------------------------------ #
    def list_cycle_consensus_rounds(
        self, cycle_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/forecast-cycles/{cycle_id}/consensus-rounds", headers=headers, params=params
        )

    def list_consensus_rounds(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/consensus-rounds", headers=headers, params=params)

    def get_consensus_round(self, round_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/consensus-rounds/{round_id}", headers=headers)

    def create_consensus_round(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/consensus-rounds", payload, headers)

    def submit_round(self, round_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/consensus-rounds/{round_id}/submit", {}, headers)

    def ratify_round(self, round_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/consensus-rounds/{round_id}/ratify", {}, headers)

    # ------------------------------------------------------------------ #
    # Revenue sources
    # ------------------------------------------------------------------ #
    def list_revenue_sources(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/revenue-sources", headers=headers, params=params)

    def get_revenue_source(self, source_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/revenue-sources/{source_id}", headers=headers)

    def create_revenue_source(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/revenue-sources", payload, headers)

    def update_revenue_source(
        self, source_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/revenue-sources/{source_id}", payload, headers)

    # ------------------------------------------------------------------ #
    # Policy change adjustments
    # ------------------------------------------------------------------ #
    def list_policy_adjustments(
        self, source_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/revenue-sources/{source_id}/policy-adjustments", headers=headers, params=params
        )

    def get_policy_adjustment(
        self, adjustment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/policy-adjustments/{adjustment_id}", headers=headers)

    def create_policy_adjustment(
        self, source_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/revenue-sources/{source_id}/policy-adjustments", payload, headers
        )

    def update_policy_adjustment(
        self, adjustment_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/policy-adjustments/{adjustment_id}", payload, headers)

    def delete_policy_adjustment(
        self, adjustment_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("DELETE", f"/policy-adjustments/{adjustment_id}", headers=headers)

    # ------------------------------------------------------------------ #
    # One-time items
    # ------------------------------------------------------------------ #
    def list_one_time_items(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/one-time-items", headers=headers, params=params)

    def get_one_time_item(self, item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/one-time-items/{item_id}", headers=headers)

    def create_one_time_item(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/one-time-items", payload, headers)

    def void_one_time_item(self, item_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/one-time-items/{item_id}/void", {}, headers)

    # ------------------------------------------------------------------ #
    # Source estimates
    # ------------------------------------------------------------------ #
    def list_source_estimates(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/source-estimates", headers=headers, params=params)

    def get_source_estimate(self, estimate_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/source-estimates/{estimate_id}", headers=headers)

    def create_source_estimate(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/source-estimates", payload, headers)

    def update_source_estimate(
        self, estimate_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/source-estimates/{estimate_id}", payload, headers)

    # ------------------------------------------------------------------ #
    # Disagreement records
    # ------------------------------------------------------------------ #
    def list_disagreement_records(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/disagreement-records", headers=headers, params=params)

    def get_disagreement_record(self, record_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/disagreement-records/{record_id}", headers=headers)

    def resolve_disagreement(
        self, record_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/disagreement-records/{record_id}/resolve", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Reserve funds
    # ------------------------------------------------------------------ #
    def list_reserve_funds(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/reserve-funds", headers=headers, params=params)

    def get_reserve_fund(self, fund_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/reserve-funds/{fund_id}", headers=headers)

    def create_reserve_fund(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/reserve-funds", payload, headers)

    def create_deposit(
        self, fund_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/reserve-funds/{fund_id}/deposits", payload, headers)

    def recompute_adequacy(self, fund_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/reserve-funds/{fund_id}/recompute-adequacy", {}, headers)

    # ------------------------------------------------------------------ #
    # Reserve transactions
    # ------------------------------------------------------------------ #
    def list_reserve_transactions(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/reserve-transactions", headers=headers, params=params)

    def get_reserve_transaction(
        self, transaction_id: str, headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("GET", f"/reserve-transactions/{transaction_id}", headers=headers)

    def reverse_transaction(
        self, transaction_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request(
            "POST", f"/reserve-transactions/{transaction_id}/reverse", payload, headers
        )

    # ------------------------------------------------------------------ #
    # Withdrawal requests and ballots
    # ------------------------------------------------------------------ #
    def list_withdrawal_requests(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/withdrawal-requests", headers=headers, params=params)

    def get_withdrawal_request(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/withdrawal-requests/{request_id}", headers=headers)

    def create_withdrawal_request(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/withdrawal-requests", payload, headers)

    def verify_shortfall(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request(
            "POST", f"/withdrawal-requests/{request_id}/verify-shortfall", {}, headers
        )

    def open_vote(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawal-requests/{request_id}/open-vote", {}, headers)

    def list_withdrawal_votes(
        self, request_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request(
            "GET", f"/withdrawal-requests/{request_id}/votes", headers=headers, params=params
        )

    def cast_vote(
        self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", f"/withdrawal-requests/{request_id}/votes", payload, headers)

    def close_vote(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawal-requests/{request_id}/close-vote", {}, headers)

    def execute_withdrawal(self, request_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/withdrawal-requests/{request_id}/execute", {}, headers)

    def get_withdrawal_vote(self, vote_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/withdrawal-votes/{vote_id}", headers=headers)

    # ------------------------------------------------------------------ #
    # Actual collections
    # ------------------------------------------------------------------ #
    def list_actual_collections(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/actual-collections", headers=headers, params=params)

    def get_actual_collection(self, actual_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/actual-collections/{actual_id}", headers=headers)

    def create_actual_collection(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/actual-collections", payload, headers)

    # ------------------------------------------------------------------ #
    # Rating agency briefings
    # ------------------------------------------------------------------ #
    def list_rating_briefings(
        self, headers: Dict[str, str], params: Optional[Dict] = None
    ) -> requests.Response:
        return self._request("GET", "/rating-briefings", headers=headers, params=params)

    def get_rating_briefing(self, briefing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("GET", f"/rating-briefings/{briefing_id}", headers=headers)

    def create_rating_briefing(
        self, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("POST", "/rating-briefings", payload, headers)

    def update_rating_briefing(
        self, briefing_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ) -> requests.Response:
        return self._request("PATCH", f"/rating-briefings/{briefing_id}", payload, headers)

    def publish_briefing(
        self,
        briefing_id: str,
        headers: Dict[str, str],
        payload: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._request(
            "POST", f"/rating-briefings/{briefing_id}/publish", payload or {}, headers
        )

    def retract_briefing(self, briefing_id: str, headers: Dict[str, str]) -> requests.Response:
        return self._request("POST", f"/rating-briefings/{briefing_id}/retract", {}, headers)
