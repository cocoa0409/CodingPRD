"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving clock control ───
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Volunteer ───
    def create_volunteer(self, payload, headers):
        return self._request("POST", "/volunteers", payload, headers)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}", headers=headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers, params=params)

    def submit_screening(self, volunteer_id, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/submit-screening", {}, headers
        )

    def deactivate_volunteer(self, volunteer_id, headers):
        return self._request(
            "POST", f"/volunteers/{volunteer_id}/deactivate", {}, headers
        )

    def list_volunteer_background_checks(self, volunteer_id, headers):
        return self._request(
            "GET", f"/volunteers/{volunteer_id}/background-checks", headers=headers
        )

    # ─── BackgroundCheck ───
    def get_background_check(self, check_id, headers):
        return self._request("GET", f"/background-checks/{check_id}", headers=headers)

    def adjudicate_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"/background-checks/{check_id}/adjudicate", payload, headers
        )

    # ─── Guardian ───
    def create_guardian(self, payload, headers):
        return self._request("POST", "/guardians", payload, headers)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/guardians/{guardian_id}", headers=headers)

    def update_guardian(self, guardian_id, payload, headers):
        return self._request("PATCH", f"/guardians/{guardian_id}", payload, headers)

    def list_guardian_children(self, guardian_id, headers):
        return self._request(
            "GET", f"/guardians/{guardian_id}/children", headers=headers
        )

    # ─── Child ───
    def create_child(self, payload, headers):
        return self._request("POST", "/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}", headers=headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/children", headers=headers, params=params)

    def propose_match(self, child_id, payload, headers):
        return self._request(
            "POST", f"/children/{child_id}/propose-match", payload, headers
        )

    def list_child_proposals(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}/proposals", headers=headers)

    def list_child_match(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}/match", headers=headers)

    # ─── MatchProposal ───
    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/match-proposals/{proposal_id}", headers=headers)

    def list_proposals(self, headers, params=None):
        return self._request("GET", "/match-proposals", headers=headers, params=params)

    def accept_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/match-proposals/{proposal_id}/accept", payload, headers
        )

    def decline_proposal(self, proposal_id, payload, headers):
        return self._request(
            "POST", f"/match-proposals/{proposal_id}/decline", payload, headers
        )

    def list_proposal_match(self, proposal_id, headers):
        return self._request(
            "GET", f"/match-proposals/{proposal_id}/match", headers=headers
        )

    # ─── Match ───
    def get_match(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", "/matches", headers=headers, params=params)

    def schedule_meeting(self, match_id, payload, headers):
        return self._request("POST", f"/matches/{match_id}/meetings", payload, headers)

    def list_match_meetings(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}/meetings", headers=headers)

    def log_activity(self, match_id, payload, headers):
        return self._request(
            "POST", f"/matches/{match_id}/activities", payload, headers
        )

    def list_match_activities(self, match_id, headers, params=None):
        return self._request(
            "GET", f"/matches/{match_id}/activities", headers=headers, params=params
        )

    def open_exit_transition(self, match_id, payload, headers):
        return self._request(
            "POST", f"/matches/{match_id}/exit-transitions", payload, headers
        )

    def list_match_exit_transitions(self, match_id, headers):
        return self._request(
            "GET", f"/matches/{match_id}/exit-transitions", headers=headers
        )

    def list_match_supervision_contacts(self, match_id, headers):
        return self._request(
            "GET", f"/matches/{match_id}/supervision-contacts", headers=headers
        )

    def list_match_survey(self, match_id, headers):
        return self._request("GET", f"/matches/{match_id}/survey", headers=headers)

    # ─── MatchMeeting ───
    def get_meeting(self, meeting_id, headers):
        return self._request("GET", f"/match-meetings/{meeting_id}", headers=headers)

    def hold_meeting(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/match-meetings/{meeting_id}/hold", payload, headers
        )

    def no_show_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/match-meetings/{meeting_id}/no-show", {}, headers
        )

    def affirm_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/match-meetings/{meeting_id}/affirm", {}, headers
        )

    def rescind_meeting(self, meeting_id, headers):
        return self._request(
            "POST", f"/match-meetings/{meeting_id}/rescind", {}, headers
        )

    # ─── SupervisionContact ───
    def get_supervision_contact(self, contact_id, headers):
        return self._request(
            "GET", f"/supervision-contacts/{contact_id}", headers=headers
        )

    def complete_contact(self, contact_id, payload, headers):
        return self._request(
            "POST", f"/supervision-contacts/{contact_id}/complete", payload, headers
        )

    # ─── ExitTransition ───
    def get_exit_transition(self, exit_id, headers):
        return self._request("GET", f"/exit-transitions/{exit_id}", headers=headers)

    def list_exit_survey(self, exit_id, headers):
        return self._request(
            "GET", f"/exit-transitions/{exit_id}/survey", headers=headers
        )

    def finalize_exit(self, exit_id, headers):
        return self._request(
            "POST", f"/exit-transitions/{exit_id}/finalize", {}, headers
        )

    # ─── OutcomeSurvey ───
    def create_outcome_survey(self, payload, headers):
        return self._request("POST", "/outcome-surveys", payload, headers)

    def get_outcome_survey(self, survey_id, headers):
        return self._request("GET", f"/outcome-surveys/{survey_id}", headers=headers)


api_client = ApiClient()
