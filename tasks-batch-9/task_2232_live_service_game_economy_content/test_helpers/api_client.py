"""API client: one method per endpoint declared by the PRD."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed surface over the live-service economy API (flat collection topology)."""

    # ---- Seasons ---------------------------------------------------------
    def create_season(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/seasons/{season_id}", headers=headers)

    def set_season_status(self, season_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/seasons/{season_id}/status", payload, headers)

    def list_season_episodes(self, season_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/seasons/{season_id}/episodes", headers=headers, params=params)

    def get_economy_summary(self, season_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/seasons/{season_id}/economy-summary", headers=headers, params=params)

    # ---- Episodes --------------------------------------------------------
    def create_episode(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/episodes", payload, headers)

    def get_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def schedule_episode(self, episode_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/episodes/{episode_id}/schedule", payload or {}, headers)

    def release_episode(self, episode_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/episodes/{episode_id}/release", {}, headers)

    def rollback_episode(self, episode_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/episodes/{episode_id}/rollback", payload, headers)

    # ---- Capacity clusters ----------------------------------------------
    def create_cluster(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/capacity-clusters", payload, headers)

    def get_cluster(self, cluster_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/capacity-clusters/{cluster_id}", headers=headers)

    def set_cluster_status(self, cluster_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/capacity-clusters/{cluster_id}/status", payload, headers)

    # ---- Live events -----------------------------------------------------
    def create_live_event(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/live-events", payload, headers)

    def get_live_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/live-events/{event_id}", headers=headers)

    def list_live_events(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/live-events", headers=headers, params=params)

    def approve_live_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/live-events/{event_id}/approve", {}, headers)

    def start_live_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/live-events/{event_id}/start", {}, headers)

    def complete_live_event(self, event_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/live-events/{event_id}/complete", {}, headers)

    def rollback_live_event(self, event_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/live-events/{event_id}/rollback", payload, headers)

    # ---- Players ---------------------------------------------------------
    def create_player(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    def list_players(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/players", headers=headers, params=params)

    def create_currency_account(self, player_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/players/{player_id}/currency-accounts", payload, headers)

    def list_currency_accounts(self, player_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/players/{player_id}/currency-accounts", headers=headers, params=params)

    def ingest_engagement_event(self, player_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/players/{player_id}/engagement-events", payload, headers)

    def set_spend_guard(self, player_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/players/{player_id}/spend-guard", payload, headers)

    def get_pacing(self, player_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/players/{player_id}/pacing", headers=headers, params=params)

    # ---- Currency accounts and ledger ------------------------------------
    def get_currency_account(self, account_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/currency-accounts/{account_id}", headers=headers)

    def create_adjustment(self, account_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/currency-accounts/{account_id}/adjustments", payload, headers)

    def list_ledger_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    def get_ledger_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    # ---- Offers and disclosures ------------------------------------------
    def create_offer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/offers", payload, headers)

    def get_offer(self, offer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def submit_offer(self, offer_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/offers/{offer_id}/submit", {}, headers)

    def review_offer(self, offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/offers/{offer_id}/review", payload, headers)

    def publish_offer(self, offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/offers/{offer_id}/publish", payload, headers)

    def set_offer_availability(self, offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/offers/{offer_id}/availability", payload, headers)

    def create_disclosure(self, offer_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/offers/{offer_id}/disclosures", payload, headers)

    def list_disclosures(self, offer_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/offers/{offer_id}/disclosures", headers=headers, params=params)

    def publish_disclosure(self, offer_id: str, disclosure_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/offers/{offer_id}/disclosures/{disclosure_id}/publish", {}, headers
        )

    def get_offer_quote(self, offer_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/offers/{offer_id}/quote", headers=headers, params=params)

    # ---- Purchases -------------------------------------------------------
    def create_purchase(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/purchases", payload, headers)

    def get_purchase(self, purchase_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/purchases/{purchase_id}", headers=headers)

    def list_purchases(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/purchases", headers=headers, params=params)

    def settle_purchase(self, purchase_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/purchases/{purchase_id}/settlement", payload, headers)

    # ---- Refund requests -------------------------------------------------
    def create_refund_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/refund-requests", payload, headers)

    def get_refund_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/refund-requests/{request_id}", headers=headers)

    def list_refund_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/refund-requests", headers=headers, params=params)

    def decide_refund_request(self, request_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/refund-requests/{request_id}/decision", payload, headers)

    def execute_refund_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/refund-requests/{request_id}/execute", {}, headers)

    # ---- Balance changes and comms notices -------------------------------
    def create_balance_change(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/balance-changes", payload, headers)

    def get_balance_change(self, change_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/balance-changes/{change_id}", headers=headers)

    def list_balance_changes(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/balance-changes", headers=headers, params=params)

    def advance_balance_change(self, change_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/balance-changes/{change_id}/advance", payload, headers)

    def revert_balance_change(self, change_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/balance-changes/{change_id}/revert", payload, headers)

    def create_comms_notice(self, change_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/balance-changes/{change_id}/comms-notices", payload, headers)

    def list_comms_notices(self, change_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/balance-changes/{change_id}/comms-notices", headers=headers, params=params)

    def publish_comms_notice(self, change_id: str, notice_id: str, headers: Dict[str, str]):
        return self._request(
            "POST", f"/balance-changes/{change_id}/comms-notices/{notice_id}/publish", {}, headers
        )

    # ---- Inflation monitoring -------------------------------------------
    def create_monitoring_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/monitoring-runs", payload, headers)

    def get_monitoring_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/monitoring-runs/{run_id}", headers=headers)

    def list_monitoring_runs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/monitoring-runs", headers=headers, params=params)

    def compute_monitoring_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/monitoring-runs/{run_id}/compute", {}, headers)

    def decide_monitoring_run(self, run_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/monitoring-runs/{run_id}/decision", payload, headers)

    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, to_iso8601: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
