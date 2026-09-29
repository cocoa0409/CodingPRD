"""HTTP client exposing one method per endpoint of the junior golf tour API."""

from prd_bench_local_runner.testing import GenericApiClient


class GolfTourApiClient(GenericApiClient):
    """One method per documented endpoint; every method returns the raw response."""

    # ------------------------------------------------------------- clock
    def set_clock(self, current_utc, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"current_utc": current_utc}, headers
        )

    def set_clock_raw(self, payload, headers=None):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ seasons
    def create_season(self, payload, headers=None):
        return self._request("POST", "/seasons", payload, headers)

    def get_season(self, season_id, headers=None):
        return self._request("GET", f"/seasons/{season_id}", None, headers)

    def run_ranking(self, season_id, payload=None, headers=None):
        return self._request(
            "POST", f"/seasons/{season_id}/ranking-runs", payload or {}, headers
        )

    # ------------------------------------------------------------ members
    def register_member(self, payload, headers=None):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, params=None, headers=None):
        return self._request("GET", "/members", params, headers)

    def get_member(self, member_id, headers=None):
        return self._request("GET", f"/members/{member_id}", None, headers)

    def verify_eligibility(self, member_id, payload, headers=None):
        return self._request(
            "POST", f"/members/{member_id}/verify-eligibility", payload, headers
        )

    def revise_handicap(self, member_id, payload, headers=None):
        return self._request(
            "POST", f"/members/{member_id}/handicap-revisions", payload, headers
        )

    def get_ranking(self, member_id, headers=None):
        return self._request("GET", f"/members/{member_id}/ranking", None, headers)

    def get_published_results(self, member_id, headers=None):
        return self._request(
            "GET", f"/members/{member_id}/published-results", None, headers
        )

    # -------------------------------------------------------- tournaments
    def create_tournament(self, payload, headers=None):
        return self._request("POST", "/tournaments", payload, headers)

    def list_tournaments(self, params=None, headers=None):
        return self._request("GET", "/tournaments", params, headers)

    def get_tournament(self, tournament_id, headers=None):
        return self._request("GET", f"/tournaments/{tournament_id}", None, headers)

    def open_entries(self, tournament_id, headers=None):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/open-entries", {}, headers
        )

    def close_entries(self, tournament_id, headers=None):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/close-entries", {}, headers
        )

    def set_field(self, tournament_id, headers=None):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/set-field", {}, headers
        )

    def start_tournament(self, tournament_id, headers=None):
        return self._request("POST", f"/tournaments/{tournament_id}/start", {}, headers)

    def cancel_tournament(self, tournament_id, payload=None, headers=None):
        return self._request(
            "POST", f"/tournaments/{tournament_id}/cancel", payload or {}, headers
        )

    # --------------------------------------------------- exemption grants
    def create_exemption_grant(self, payload, headers=None):
        return self._request("POST", "/exemption-grants", payload, headers)

    def list_exemption_grants(self, params=None, headers=None):
        return self._request("GET", "/exemption-grants", params, headers)

    def get_exemption_grant(self, grant_id, headers=None):
        return self._request("GET", f"/exemption-grants/{grant_id}", None, headers)

    # ------------------------------------------------------------ entries
    def submit_entry(self, payload, headers=None):
        return self._request("POST", "/entries", payload, headers)

    def list_entries(self, params=None, headers=None):
        return self._request("GET", "/entries", params, headers)

    def get_entry(self, entry_id, headers=None):
        return self._request("GET", f"/entries/{entry_id}", None, headers)

    def withdraw_entry(self, entry_id, payload=None, headers=None):
        return self._request(
            "POST", f"/entries/{entry_id}/withdraw", payload or {}, headers
        )

    def pay_entry(self, entry_id, payload, headers=None):
        return self._request("POST", f"/entries/{entry_id}/pay", payload, headers)

    # --------------------------------------------------- aid applications
    def submit_aid_application(self, payload, headers=None):
        return self._request("POST", "/aid-applications", payload, headers)

    def list_aid_applications(self, params=None, headers=None):
        return self._request("GET", "/aid-applications", params, headers)

    def get_aid_application(self, application_id, headers=None):
        return self._request("GET", f"/aid-applications/{application_id}", None, headers)

    def decide_aid_application(self, application_id, payload, headers=None):
        return self._request(
            "POST", f"/aid-applications/{application_id}/decide", payload, headers
        )

    # ------------------------------------------------------------- rounds
    def create_round(self, payload, headers=None):
        return self._request("POST", "/rounds", payload, headers)

    def list_rounds(self, params=None, headers=None):
        return self._request("GET", "/rounds", params, headers)

    def get_round(self, round_id, headers=None):
        return self._request("GET", f"/rounds/{round_id}", None, headers)

    def record_pace_observation(self, round_id, payload, headers=None):
        return self._request(
            "POST", f"/rounds/{round_id}/pace-observations", payload, headers
        )

    def submit_score(self, round_id, payload, headers=None):
        return self._request("POST", f"/rounds/{round_id}/submit-score", payload, headers)

    def peer_verify(self, round_id, payload, headers=None):
        return self._request("POST", f"/rounds/{round_id}/peer-verify", payload, headers)

    def certify_round(self, round_id, headers=None):
        return self._request("POST", f"/rounds/{round_id}/certify", {}, headers)

    # -------------------------------------------------------- rules cases
    def report_rules_case(self, payload, headers=None):
        return self._request("POST", "/rules-cases", payload, headers)

    def list_rules_cases(self, params=None, headers=None):
        return self._request("GET", "/rules-cases", params, headers)

    def get_rules_case(self, case_id, headers=None):
        return self._request("GET", f"/rules-cases/{case_id}", None, headers)

    def adjudicate_rules_case(self, case_id, payload, headers=None):
        return self._request(
            "POST", f"/rules-cases/{case_id}/adjudicate", payload, headers
        )

    def appeal_rules_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/rules-cases/{case_id}/appeal", payload, headers)

    # ------------------------------------------------------ conduct cases
    def file_conduct_case(self, payload, headers=None):
        return self._request("POST", "/conduct-cases", payload, headers)

    def list_conduct_cases(self, params=None, headers=None):
        return self._request("GET", "/conduct-cases", params, headers)

    def get_conduct_case(self, case_id, headers=None):
        return self._request("GET", f"/conduct-cases/{case_id}", None, headers)

    def decide_conduct_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/conduct-cases/{case_id}/decide", payload, headers)

    def appeal_conduct_case(self, case_id, payload, headers=None):
        return self._request("POST", f"/conduct-cases/{case_id}/appeal", payload, headers)

    # ------------------------------------------------ coach access grants
    def request_coach_access(self, payload, headers=None):
        return self._request("POST", "/coach-access-grants", payload, headers)

    def list_coach_access_grants(self, params=None, headers=None):
        return self._request("GET", "/coach-access-grants", params, headers)

    def get_coach_access_grant(self, grant_id, headers=None):
        return self._request("GET", f"/coach-access-grants/{grant_id}", None, headers)

    def decide_coach_access(self, grant_id, payload, headers=None):
        return self._request(
            "POST", f"/coach-access-grants/{grant_id}/decide", payload, headers
        )

    def revoke_coach_access(self, grant_id, payload=None, headers=None):
        return self._request(
            "POST", f"/coach-access-grants/{grant_id}/revoke", payload or {}, headers
        )
