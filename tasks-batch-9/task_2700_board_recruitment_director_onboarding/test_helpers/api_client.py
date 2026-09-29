"""API client: one method per endpoint published in the PRD (all mounted under /governance)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/governance"


class ApiClient(GenericApiClient):
    # ---------------- Governance policies ----------------
    def adopt_policy(self, payload, headers):
        return self._request("POST", f"{PREFIX}/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"{PREFIX}/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/policies", headers=headers, params=params)

    # ---------------- Skill categories & gap analysis ----------------
    def create_skill_category(self, payload, headers):
        return self._request("POST", f"{PREFIX}/skill-categories", payload, headers)

    def list_skill_categories(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/skill-categories", headers=headers, params=params
        )

    def get_gap_analysis(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/skills-matrix/gap-analysis", headers=headers, params=params
        )

    # ---------------- Search firms ----------------
    def create_search_firm(self, payload, headers):
        return self._request("POST", f"{PREFIX}/search-firms", payload, headers)

    def get_search_firm(self, firm_id, headers):
        return self._request("GET", f"{PREFIX}/search-firms/{firm_id}", headers=headers)

    # ---------------- External companies ----------------
    def create_external_company(self, payload, headers):
        return self._request("POST", f"{PREFIX}/external-companies", payload, headers)

    # ---------------- Directors ----------------
    def create_director(self, payload, headers):
        return self._request("POST", f"{PREFIX}/directors", payload, headers)

    def get_director(self, director_id, headers):
        return self._request("GET", f"{PREFIX}/directors/{director_id}", headers=headers)

    def list_directors(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/directors", headers=headers, params=params)

    def seat_director(self, director_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/directors/{director_id}/seat", payload or {}, headers
        )

    def record_departure_notice(self, director_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/directors/{director_id}/departure-notice", payload, headers
        )

    # ---------------- Skill ratings ----------------
    def create_skill_rating(self, director_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/directors/{director_id}/skill-ratings", payload, headers
        )

    def get_skill_rating(self, rating_id, headers):
        return self._request(
            "GET", f"{PREFIX}/skill-ratings/{rating_id}", headers=headers
        )

    def list_skill_ratings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/skill-ratings", headers=headers, params=params
        )

    def validate_skill_rating(self, rating_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/skill-ratings/{rating_id}/validate", payload, headers
        )

    # ---------------- Candidates ----------------
    def create_candidate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/candidates/{candidate_id}", headers=headers
        )

    def list_candidates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/candidates", headers=headers, params=params)

    def record_reference_check(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/candidates/{candidate_id}/reference-check", payload, headers
        )

    def reopen_interviews(self, candidate_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/candidates/{candidate_id}/reopen-interviews",
            payload or {},
            headers,
        )

    def run_conflict_clearance(self, candidate_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/candidates/{candidate_id}/conflict-clearance",
            payload or {},
            headers,
        )

    def reopen_screening(self, candidate_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/candidates/{candidate_id}/reopen-screening",
            payload or {},
            headers,
        )

    def withdraw_candidate(self, candidate_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/candidates/{candidate_id}/withdraw", payload or {}, headers
        )

    # ---------------- Independence screens ----------------
    def create_screen(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/candidates/{candidate_id}/screens", payload, headers
        )

    def list_candidate_screens(self, candidate_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/candidates/{candidate_id}/screens",
            headers=headers,
            params=params,
        )

    def get_screen(self, screen_id, headers):
        return self._request("GET", f"{PREFIX}/screens/{screen_id}", headers=headers)

    def list_screens(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/screens", headers=headers, params=params)

    def submit_screen(self, screen_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/screens/{screen_id}/submit", payload or {}, headers
        )

    def determine_screen(self, screen_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/screens/{screen_id}/determine", payload or {}, headers
        )

    # ---------------- External directorships ----------------
    def create_external_directorship(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/external-directorships", payload, headers
        )

    def get_external_directorship(self, directorship_id, headers):
        return self._request(
            "GET", f"{PREFIX}/external-directorships/{directorship_id}", headers=headers
        )

    def list_external_directorships(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/external-directorships", headers=headers, params=params
        )

    def end_external_directorship(self, directorship_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/external-directorships/{directorship_id}/end",
            payload,
            headers,
        )

    # ---------------- Interviews ----------------
    def schedule_interview(self, payload, headers):
        return self._request("POST", f"{PREFIX}/interviews", payload, headers)

    def get_interview(self, interview_id, headers):
        return self._request(
            "GET", f"{PREFIX}/interviews/{interview_id}", headers=headers
        )

    def list_interviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/interviews", headers=headers, params=params)

    def complete_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/interviews/{interview_id}/complete", payload, headers
        )

    def cancel_interview(self, interview_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/interviews/{interview_id}/cancel", payload, headers
        )

    # ---------------- Committees & assignments ----------------
    def create_committee(self, payload, headers):
        return self._request("POST", f"{PREFIX}/committees", payload, headers)

    def get_committee(self, committee_id, headers):
        return self._request(
            "GET", f"{PREFIX}/committees/{committee_id}", headers=headers
        )

    def list_committees(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/committees", headers=headers, params=params)

    def create_assignment(self, committee_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/committees/{committee_id}/assignments", payload, headers
        )

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers
        )

    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignments", headers=headers, params=params
        )

    def activate_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/activate", payload or {}, headers
        )

    def revoke_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/revoke", payload or {}, headers
        )

    # ---------------- Slates, nominees, ballots ----------------
    def create_slate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/slates", payload, headers)

    def get_slate(self, slate_id, headers):
        return self._request("GET", f"{PREFIX}/slates/{slate_id}", headers=headers)

    def list_slates(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/slates", headers=headers, params=params)

    def add_slate_nominee(self, slate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/slates/{slate_id}/nominees", payload, headers
        )

    def get_slate_nominee(self, nominee_id, headers):
        return self._request(
            "GET", f"{PREFIX}/slate-nominees/{nominee_id}", headers=headers
        )

    def list_slate_nominees(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/slate-nominees", headers=headers, params=params
        )

    def void_slate_nominee(self, nominee_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/slate-nominees/{nominee_id}/void", payload or {}, headers
        )

    def submit_slate_for_review(self, slate_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/slates/{slate_id}/submit-for-review", payload or {}, headers
        )

    def cast_vote(self, slate_id, payload, headers):
        return self._request("POST", f"{PREFIX}/slates/{slate_id}/votes", payload, headers)

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"{PREFIX}/votes/{vote_id}", headers=headers)

    def list_votes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/votes", headers=headers, params=params)

    def decide_slate(self, slate_id, payload, headers):
        return self._request("POST", f"{PREFIX}/slates/{slate_id}/decide", payload, headers)

    def file_slate(self, slate_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/slates/{slate_id}/file", payload or {}, headers
        )

    def record_election(self, slate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/slates/{slate_id}/record-election", payload, headers
        )

    # ---------------- Onboarding items ----------------
    def create_onboarding_item(self, director_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/directors/{director_id}/onboarding-items", payload, headers
        )

    def list_director_onboarding_items(self, director_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/directors/{director_id}/onboarding-items",
            headers=headers,
            params=params,
        )

    def get_onboarding_item(self, item_id, headers):
        return self._request(
            "GET", f"{PREFIX}/onboarding-items/{item_id}", headers=headers
        )

    def list_onboarding_items(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/onboarding-items", headers=headers, params=params
        )

    def complete_onboarding_item(self, item_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/onboarding-items/{item_id}/complete", payload or {}, headers
        )

    def waive_onboarding_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/onboarding-items/{item_id}/waive", payload, headers
        )

    # ---------------- Compensation awards ----------------
    def create_comp_award(self, director_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/directors/{director_id}/comp-awards", payload, headers
        )

    def list_director_comp_awards(self, director_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/directors/{director_id}/comp-awards",
            headers=headers,
            params=params,
        )

    def get_comp_award(self, award_id, headers):
        return self._request("GET", f"{PREFIX}/comp-awards/{award_id}", headers=headers)

    def list_comp_awards(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/comp-awards", headers=headers, params=params)

    def finalize_comp_award(self, award_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/comp-awards/{award_id}/finalize", payload or {}, headers
        )

    # ---------------- Logical clock ----------------
    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
