"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Applicants ──────────────────────────────────────────────────
    def create_applicant(self, payload, headers=None):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    def update_applicant(self, applicant_id, payload, headers):
        return self._request("PATCH", f"/applicants/{applicant_id}", payload, headers)

    def list_applicants(self, headers, params=None):
        return self._request("GET", "/applicants", headers=headers, params=params)

    # ── Schools ─────────────────────────────────────────────────────
    def create_school(self, payload, headers):
        return self._request("POST", "/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"/schools/{school_id}", headers=headers)

    def list_schools(self, headers, params=None):
        return self._request("GET", "/schools", headers=headers, params=params)

    # ── Applications ────────────────────────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/submit", {}, headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers)

    def begin_review_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/begin-review", {}, headers)

    def admit_application(self, application_id, expected_application_version, headers):
        return self._request(
            "POST", f"/applications/{application_id}/admit",
            {"expected_application_version": expected_application_version}, headers,
        )

    def waitlist_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/waitlist", {}, headers)

    def deny_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/deny", {}, headers)

    def enroll_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/enroll", {}, headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/decline", {}, headers)

    # ── Essays ──────────────────────────────────────────────────────
    def create_essay(self, payload, headers):
        return self._request("POST", "/essays", payload, headers)

    def update_essay(self, essay_id, payload, headers):
        return self._request("PATCH", f"/essays/{essay_id}", payload, headers)

    def get_essay(self, essay_id, headers):
        return self._request("GET", f"/essays/{essay_id}", headers=headers)

    def list_essays(self, headers, params=None):
        return self._request("GET", "/essays", headers=headers, params=params)

    # ── RecommendationRequests ─────────────────────────────────────
    def create_recommendation_request(self, payload, headers):
        return self._request("POST", "/recommendation-requests", payload, headers)

    def submit_recommendation_request(self, request_id, rating, headers):
        return self._request(
            "POST", f"/recommendation-requests/{request_id}/submit",
            {"rating": rating}, headers,
        )

    def waive_recommendation_request(self, request_id, headers):
        return self._request("POST", f"/recommendation-requests/{request_id}/waive", {}, headers)

    def get_recommendation_request(self, request_id, headers):
        return self._request("GET", f"/recommendation-requests/{request_id}", headers=headers)

    def list_recommendation_requests(self, headers, params=None):
        return self._request("GET", "/recommendation-requests", headers=headers, params=params)

    # ── FinancialAidProfile ────────────────────────────────────────
    def create_financial_aid_profile(self, payload, headers):
        return self._request("POST", "/financial-aid-profiles", payload, headers)

    def get_financial_aid_profile(self, profile_id, headers):
        return self._request("GET", f"/financial-aid-profiles/{profile_id}", headers=headers)

    def list_financial_aid_profiles(self, headers, params=None):
        return self._request("GET", "/financial-aid-profiles", headers=headers, params=params)

    def update_financial_aid_profile(self, profile_id, payload, headers):
        return self._request("PATCH", f"/financial-aid-profiles/{profile_id}", payload, headers)

    # ── AidPackage ─────────────────────────────────────────────────
    def create_aid_package(self, payload, headers):
        return self._request("POST", "/aid-packages", payload, headers)

    def finalize_aid_package(self, package_id, headers):
        return self._request("POST", f"/aid-packages/{package_id}/finalize", {}, headers)

    def get_aid_package(self, package_id, headers):
        return self._request("GET", f"/aid-packages/{package_id}", headers=headers)

    def list_aid_packages(self, headers, params=None):
        return self._request("GET", "/aid-packages", headers=headers, params=params)

    # ── Waitlist ────────────────────────────────────────────────────
    def list_school_waitlist(self, school_id, headers, params=None):
        return self._request(
            "GET", f"/schools/{school_id}/waitlist", headers=headers, params=params,
        )

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def promote_waitlist(self, school_id, headers):
        return self._request("POST", f"/schools/{school_id}/waitlist/promote", {}, headers)

    # ── Clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers=None):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
