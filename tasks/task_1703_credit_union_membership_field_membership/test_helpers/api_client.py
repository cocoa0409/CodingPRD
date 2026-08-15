"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Charter
    # ------------------------------------------------------------------
    def create_charter(self, payload, headers):
        return self._request("POST", "/credit-union/charters", payload, headers)

    def get_charter(self, charter_id, headers):
        return self._request("GET", f"/credit-union/charters/{charter_id}",
                             headers=headers)

    def list_charter_segments(self, charter_id, headers, params=None):
        return self._request("GET", f"/credit-union/charters/{charter_id}/segments",
                             headers=headers, params=params)

    def list_charter_amendment_applications(self, charter_id, headers, params=None):
        return self._request(
            "GET", f"/credit-union/charters/{charter_id}/amendment-applications",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Charter amendment applications
    # ------------------------------------------------------------------
    def create_amendment_application(self, payload, headers):
        return self._request("POST", "/credit-union/charter-amendment-applications",
                             payload, headers)

    def approve_amendment_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/credit-union/charter-amendment-applications/{application_id}/approve",
            {}, headers)

    def deny_amendment_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/credit-union/charter-amendment-applications/{application_id}/deny",
            payload, headers)

    # ------------------------------------------------------------------
    # Membership applications
    # ------------------------------------------------------------------
    def create_membership_application(self, payload, headers):
        return self._request("POST", "/credit-union/membership-applications",
                             payload, headers)

    def list_membership_applications(self, headers, params=None):
        return self._request("GET", "/credit-union/membership-applications",
                             headers=headers, params=params)

    def get_membership_application(self, application_id, headers):
        return self._request(
            "GET", f"/credit-union/membership-applications/{application_id}",
            headers=headers)

    def request_documents(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/credit-union/membership-applications/{application_id}/request-documents",
            payload, headers)

    def submit_documents(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/credit-union/membership-applications/{application_id}/submit-documents",
            payload, headers)

    def approve_membership_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/credit-union/membership-applications/{application_id}/approve",
            {}, headers)

    def deny_membership_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/credit-union/membership-applications/{application_id}/deny",
            payload, headers)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def list_members(self, headers, params=None):
        return self._request("GET", "/credit-union/members",
                             headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/credit-union/members/{member_id}",
                             headers=headers)

    def patch_member(self, member_id, payload, headers):
        return self._request("PATCH", f"/credit-union/members/{member_id}",
                             payload, headers)

    def tier_review(self, member_id, headers):
        return self._request("POST",
                             f"/credit-union/members/{member_id}/tier-review",
                             {}, headers)

    # ------------------------------------------------------------------
    # Share accounts
    # ------------------------------------------------------------------
    def create_share_account(self, payload, headers):
        return self._request("POST", "/credit-union/share-accounts", payload, headers)

    def get_share_account(self, account_id, headers):
        return self._request("GET", f"/credit-union/share-accounts/{account_id}",
                             headers=headers)

    def list_member_share_accounts(self, member_id, headers, params=None):
        return self._request("GET",
                             f"/credit-union/members/{member_id}/share-accounts",
                             headers=headers, params=params)

    def close_share_account(self, account_id, headers):
        return self._request("POST",
                             f"/credit-union/share-accounts/{account_id}/close",
                             {}, headers)

    def post_share_transaction(self, account_id, payload, headers):
        return self._request(
            "POST", f"/credit-union/share-accounts/{account_id}/transactions",
            payload, headers)

    def list_share_transactions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/credit-union/share-accounts/{account_id}/transactions",
            headers=headers, params=params)

    def list_account_dividend_payments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/credit-union/share-accounts/{account_id}/dividend-payments",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Product enrollments
    # ------------------------------------------------------------------
    def create_product_enrollment(self, payload, headers):
        return self._request("POST", "/credit-union/product-enrollments",
                             payload, headers)

    def list_product_enrollments(self, headers, params=None):
        return self._request("GET", "/credit-union/product-enrollments",
                             headers=headers, params=params)

    def get_product_enrollment(self, enrollment_id, headers):
        return self._request("GET",
                             f"/credit-union/product-enrollments/{enrollment_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Dividend declarations
    # ------------------------------------------------------------------
    def create_dividend_declaration(self, payload, headers):
        return self._request("POST", "/credit-union/dividend-declarations",
                             payload, headers)

    def get_dividend_declaration(self, declaration_id, headers):
        return self._request("GET",
                             f"/credit-union/dividend-declarations/{declaration_id}",
                             headers=headers)

    def void_dividend_declaration(self, declaration_id, headers):
        return self._request(
            "POST", f"/credit-union/dividend-declarations/{declaration_id}/void",
            {}, headers)

    def pay_dividend_declaration(self, declaration_id, headers):
        return self._request(
            "POST", f"/credit-union/dividend-declarations/{declaration_id}/pay",
            {}, headers)

    def list_declaration_payments(self, declaration_id, headers, params=None):
        return self._request(
            "GET", f"/credit-union/dividend-declarations/{declaration_id}/payments",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Annual meetings and ballots
    # ------------------------------------------------------------------
    def create_annual_meeting(self, payload, headers):
        return self._request("POST", "/credit-union/annual-meetings", payload, headers)

    def list_annual_meetings(self, headers, params=None):
        return self._request("GET", "/credit-union/annual-meetings",
                             headers=headers, params=params)

    def get_annual_meeting(self, meeting_id, headers):
        return self._request("GET", f"/credit-union/annual-meetings/{meeting_id}",
                             headers=headers)

    def close_and_tally(self, meeting_id, headers):
        return self._request(
            "POST", f"/credit-union/annual-meetings/{meeting_id}/close-and-tally",
            {}, headers)

    def reconvene_meeting(self, meeting_id, payload, headers):
        return self._request(
            "POST", f"/credit-union/annual-meetings/{meeting_id}/reconvene",
            payload, headers)

    def cast_ballot(self, payload, headers):
        return self._request("POST", "/credit-union/ballots", payload, headers)

    def list_meeting_ballots(self, meeting_id, headers, params=None):
        return self._request(
            "GET", f"/credit-union/annual-meetings/{meeting_id}/ballots",
            headers=headers, params=params)

    def list_member_ballots(self, member_id, headers, params=None):
        return self._request("GET", f"/credit-union/members/{member_id}/ballots",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Eligibility reviews
    # ------------------------------------------------------------------
    def create_eligibility_review(self, member_id, payload, headers):
        return self._request(
            "POST", f"/credit-union/members/{member_id}/eligibility-reviews",
            payload, headers)

    def list_member_eligibility_reviews(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/credit-union/members/{member_id}/eligibility-reviews",
            headers=headers, params=params)

    def cure_eligibility_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/credit-union/eligibility-reviews/{review_id}/cure",
            payload, headers)

    def confirm_ineligible(self, review_id, headers):
        return self._request(
            "POST",
            f"/credit-union/eligibility-reviews/{review_id}/confirm-ineligible",
            {}, headers)


api_client = ApiClient()
