"""API client for the Lateral Partner Hiring API.

One method per endpoint. Every path is mounted under the ``/lateral-hiring``
prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/lateral-hiring"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Practice groups
    # ------------------------------------------------------------------

    def create_practice_group(self, payload, headers):
        return self._request("POST", f"{PREFIX}/practice-groups", payload, headers)

    def get_practice_group(self, practice_group_id, headers):
        return self._request(
            "GET", f"{PREFIX}/practice-groups/{practice_group_id}", headers=headers
        )

    def list_practice_groups(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/practice-groups", headers=headers, params=params
        )

    def freeze_practice_group(self, practice_group_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/practice-groups/{practice_group_id}/freeze",
            payload,
            headers,
        )

    def unfreeze_practice_group(self, practice_group_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/practice-groups/{practice_group_id}/unfreeze",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Search firms
    # ------------------------------------------------------------------

    def create_search_firm(self, payload, headers):
        return self._request("POST", f"{PREFIX}/search-firms", payload, headers)

    def get_search_firm(self, search_firm_id, headers):
        return self._request(
            "GET", f"{PREFIX}/search-firms/{search_firm_id}", headers=headers
        )

    def list_search_firms(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/search-firms", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Search firm engagements
    # ------------------------------------------------------------------

    def create_search_firm_engagement(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/search-firm-engagements", payload, headers
        )

    def get_search_firm_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/search-firm-engagements/{engagement_id}", headers=headers
        )

    def list_search_firm_engagements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/search-firm-engagements", headers=headers, params=params
        )

    def terminate_search_firm_engagement(self, engagement_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/search-firm-engagements/{engagement_id}/terminate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Candidates
    # ------------------------------------------------------------------

    def create_candidate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/candidates/{candidate_id}", headers=headers
        )

    def list_candidates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/candidates", headers=headers, params=params
        )

    def approach_candidate(self, candidate_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/candidates/{candidate_id}/approach", payload, headers
        )

    def withdraw_candidate(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/candidates/{candidate_id}/withdraw", payload, headers
        )

    def create_questionnaire(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/candidates/{candidate_id}/questionnaires",
            payload,
            headers,
        )

    def create_collection_record(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/candidates/{candidate_id}/collection-records",
            payload,
            headers,
        )

    def create_offer(self, candidate_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/candidates/{candidate_id}/offers", payload, headers
        )

    def create_integration_plan(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/candidates/{candidate_id}/integration-plans",
            payload,
            headers,
        )

    def create_performance_review(self, candidate_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/candidates/{candidate_id}/performance-reviews",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Lateral partner questionnaires
    # ------------------------------------------------------------------

    def get_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "GET", f"{PREFIX}/questionnaires/{questionnaire_id}", headers=headers
        )

    def list_questionnaires(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/questionnaires", headers=headers, params=params
        )

    def submit_questionnaire(self, questionnaire_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/questionnaires/{questionnaire_id}/submit",
            payload,
            headers,
        )

    def start_review_questionnaire(self, questionnaire_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/questionnaires/{questionnaire_id}/start-review",
            payload,
            headers,
        )

    def request_revision_questionnaire(self, questionnaire_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/questionnaires/{questionnaire_id}/request-revision",
            payload,
            headers,
        )

    def accept_questionnaire(self, questionnaire_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/questionnaires/{questionnaire_id}/accept",
            payload,
            headers,
        )

    def create_client_book_entry(self, questionnaire_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/questionnaires/{questionnaire_id}/client-book-entries",
            payload,
            headers,
        )

    def create_portability_assessment(self, questionnaire_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/questionnaires/{questionnaire_id}/portability-assessments",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Client book entries
    # ------------------------------------------------------------------

    def get_client_book_entry(self, entry_id, headers):
        return self._request(
            "GET", f"{PREFIX}/client-book-entries/{entry_id}", headers=headers
        )

    def list_client_book_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/client-book-entries", headers=headers, params=params
        )

    def delete_client_book_entry(self, entry_id, headers):
        return self._request(
            "DELETE", f"{PREFIX}/client-book-entries/{entry_id}", headers=headers
        )

    def create_conflict_check(self, entry_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/client-book-entries/{entry_id}/conflict-checks",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Collection records
    # ------------------------------------------------------------------

    def get_collection_record(self, record_id, headers):
        return self._request(
            "GET", f"{PREFIX}/collection-records/{record_id}", headers=headers
        )

    def list_collection_records(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/collection-records", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Portability assessments
    # ------------------------------------------------------------------

    def get_portability_assessment(self, assessment_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/portability-assessments/{assessment_id}",
            headers=headers,
        )

    def list_portability_assessments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/portability-assessments", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Conflict checks
    # ------------------------------------------------------------------

    def get_conflict_check(self, conflict_check_id, headers):
        return self._request(
            "GET", f"{PREFIX}/conflict-checks/{conflict_check_id}", headers=headers
        )

    def list_conflict_checks(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/conflict-checks", headers=headers, params=params
        )

    def clear_conflict_check(self, conflict_check_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/conflict-checks/{conflict_check_id}/clear",
            payload,
            headers,
        )

    def create_conflict_waiver(self, conflict_check_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/conflict-checks/{conflict_check_id}/waivers",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Conflict waivers
    # ------------------------------------------------------------------

    def get_conflict_waiver(self, waiver_id, headers):
        return self._request(
            "GET", f"{PREFIX}/conflict-waivers/{waiver_id}", headers=headers
        )

    def list_conflict_waivers(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/conflict-waivers", headers=headers, params=params
        )

    def grant_conflict_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/conflict-waivers/{waiver_id}/grant", payload, headers
        )

    def refuse_conflict_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/conflict-waivers/{waiver_id}/refuse", payload, headers
        )

    # ------------------------------------------------------------------
    # Matter declinations
    # ------------------------------------------------------------------

    def get_matter_declination(self, declination_id, headers):
        return self._request(
            "GET", f"{PREFIX}/matter-declinations/{declination_id}", headers=headers
        )

    def list_matter_declinations(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/matter-declinations", headers=headers, params=params
        )

    def rescind_matter_declination(self, declination_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/matter-declinations/{declination_id}/rescind",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Compensation offers
    # ------------------------------------------------------------------

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"{PREFIX}/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/offers", headers=headers, params=params)

    def redraft_offer(self, offer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/offers/{offer_id}", payload, headers)

    def submit_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/submit", payload, headers
        )

    def finalize_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/finalize", payload, headers
        )

    def counter_offer(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/counter", payload, headers
        )

    def accept_offer(self, offer_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/accept", payload, headers
        )

    def cast_vote(self, offer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/offers/{offer_id}/votes", payload, headers
        )

    # ------------------------------------------------------------------
    # Committee votes
    # ------------------------------------------------------------------

    def get_vote(self, vote_id, headers):
        return self._request("GET", f"{PREFIX}/votes/{vote_id}", headers=headers)

    def list_votes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/votes", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Integration plans
    # ------------------------------------------------------------------

    def get_integration_plan(self, plan_id, headers):
        return self._request(
            "GET", f"{PREFIX}/integration-plans/{plan_id}", headers=headers
        )

    def list_integration_plans(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/integration-plans", headers=headers, params=params
        )

    def abandon_integration_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/integration-plans/{plan_id}/abandon", payload, headers
        )

    def activate_integration_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/integration-plans/{plan_id}/activate", payload, headers
        )

    def create_introduction(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/integration-plans/{plan_id}/introductions",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Cross-selling introductions
    # ------------------------------------------------------------------

    def get_introduction(self, introduction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/introductions/{introduction_id}", headers=headers
        )

    def list_introductions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/introductions", headers=headers, params=params
        )

    def complete_introduction(self, introduction_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/introductions/{introduction_id}/complete",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Performance reviews
    # ------------------------------------------------------------------

    def get_performance_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/performance-reviews/{review_id}", headers=headers
        )

    def list_performance_reviews(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/performance-reviews", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def set_clock_raw(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
