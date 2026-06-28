"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- MembershipPlan ----
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/box/membership-plans", payload, headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/box/membership-plans", headers=headers, params=params)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/box/membership-plans/{plan_id}", headers=headers)

    def archive_membership_plan(self, plan_id, headers):
        return self._request("POST", f"/box/membership-plans/{plan_id}/archive", headers=headers)

    # ---- Member ----
    def register_member(self, payload, headers):
        return self._request("POST", "/box/members/register", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/box/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/box/members", headers=headers, params=params)

    def clear_strikes(self, member_id, headers):
        return self._request("POST", f"/box/members/{member_id}/clear-strikes", headers=headers)

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/box/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/box/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/box/memberships", headers=headers, params=params)

    def confirm_payment(self, membership_id, headers):
        return self._request("POST", f"/box/memberships/{membership_id}/confirm-payment", headers=headers)

    def freeze_membership(self, membership_id, headers):
        return self._request("POST", f"/box/memberships/{membership_id}/freeze", headers=headers)

    def unfreeze_membership(self, membership_id, headers):
        return self._request("POST", f"/box/memberships/{membership_id}/unfreeze", headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/box/memberships/{membership_id}/cancel", headers=headers)

    # ---- Coach ----
    def create_coach(self, payload, headers):
        return self._request("POST", "/box/coaches", payload, headers)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/box/coaches/{coach_id}", headers=headers)

    def list_coaches(self, headers, params=None):
        return self._request("GET", "/box/coaches", headers=headers, params=params)

    # ---- ProgramTrack ----
    def create_program_track(self, payload, headers):
        return self._request("POST", "/box/program-tracks", payload, headers)

    def get_program_track(self, track_id, headers):
        return self._request("GET", f"/box/program-tracks/{track_id}", headers=headers)

    def list_program_tracks(self, headers, params=None):
        return self._request("GET", "/box/program-tracks", headers=headers, params=params)

    def get_leaderboard(self, track_id, headers, params=None):
        return self._request("GET", f"/box/program-tracks/{track_id}/leaderboard", headers=headers, params=params)

    # ---- ClassSession ----
    def create_session(self, payload, headers):
        return self._request("POST", "/box/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/box/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/box/sessions", headers=headers, params=params)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/box/sessions/{session_id}/cancel", headers=headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/box/sessions/{session_id}/complete", payload, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/box/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/box/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/box/reservations", headers=headers, params=params)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/box/reservations/{reservation_id}/cancel", headers=headers)

    # ---- BenchmarkResult ----
    def create_benchmark_result(self, payload, headers):
        return self._request("POST", "/box/benchmark-results", payload, headers)

    def get_benchmark_result(self, result_id, headers):
        return self._request("GET", f"/box/benchmark-results/{result_id}", headers=headers)

    def list_benchmark_results(self, headers, params=None):
        return self._request("GET", "/box/benchmark-results", headers=headers, params=params)

    def verify_benchmark_result(self, result_id, headers):
        return self._request("POST", f"/box/benchmark-results/{result_id}/verify", headers=headers)

    # ---- CompetitionTeam ----
    def create_team(self, payload, headers):
        return self._request("POST", "/box/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/box/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/box/teams", headers=headers, params=params)

    def lock_team(self, team_id, payload, headers):
        return self._request("POST", f"/box/teams/{team_id}/lock", payload, headers)

    def disband_team(self, team_id, payload, headers):
        return self._request("POST", f"/box/teams/{team_id}/disband", payload, headers)

    # ---- TeamMember ----
    def create_team_member(self, payload, headers):
        return self._request("POST", "/box/team-members", payload, headers)

    def get_team_member(self, team_member_id, headers):
        return self._request("GET", f"/box/team-members/{team_member_id}", headers=headers)

    def list_team_members(self, headers, params=None):
        return self._request("GET", "/box/team-members", headers=headers, params=params)

    def accept_team_member(self, team_member_id, headers):
        return self._request("POST", f"/box/team-members/{team_member_id}/accept", headers=headers)

    def decline_team_member(self, team_member_id, headers):
        return self._request("POST", f"/box/team-members/{team_member_id}/decline", headers=headers)

    # ---- Test-driving / batch endpoints ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/box/_clock/set_current_utc", payload, headers)

    def complete_foundations(self, payload, headers):
        return self._request("POST", "/box/_membership/complete-foundations", payload, headers)

    def run_cycle_close(self, headers):
        return self._request("POST", "/box/_billing/run-cycle-close", headers=headers)


api_client = ApiClient()
