"""API client: one method per endpoint defined in the PRD.

The API is mounted under /api (PRD introduction), so every path carries that
prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def open_registration(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/open-registration", {}, headers)

    def close_registration(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/close-registration", {}, headers)

    def go_live(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/go-live", {}, headers)

    def finalize_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/finalize", {}, headers)

    def checkpoint(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/checkpoint", {}, headers)

    def allocate_bids(self, event_id, expected_event_version, headers):
        return self._request("POST", f"/api/events/{event_id}/allocate-bids",
                             {"expected_event_version": expected_event_version}, headers)

    def list_event_divisions(self, event_id, headers, params=None):
        return self._request("GET", f"/api/events/{event_id}/divisions",
                             headers=headers, params=params)

    def list_event_teams(self, event_id, headers, params=None):
        return self._request("GET", f"/api/events/{event_id}/teams",
                             headers=headers, params=params)

    def list_event_sessions(self, event_id, headers, params=None):
        return self._request("GET", f"/api/events/{event_id}/sessions",
                             headers=headers, params=params)

    def list_event_warm_up_assignments(self, event_id, headers, params=None):
        return self._request("GET", f"/api/events/{event_id}/warm-up-assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Divisions
    # ------------------------------------------------------------------
    def create_division(self, payload, headers):
        return self._request("POST", "/api/divisions", payload, headers)

    def get_division(self, division_id, headers):
        return self._request("GET", f"/api/divisions/{division_id}", headers=headers)

    def get_division_standings(self, division_id, headers, params=None):
        return self._request("GET", f"/api/divisions/{division_id}/standings",
                             headers=headers, params=params)

    def generate_schedule(self, division_id, expected_division_version, headers):
        return self._request("POST", f"/api/divisions/{division_id}/generate-schedule",
                             {"expected_division_version": expected_division_version}, headers)

    def list_division_teams(self, division_id, headers, params=None):
        return self._request("GET", f"/api/divisions/{division_id}/teams",
                             headers=headers, params=params)

    def list_division_performances(self, division_id, headers, params=None):
        return self._request("GET", f"/api/divisions/{division_id}/performances",
                             headers=headers, params=params)

    def list_division_bids(self, division_id, headers, params=None):
        return self._request("GET", f"/api/divisions/{division_id}/bids",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Teams
    # ------------------------------------------------------------------
    def create_team(self, payload, headers):
        return self._request("POST", "/api/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/api/teams/{team_id}", headers=headers)

    def lock_roster(self, team_id, headers):
        return self._request("POST", f"/api/teams/{team_id}/lock-roster", {}, headers)

    def check_in_team(self, team_id, athlete_ids, headers):
        return self._request("POST", f"/api/teams/{team_id}/check-in",
                             {"athlete_ids": athlete_ids}, headers)

    def withdraw_team(self, team_id, headers):
        return self._request("POST", f"/api/teams/{team_id}/withdraw", {}, headers)

    def disqualify_team(self, team_id, headers):
        return self._request("POST", f"/api/teams/{team_id}/disqualify", {}, headers)

    def list_team_performances(self, team_id, headers, params=None):
        return self._request("GET", f"/api/teams/{team_id}/performances",
                             headers=headers, params=params)

    def list_team_roster_entries(self, team_id, headers, params=None):
        return self._request("GET", f"/api/teams/{team_id}/roster-entries",
                             headers=headers, params=params)

    def list_team_bids(self, team_id, headers, params=None):
        return self._request("GET", f"/api/teams/{team_id}/bids",
                             headers=headers, params=params)

    def list_team_warm_up_assignments(self, team_id, headers, params=None):
        return self._request("GET", f"/api/teams/{team_id}/warm-up-assignments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Music submissions
    # ------------------------------------------------------------------
    def create_music_submission(self, team_id, payload, headers):
        return self._request("POST", f"/api/teams/{team_id}/music-submissions",
                             payload, headers)

    def list_music_submissions(self, team_id, headers, params=None):
        return self._request("GET", f"/api/teams/{team_id}/music-submissions",
                             headers=headers, params=params)

    def review_music_submission(self, submission_id, payload, headers):
        return self._request("POST", f"/api/music-submissions/{submission_id}/review",
                             payload, headers)

    # ------------------------------------------------------------------
    # Athletes & roster entries
    # ------------------------------------------------------------------
    def create_athlete(self, payload, headers):
        return self._request("POST", "/api/athletes", payload, headers)

    def get_athlete(self, athlete_id, headers):
        return self._request("GET", f"/api/athletes/{athlete_id}", headers=headers)

    def list_athlete_roster_entries(self, athlete_id, headers, params=None):
        return self._request("GET", f"/api/athletes/{athlete_id}/roster-entries",
                             headers=headers, params=params)

    def create_roster_entry(self, payload, headers):
        return self._request("POST", "/api/roster-entries", payload, headers)

    def get_roster_entry(self, entry_id, headers):
        return self._request("GET", f"/api/roster-entries/{entry_id}", headers=headers)

    def delete_roster_entry(self, entry_id, headers):
        return self._request("DELETE", f"/api/roster-entries/{entry_id}", headers=headers)

    def set_eligibility(self, entry_id, eligibility_status, headers):
        return self._request("POST", f"/api/roster-entries/{entry_id}/set-eligibility",
                             {"eligibility_status": eligibility_status}, headers)

    # ------------------------------------------------------------------
    # Judges
    # ------------------------------------------------------------------
    def create_judge(self, payload, headers):
        return self._request("POST", "/api/judges", payload, headers)

    def get_judge(self, judge_id, headers):
        return self._request("GET", f"/api/judges/{judge_id}", headers=headers)

    def list_judge_score_sheets(self, judge_id, headers, params=None):
        return self._request("GET", f"/api/judges/{judge_id}/score-sheets",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Performances, score sheets, deductions, appeals
    # ------------------------------------------------------------------
    def get_performance(self, performance_id, headers):
        return self._request("GET", f"/api/performances/{performance_id}", headers=headers)

    def mark_performed(self, performance_id, payload, headers):
        return self._request("POST", f"/api/performances/{performance_id}/mark-performed",
                             payload, headers)

    def create_score_sheet(self, performance_id, payload, headers):
        return self._request("POST", f"/api/performances/{performance_id}/score-sheets",
                             payload, headers)

    def list_performance_score_sheets(self, performance_id, headers, params=None):
        return self._request("GET", f"/api/performances/{performance_id}/score-sheets",
                             headers=headers, params=params)

    def get_score_sheet(self, sheet_id, headers):
        return self._request("GET", f"/api/score-sheets/{sheet_id}", headers=headers)

    def patch_score_sheet(self, sheet_id, payload, headers):
        return self._request("PATCH", f"/api/score-sheets/{sheet_id}", payload, headers)

    def submit_score_sheet(self, sheet_id, headers):
        return self._request("POST", f"/api/score-sheets/{sheet_id}/submit", {}, headers)

    def confirm_official(self, performance_id, headers):
        return self._request("POST", f"/api/performances/{performance_id}/confirm-official",
                             {}, headers)

    def create_deduction(self, performance_id, payload, headers):
        return self._request("POST", f"/api/performances/{performance_id}/deductions",
                             payload, headers)

    def list_performance_deductions(self, performance_id, headers, params=None):
        return self._request("GET", f"/api/performances/{performance_id}/deductions",
                             headers=headers, params=params)

    def get_deduction(self, deduction_id, headers):
        return self._request("GET", f"/api/deductions/{deduction_id}", headers=headers)

    def list_deductions(self, headers, params=None):
        return self._request("GET", "/api/deductions", headers=headers, params=params)

    def patch_deduction(self, deduction_id, payload, headers):
        return self._request("PATCH", f"/api/deductions/{deduction_id}", payload, headers)

    def void_deduction(self, deduction_id, headers):
        return self._request("POST", f"/api/deductions/{deduction_id}/void", {}, headers)

    def create_appeal(self, deduction_id, payload, headers):
        return self._request("POST", f"/api/deductions/{deduction_id}/appeals",
                             payload, headers)

    def list_deduction_appeals(self, deduction_id, headers, params=None):
        return self._request("GET", f"/api/deductions/{deduction_id}/appeals",
                             headers=headers, params=params)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/api/appeals/{appeal_id}", headers=headers)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/api/appeals", headers=headers, params=params)

    def resolve_appeal(self, appeal_id, decision, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/resolve",
                             {"decision": decision}, headers)

    def resubmit_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/api/appeals/{appeal_id}/resubmit",
                             payload, headers)

    # ------------------------------------------------------------------
    # Bids
    # ------------------------------------------------------------------
    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/api/bids/{bid_id}", headers=headers)

    def accept_bid(self, bid_id, headers):
        return self._request("POST", f"/api/bids/{bid_id}/accept", {}, headers)

    def decline_bid(self, bid_id, headers):
        return self._request("POST", f"/api/bids/{bid_id}/decline", {}, headers)

    # ------------------------------------------------------------------
    # Sessions & ticket orders
    # ------------------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/api/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/api/sessions/{session_id}", headers=headers)

    def list_session_ticket_orders(self, session_id, headers, params=None):
        return self._request("GET", f"/api/sessions/{session_id}/ticket-orders",
                             headers=headers, params=params)

    def create_ticket_order(self, payload, headers):
        return self._request("POST", "/api/ticket-orders", payload, headers)

    def get_ticket_order(self, order_id, headers):
        return self._request("GET", f"/api/ticket-orders/{order_id}", headers=headers)

    def pay_ticket_order(self, order_id, headers):
        return self._request("POST", f"/api/ticket-orders/{order_id}/pay", {}, headers)

    def cancel_ticket_order(self, order_id, headers):
        return self._request("POST", f"/api/ticket-orders/{order_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Warm-up assignments
    # ------------------------------------------------------------------
    def create_warm_up_assignment(self, payload, headers):
        return self._request("POST", "/api/warm-up-assignments", payload, headers)

    def get_warm_up_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/warm-up-assignments/{assignment_id}",
                             headers=headers)

    def release_warm_up_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/warm-up-assignments/{assignment_id}/release",
                             {}, headers)


api_client = ApiClient()
