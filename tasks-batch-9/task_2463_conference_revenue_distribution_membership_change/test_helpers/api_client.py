"""Typed API client: one method per endpoint in the PRD's endpoint table."""

from typing import Any, Dict, Optional

import requests
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Thin, explicit wrapper over the conference revenue distribution API."""

    # -- helpers ----------------------------------------------------------
    def _patch(
        self,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._request("PATCH", path, payload=payload, headers=headers)

    # -- logical clock ----------------------------------------------------
    def set_clock(
        self, to_iso8601: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/_clock/set_current_utc", json={"to_iso8601": to_iso8601}, headers=headers
        )

    # -- conference -------------------------------------------------------
    def create_conference(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/conference", json=payload, headers=headers)

    def get_conference(
        self, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get("/conference", headers=headers)

    def create_reserve_transfer(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post(
            "/conference/reserve-transfers", json=payload, headers=headers
        )

    # -- venues -----------------------------------------------------------
    def create_venue(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/venues", json=payload, headers=headers)

    # -- members ----------------------------------------------------------
    def create_member(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/members", json=payload, headers=headers)

    def get_member(
        self, member_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/members/{member_id}", headers=headers)

    def list_members(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/members", headers=headers, params=params)

    def update_member(
        self,
        member_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self._patch(f"/members/{member_id}", payload=payload, headers=headers)

    def create_entry_fee_payment(
        self,
        member_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/members/{member_id}/entry-fee-payments", json=payload, headers=headers
        )

    def advance_member_phase(
        self,
        member_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/members/{member_id}/phase-advance", json=payload or {}, headers=headers
        )

    def file_withdrawal_notice(
        self,
        member_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/members/{member_id}/withdrawal-notice", json=payload, headers=headers
        )

    def rescind_withdrawal_notice(
        self,
        member_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/members/{member_id}/withdrawal-notice/rescind",
            json=payload or {},
            headers=headers,
        )

    def get_schedule_compliance(
        self, member_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/members/{member_id}/schedule-compliance", headers=headers)

    def get_postseason_unit_valuation(
        self, member_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(
            f"/members/{member_id}/postseason-unit-valuation", headers=headers
        )

    def get_exit_settlement(
        self, member_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/members/{member_id}/exit-settlement", headers=headers)

    def list_member_distribution_lines(
        self,
        member_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/members/{member_id}/distribution-lines", headers=headers, params=params
        )

    def list_member_postseason_units(
        self,
        member_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/members/{member_id}/postseason-units", headers=headers, params=params
        )

    def list_member_ballots(
        self,
        member_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/members/{member_id}/ballots", headers=headers, params=params
        )

    def create_bowl_appearance(
        self,
        member_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/members/{member_id}/bowl-appearances", json=payload, headers=headers
        )

    def list_member_bowl_appearances(
        self,
        member_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/members/{member_id}/bowl-appearances", headers=headers, params=params
        )

    # -- revenue pools ----------------------------------------------------
    def create_revenue_pool(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/revenue-pools", json=payload, headers=headers)

    def get_revenue_pool(
        self, pool_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/revenue-pools/{pool_id}", headers=headers)

    def list_revenue_pools(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/revenue-pools", headers=headers, params=params)

    def open_revenue_pool(
        self,
        pool_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/revenue-pools/{pool_id}/open", json=payload or {}, headers=headers
        )

    def close_revenue_pool_books(
        self,
        pool_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/revenue-pools/{pool_id}/close-books", json=payload, headers=headers
        )

    def reopen_revenue_pool(
        self,
        pool_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/revenue-pools/{pool_id}/reopen", json=payload or {}, headers=headers
        )

    def close_revenue_pool(
        self,
        pool_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/revenue-pools/{pool_id}/close", json=payload or {}, headers=headers
        )

    def create_distribution_run(
        self,
        pool_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/revenue-pools/{pool_id}/distribution-runs",
            json=payload,
            headers=headers,
        )

    def list_pool_distribution_runs(
        self,
        pool_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/revenue-pools/{pool_id}/distribution-runs",
            headers=headers,
            params=params,
        )

    # -- distribution runs ------------------------------------------------
    def get_distribution_run(
        self, run_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/distribution-runs/{run_id}", headers=headers)

    def list_distribution_runs(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/distribution-runs", headers=headers, params=params)

    def list_distribution_run_lines(
        self,
        run_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/distribution-runs/{run_id}/lines", headers=headers, params=params
        )

    def get_run_reconciliation(
        self, run_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(
            f"/distribution-runs/{run_id}/reconciliation", headers=headers
        )

    def post_distribution_run(
        self,
        run_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/distribution-runs/{run_id}/post", json=payload or {}, headers=headers
        )

    def reverse_distribution_run(
        self,
        run_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/distribution-runs/{run_id}/reverse", json=payload or {}, headers=headers
        )

    # -- bowl appearances -------------------------------------------------
    def get_bowl_appearance(
        self, appearance_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/bowl-appearances/{appearance_id}", headers=headers)

    def begin_bowl_review(
        self,
        appearance_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/bowl-appearances/{appearance_id}/begin-review",
            json=payload or {},
            headers=headers,
        )

    def request_bowl_revision(
        self,
        appearance_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/bowl-appearances/{appearance_id}/request-revision",
            json=payload or {},
            headers=headers,
        )

    def resubmit_bowl_appearance(
        self,
        appearance_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/bowl-appearances/{appearance_id}/resubmit",
            json=payload,
            headers=headers,
        )

    def approve_bowl_appearance(
        self,
        appearance_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/bowl-appearances/{appearance_id}/approve",
            json=payload or {},
            headers=headers,
        )

    def void_bowl_appearance(
        self,
        appearance_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/bowl-appearances/{appearance_id}/void",
            json=payload or {},
            headers=headers,
        )

    def list_appearance_postseason_units(
        self,
        appearance_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/bowl-appearances/{appearance_id}/postseason-units",
            headers=headers,
            params=params,
        )

    # -- membership actions -----------------------------------------------
    def create_membership_action(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/membership-actions", json=payload, headers=headers)

    def get_membership_action(
        self, action_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/membership-actions/{action_id}", headers=headers)

    def list_membership_actions(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/membership-actions", headers=headers, params=params)

    def open_action_voting(
        self,
        action_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/membership-actions/{action_id}/open-voting",
            json=payload or {},
            headers=headers,
        )

    def withdraw_membership_action(
        self,
        action_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/membership-actions/{action_id}/withdraw",
            json=payload or {},
            headers=headers,
        )

    def cast_action_ballot(
        self,
        action_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/membership-actions/{action_id}/ballots", json=payload, headers=headers
        )

    def list_action_ballots(
        self,
        action_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/membership-actions/{action_id}/ballots", headers=headers, params=params
        )

    def amend_membership_action(
        self,
        action_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/membership-actions/{action_id}/amend", json=payload, headers=headers
        )

    def close_action_voting(
        self,
        action_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/membership-actions/{action_id}/close-voting",
            json=payload or {},
            headers=headers,
        )

    def execute_membership_action(
        self,
        action_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/membership-actions/{action_id}/execute",
            json=payload or {},
            headers=headers,
        )

    # -- budget proposals -------------------------------------------------
    def create_budget_proposal(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/budget-proposals", json=payload, headers=headers)

    def get_budget_proposal(
        self, proposal_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/budget-proposals/{proposal_id}", headers=headers)

    def list_budget_proposals(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/budget-proposals", headers=headers, params=params)

    def open_budget_voting(
        self,
        proposal_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/budget-proposals/{proposal_id}/open-voting",
            json=payload or {},
            headers=headers,
        )

    def cast_budget_ballot(
        self,
        proposal_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/budget-proposals/{proposal_id}/ballots", json=payload, headers=headers
        )

    def list_budget_ballots(
        self,
        proposal_id: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get(
            f"/budget-proposals/{proposal_id}/ballots", headers=headers, params=params
        )

    def close_budget_voting(
        self,
        proposal_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/budget-proposals/{proposal_id}/close-voting",
            json=payload or {},
            headers=headers,
        )

    # -- protected rivalries ----------------------------------------------
    def create_protected_rivalry(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/protected-rivalries", json=payload, headers=headers)

    def get_protected_rivalry(
        self, rivalry_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/protected-rivalries/{rivalry_id}", headers=headers)

    def list_protected_rivalries(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/protected-rivalries", headers=headers, params=params)

    # -- schedule games ---------------------------------------------------
    def create_schedule_game(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/schedule-games", json=payload, headers=headers)

    def get_schedule_game(
        self, game_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/schedule-games/{game_id}", headers=headers)

    def list_schedule_games(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/schedule-games", headers=headers, params=params)

    def play_schedule_game(
        self,
        game_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/schedule-games/{game_id}/play", json=payload or {}, headers=headers
        )

    def cancel_schedule_game(
        self,
        game_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/schedule-games/{game_id}/cancel", json=payload or {}, headers=headers
        )

    # -- championship events ----------------------------------------------
    def create_championship_event(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/championship-events", json=payload, headers=headers)

    def get_championship_event(
        self, event_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/championship-events/{event_id}", headers=headers)

    def list_championship_events(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/championship-events", headers=headers, params=params)

    def host_championship_event(
        self,
        event_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/championship-events/{event_id}/host", json=payload or {}, headers=headers
        )

    def settle_championship_event(
        self,
        event_id: str,
        payload: Dict[str, Any],
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/championship-events/{event_id}/settle", json=payload, headers=headers
        )

    def cancel_championship_event(
        self,
        event_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/championship-events/{event_id}/cancel",
            json=payload or {},
            headers=headers,
        )

    # -- audit reports ----------------------------------------------------
    def create_audit_report(
        self, payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.post("/audit-reports", json=payload, headers=headers)

    def get_audit_report(
        self, report_id: str, headers: Optional[Dict[str, str]] = None
    ) -> requests.Response:
        return self.get(f"/audit-reports/{report_id}", headers=headers)

    def list_audit_reports(
        self,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.get("/audit-reports", headers=headers, params=params)

    def issue_audit_report(
        self,
        report_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/audit-reports/{report_id}/issue", json=payload or {}, headers=headers
        )

    def accept_audit_report(
        self,
        report_id: str,
        payload: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> requests.Response:
        return self.post(
            f"/audit-reports/{report_id}/accept", json=payload or {}, headers=headers
        )


api_client = ApiClient()
