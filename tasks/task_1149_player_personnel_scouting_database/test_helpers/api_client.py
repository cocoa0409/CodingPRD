"""API client: one method per endpoint defined in PRD §4."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601: str, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- scouts ---
    def create_scout(self, payload, headers):
        return self._request("POST", "/scouting/scouts", payload, headers)

    def get_scout(self, scout_id, headers):
        return self._request("GET", f"/scouting/scouts/{scout_id}", headers=headers)

    def get_scout_evaluation(self, scout_id, headers):
        return self._request(
            "GET", f"/scouting/scouts/{scout_id}/evaluation", headers=headers
        )

    def set_scout_weight(self, scout_id, payload, headers):
        return self._request(
            "POST", f"/scouting/scouts/{scout_id}/weight", payload, headers
        )

    # --- prospects ---
    def create_prospect(self, payload, headers):
        return self._request("POST", "/scouting/prospects", payload, headers)

    def list_prospects(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/scouting/prospects", headers=headers, params=params)

    def get_prospect(self, prospect_id, headers):
        return self._request(
            "GET", f"/scouting/prospects/{prospect_id}", headers=headers
        )

    def advance_prospect(self, prospect_id, payload, headers):
        return self._request(
            "POST", f"/scouting/prospects/{prospect_id}/advance", payload, headers
        )

    def mark_drafted(self, prospect_id, headers):
        return self._request(
            "POST", f"/scouting/prospects/{prospect_id}/mark-drafted", {}, headers
        )

    def list_prospect_board_entries(self, prospect_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/scouting/prospects/{prospect_id}/board-entries",
            headers=headers,
            params=params,
        )

    # --- scouting reports ---
    def create_report(self, prospect_id, payload, headers):
        return self._request(
            "POST", f"/scouting/prospects/{prospect_id}/reports", payload, headers
        )

    def get_report(self, report_id, headers):
        return self._request("GET", f"/scouting/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/scouting/reports", headers=headers, params=params)

    def submit_report(self, report_id, headers):
        return self._request(
            "POST", f"/scouting/reports/{report_id}/submit", {}, headers
        )

    def return_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"/scouting/reports/{report_id}/return", payload, headers
        )

    def lock_report(self, report_id, headers):
        return self._request("POST", f"/scouting/reports/{report_id}/lock", {}, headers)

    # --- video tags ---
    def create_video_tag(self, report_id, payload, headers):
        return self._request(
            "POST", f"/scouting/reports/{report_id}/video-tags", payload, headers
        )

    def list_video_tags(self, report_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/scouting/reports/{report_id}/video-tags",
            headers=headers,
            params=params,
        )

    # --- confidential flags ---
    def create_flag(self, prospect_id, payload, headers):
        return self._request(
            "POST", f"/scouting/prospects/{prospect_id}/flags", payload, headers
        )

    def list_flags(self, prospect_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/scouting/prospects/{prospect_id}/flags",
            headers=headers,
            params=params,
        )

    def acknowledge_flag(self, flag_id, headers):
        return self._request(
            "POST", f"/scouting/flags/{flag_id}/acknowledge", {}, headers
        )

    def resolve_flag(self, flag_id, payload, headers):
        return self._request(
            "POST", f"/scouting/flags/{flag_id}/resolve", payload, headers
        )

    def escalate_flag(self, flag_id, headers):
        return self._request("POST", f"/scouting/flags/{flag_id}/escalate", {}, headers)

    # --- draft boards ---
    def create_draft_board(self, payload, headers):
        return self._request("POST", "/scouting/draft-boards", payload, headers)

    def get_draft_board(self, board_id, headers):
        return self._request(
            "GET", f"/scouting/draft-boards/{board_id}", headers=headers
        )

    def list_board_entries(self, board_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/scouting/draft-boards/{board_id}/entries",
            headers=headers,
            params=params,
        )

    def add_board_entry(self, board_id, payload, headers):
        return self._request(
            "POST", f"/scouting/draft-boards/{board_id}/entries", payload, headers
        )

    def reorder_board_entries(self, board_id, payload, headers):
        return self._request(
            "POST",
            f"/scouting/draft-boards/{board_id}/entries/reorder",
            payload,
            headers,
        )

    def freeze_board(self, board_id, headers):
        return self._request(
            "POST", f"/scouting/draft-boards/{board_id}/freeze", {}, headers
        )

    def unfreeze_board(self, board_id, headers):
        return self._request(
            "POST", f"/scouting/draft-boards/{board_id}/unfreeze", {}, headers
        )

    def finalize_board(self, board_id, headers):
        return self._request(
            "POST", f"/scouting/draft-boards/{board_id}/finalize", {}, headers
        )

    # --- roster needs ---
    def create_roster_need(self, payload, headers):
        return self._request("POST", "/scouting/roster-needs", payload, headers)

    def list_roster_needs(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", "/scouting/roster-needs", headers=headers, params=params
        )

    def get_roster_need(self, need_id, headers):
        return self._request(
            "GET", f"/scouting/roster-needs/{need_id}", headers=headers
        )

    def close_roster_need(self, need_id, headers):
        return self._request(
            "POST", f"/scouting/roster-needs/{need_id}/close", {}, headers
        )

    # --- free agent targets ---
    def create_free_agent_target(self, payload, headers):
        return self._request("POST", "/scouting/free-agent-targets", payload, headers)

    def list_free_agent_targets(self, headers, params: Optional[dict] = None):
        return self._request(
            "GET", "/scouting/free-agent-targets", headers=headers, params=params
        )

    def get_free_agent_target(self, target_id, headers):
        return self._request(
            "GET", f"/scouting/free-agent-targets/{target_id}", headers=headers
        )

    def advance_target(self, target_id, payload, headers):
        return self._request(
            "POST",
            f"/scouting/free-agent-targets/{target_id}/advance",
            payload,
            headers,
        )

    def sign_target(self, target_id, payload, headers):
        return self._request(
            "POST", f"/scouting/free-agent-targets/{target_id}/sign", payload, headers
        )

    def release_target(self, target_id, headers):
        return self._request(
            "POST", f"/scouting/free-agent-targets/{target_id}/release", {}, headers
        )

    def pass_target(self, target_id, headers):
        return self._request(
            "POST", f"/scouting/free-agent-targets/{target_id}/pass", {}, headers
        )

    # --- budgets ---
    def create_budget(self, payload, headers):
        return self._request("POST", "/scouting/budgets", payload, headers)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/scouting/budgets/{budget_id}", headers=headers)

    def adjust_budget(self, budget_id, payload, headers):
        return self._request(
            "POST", f"/scouting/budgets/{budget_id}/adjustments", payload, headers
        )

    # --- interviews ---
    def schedule_interview(self, prospect_id, payload, headers):
        return self._request(
            "POST", f"/scouting/prospects/{prospect_id}/interviews", payload, headers
        )

    def cancel_interview(self, session_id, headers):
        return self._request(
            "POST", f"/scouting/interviews/{session_id}/cancel", {}, headers
        )

    def list_interviews(self, prospect_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/scouting/prospects/{prospect_id}/interviews",
            headers=headers,
            params=params,
        )

    # --- facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/scouting/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request(
            "GET", f"/scouting/facilities/{facility_id}", headers=headers
        )

    def create_booking(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/scouting/facilities/{facility_id}/bookings", payload, headers
        )

    def list_bookings(self, facility_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/scouting/facilities/{facility_id}/bookings",
            headers=headers,
            params=params,
        )

    # --- outcomes ---
    def create_outcome(self, prospect_id, payload, headers):
        return self._request(
            "POST", f"/scouting/prospects/{prospect_id}/outcomes", payload, headers
        )

    def list_outcomes(self, prospect_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET",
            f"/scouting/prospects/{prospect_id}/outcomes",
            headers=headers,
            params=params,
        )


api_client = ApiClient()
