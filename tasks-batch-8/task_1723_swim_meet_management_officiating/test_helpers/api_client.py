"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, open to Any authenticated role)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Meet lifecycle
    # ------------------------------------------------------------------
    def create_meet(self, payload, headers):
        return self._request("POST", "/meets", payload, headers)

    def get_meet(self, meet_id, headers):
        return self._request("GET", f"/meets/{meet_id}", headers=headers)

    def open_entries(self, meet_id, headers):
        return self._request("POST", f"/meets/{meet_id}/open-entries", {}, headers)

    def close_entries(self, meet_id, headers):
        return self._request("POST", f"/meets/{meet_id}/close-entries", {}, headers)

    def seed_meet(self, meet_id, expected_meet_version, headers):
        return self._request("POST", f"/meets/{meet_id}/seed",
                             {"expected_meet_version": expected_meet_version}, headers)

    def reopen_entries(self, meet_id, new_entry_deadline_utc, headers):
        return self._request("POST", f"/meets/{meet_id}/reopen-entries",
                             {"new_entry_deadline_utc": new_entry_deadline_utc}, headers)

    def complete_meet(self, meet_id, headers):
        return self._request("POST", f"/meets/{meet_id}/complete", {}, headers)

    def finalize_meet(self, meet_id, headers):
        return self._request("POST", f"/meets/{meet_id}/finalize", {}, headers)

    # ------------------------------------------------------------------
    # Teams / Swimmers
    # ------------------------------------------------------------------
    def create_team(self, payload, headers):
        return self._request("POST", "/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/teams", headers=headers, params=params)

    def withdraw_team(self, team_id, headers):
        return self._request("POST", f"/teams/{team_id}/withdraw", {}, headers)

    def create_swimmer(self, payload, headers):
        return self._request("POST", "/swimmers", payload, headers)

    def get_swimmer(self, swimmer_id, headers):
        return self._request("GET", f"/swimmers/{swimmer_id}", headers=headers)

    def list_swimmers(self, headers, params=None):
        return self._request("GET", "/swimmers", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/start", {}, headers)

    def complete_event(self, event_id, expected_event_version, headers):
        return self._request("POST", f"/events/{event_id}/complete",
                             {"expected_event_version": expected_event_version}, headers)

    def reopen_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/reopen", {}, headers)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/publish", {}, headers)

    def get_heat_sheet(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/heat-sheet", headers=headers)

    def list_event_results(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/results",
                             headers=headers, params=params)

    def list_event_official_assignments(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/official-assignments",
                             headers=headers, params=params)

    def list_event_records(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/records",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Entries
    # ------------------------------------------------------------------
    def create_entry(self, payload, headers):
        return self._request("POST", "/entries", payload, headers)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/entries/{entry_id}", headers=headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/entries", headers=headers, params=params)

    def verify_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/verify", {}, headers)

    def scratch_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/scratch", {}, headers)

    def unscratch_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/unscratch", {}, headers)

    def mark_no_show(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/mark-no-show", {}, headers)

    def get_entry_result(self, entry_id, headers):
        return self._request("GET", f"/entries/{entry_id}/result", headers=headers)

    # ------------------------------------------------------------------
    # Relay teams / legs
    # ------------------------------------------------------------------
    def create_relay_team(self, payload, headers):
        return self._request("POST", "/relay-teams", payload, headers)

    def get_relay_team(self, relay_team_id, headers):
        return self._request("GET", f"/relay-teams/{relay_team_id}", headers=headers)

    def list_relay_teams(self, headers, params=None):
        return self._request("GET", "/relay-teams", headers=headers, params=params)

    def add_relay_leg(self, relay_team_id, payload, headers):
        return self._request("POST", f"/relay-teams/{relay_team_id}/legs",
                             payload, headers)

    def list_relay_team_legs(self, relay_team_id, headers, params=None):
        return self._request("GET", f"/relay-teams/{relay_team_id}/legs",
                             headers=headers, params=params)

    def get_relay_leg(self, relay_leg_id, headers):
        return self._request("GET", f"/relay-legs/{relay_leg_id}", headers=headers)

    def list_relay_legs(self, headers, params=None):
        return self._request("GET", "/relay-legs", headers=headers, params=params)

    def lock_relay_team(self, relay_team_id, headers):
        return self._request("POST", f"/relay-teams/{relay_team_id}/lock", {}, headers)

    def scratch_relay_team(self, relay_team_id, headers):
        return self._request("POST", f"/relay-teams/{relay_team_id}/scratch", {}, headers)

    # ------------------------------------------------------------------
    # Lane assignments / timing
    # ------------------------------------------------------------------
    def get_lane_assignment(self, lane_assignment_id, headers):
        return self._request("GET", f"/lane-assignments/{lane_assignment_id}",
                             headers=headers)

    def list_lane_assignments(self, headers, params=None):
        return self._request("GET", "/lane-assignments", headers=headers, params=params)

    def submit_readings(self, lane_assignment_id, payload, headers):
        return self._request("POST", f"/lane-assignments/{lane_assignment_id}/readings",
                             payload, headers)

    def resolve_lane(self, lane_assignment_id, variant, headers, pad_status=None):
        payload = {"variant": variant}
        if pad_status is not None:
            payload["pad_status"] = pad_status
        return self._request("POST", f"/lane-assignments/{lane_assignment_id}/resolve",
                             payload, headers)

    def reopen_timing(self, lane_assignment_id, headers):
        return self._request("POST",
                             f"/lane-assignments/{lane_assignment_id}/reopen-timing",
                             {}, headers)

    def list_lane_disqualifications(self, lane_assignment_id, headers, params=None):
        return self._request("GET",
                             f"/lane-assignments/{lane_assignment_id}/disqualifications",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------
    def list_team_results(self, team_id, headers, params=None):
        return self._request("GET", f"/teams/{team_id}/results",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Officials / assignments
    # ------------------------------------------------------------------
    def create_official(self, payload, headers):
        return self._request("POST", "/officials", payload, headers)

    def get_official(self, official_id, headers):
        return self._request("GET", f"/officials/{official_id}", headers=headers)

    def list_officials(self, headers, params=None):
        return self._request("GET", "/officials", headers=headers, params=params)

    def create_official_assignment(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/official-assignments",
                             payload, headers)

    def get_official_assignment(self, assignment_id, headers):
        return self._request("GET", f"/official-assignments/{assignment_id}",
                             headers=headers)

    def list_official_assignments(self, headers, params=None):
        return self._request("GET", "/official-assignments",
                             headers=headers, params=params)

    def confirm_official_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/official-assignments/{assignment_id}/confirm",
                             {}, headers)

    def release_official_assignment(self, assignment_id, headers):
        return self._request("POST",
                             f"/official-assignments/{assignment_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Disqualifications
    # ------------------------------------------------------------------
    def record_disqualification(self, lane_assignment_id, payload, headers):
        return self._request("POST",
                             f"/lane-assignments/{lane_assignment_id}/disqualifications",
                             payload, headers)

    def get_disqualification(self, disqualification_id, headers):
        return self._request("GET", f"/disqualifications/{disqualification_id}",
                             headers=headers)

    def list_disqualifications(self, headers, params=None):
        return self._request("GET", "/disqualifications", headers=headers, params=params)

    def notify_coach(self, disqualification_id, headers):
        return self._request("POST",
                             f"/disqualifications/{disqualification_id}/notify-coach",
                             {}, headers)

    def protest_disqualification(self, disqualification_id, headers):
        return self._request("POST",
                             f"/disqualifications/{disqualification_id}/protest",
                             {}, headers)

    def confirm_disqualification(self, disqualification_id, headers):
        return self._request("POST",
                             f"/disqualifications/{disqualification_id}/confirm",
                             {}, headers)

    def uphold_disqualification(self, disqualification_id, headers):
        return self._request("POST",
                             f"/disqualifications/{disqualification_id}/uphold",
                             {}, headers)

    def overturn_disqualification(self, disqualification_id, headers):
        return self._request("POST",
                             f"/disqualifications/{disqualification_id}/overturn",
                             {}, headers)

    # ------------------------------------------------------------------
    # Meet records
    # ------------------------------------------------------------------
    def create_standing_record(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/records", payload, headers)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/records/{record_id}", headers=headers)

    def list_records(self, headers, params=None):
        return self._request("GET", "/records", headers=headers, params=params)

    def verify_record(self, record_id, headers):
        return self._request("POST", f"/records/{record_id}/verify", {}, headers)

    def ratify_record(self, record_id, headers):
        return self._request("POST", f"/records/{record_id}/ratify", {}, headers)

    def reject_record(self, record_id, headers):
        return self._request("POST", f"/records/{record_id}/reject", {}, headers)


api_client = ApiClient()
