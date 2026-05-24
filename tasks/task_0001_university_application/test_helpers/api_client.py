"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient, which provides the _request()
implementation and envelope handling.

Per PRD §2 all endpoint paths are mounted under the `/api` prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Applicants ---
    def register_applicant(self, payload, headers=None):
        return self._request("POST", "/api/applicants/register", payload, headers or {})

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/api/applicants/{applicant_id}", headers=headers)

    def patch_applicant(self, applicant_id, payload, headers):
        return self._request("PATCH", f"/api/applicants/{applicant_id}", payload, headers)

    # --- Recommenders ---
    def create_recommender(self, payload, headers):
        return self._request("POST", "/api/recommenders", payload, headers)

    def get_recommender(self, recommender_id, headers):
        return self._request("GET", f"/api/recommenders/{recommender_id}", headers=headers)

    def accept_recommender(self, recommender_id, headers=None):
        return self._request("POST", f"/api/recommenders/{recommender_id}/accept",
                             {}, headers or {})

    def decline_recommender(self, recommender_id, headers=None):
        return self._request("POST", f"/api/recommenders/{recommender_id}/decline",
                             {}, headers or {})

    # --- Schools ---
    def create_school(self, payload, headers):
        return self._request("POST", "/api/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/api/schools/{school_id}", headers=headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/api/schools", headers=headers, params=params)

    def get_school_yield_report(self, school_id, headers):
        return self._request("GET", f"/api/schools/{school_id}/yield-report",
                             headers=headers)

    # --- Applications ---
    def create_application(self, payload, headers):
        return self._request("POST", "/api/applications", payload, headers)

    def get_application(self, application_id, headers, params=None):
        return self._request("GET", f"/api/applications/{application_id}",
                             headers=headers, params=params)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/api/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/submit",
                             {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/withdraw",
                             {}, headers)

    def start_review_application(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/start-review",
                             {}, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/api/applications/{application_id}/decide",
                             payload, headers)

    def accept_offer(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/accept-offer",
                             {}, headers)

    def decline_offer(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/decline-offer",
                             {}, headers)

    def revoke_enrollment(self, application_id, headers):
        return self._request("POST", f"/api/applications/{application_id}/revoke-enrollment",
                             {}, headers)

    # --- Essays ---
    def create_essay(self, payload, headers):
        return self._request("POST", "/api/essay-submissions", payload, headers)

    def patch_essay(self, essay_id, payload, headers):
        return self._request("PATCH", f"/api/essay-submissions/{essay_id}",
                             payload, headers)

    # --- Recommendation Letters ---
    def create_letter(self, payload, headers):
        return self._request("POST", "/api/recommendation-letters", payload, headers)

    def start_letter(self, letter_id, headers):
        return self._request("POST", f"/api/recommendation-letters/{letter_id}/start",
                             {}, headers)

    def submit_letter(self, letter_id, payload, headers):
        return self._request("POST", f"/api/recommendation-letters/{letter_id}/submit",
                             payload, headers)

    def waive_letter(self, letter_id, headers):
        return self._request("POST", f"/api/recommendation-letters/{letter_id}/waive",
                             {}, headers)

    # --- Financial Aid ---
    def create_financial_aid_profile(self, payload, headers):
        return self._request("POST", "/api/financial-aid-profiles", payload, headers)

    def submit_financial_aid_profile(self, profile_id, headers):
        return self._request(
            "POST",
            f"/api/financial-aid-profiles/{profile_id}/submit",
            {},
            headers,
        )

    def get_financial_aid_profile(self, profile_id, headers):
        return self._request("GET", f"/api/financial-aid-profiles/{profile_id}",
                             headers=headers)

    def create_aid_offer(self, payload, headers):
        return self._request("POST", "/api/aid-offers", payload, headers)

    def patch_aid_offer(self, offer_id, payload, headers):
        return self._request("PATCH", f"/api/aid-offers/{offer_id}", payload, headers)

    def get_aid_offer(self, offer_id, headers):
        return self._request("GET", f"/api/aid-offers/{offer_id}", headers=headers)

    # --- Yield Management ---
    def run_yield(self, cycle_id, headers):
        return self._request("POST", f"/api/admission-cycles/{cycle_id}/run-yield",
                             {}, headers)

    def get_admission_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/admission-cycles/{cycle_id}",
                             headers=headers)

    # --- Test clock ---
    def advance_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/advance",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
