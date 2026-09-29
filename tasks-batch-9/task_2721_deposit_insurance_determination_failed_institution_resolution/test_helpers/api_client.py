"""API client: one method per endpoint published in PRD 4.

The URL topology is flat, so every collection is a root-level path and no shared
prefix is applied.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Institutions
    # ------------------------------------------------------------------
    def create_institution(self, payload, headers):
        return self._request("POST", "/institutions", payload, headers)

    def list_institutions(self, headers, params=None):
        return self._request("GET", "/institutions", headers=headers, params=params)

    def get_institution(self, institution_id, headers):
        return self._request("GET", f"/institutions/{institution_id}", headers=headers)

    def get_insurance_summary(self, institution_id, headers):
        return self._request(
            "GET", f"/institutions/{institution_id}/insurance-summary", headers=headers
        )

    def close_institution(self, institution_id, headers, payload=None):
        return self._request(
            "POST", f"/institutions/{institution_id}/close", payload or {}, headers
        )

    def franchise_marketing(self, institution_id, payload, headers):
        return self._request(
            "POST", f"/institutions/{institution_id}/franchise-marketing", payload, headers
        )

    def post_receivership_proceeds(self, institution_id, payload, headers):
        return self._request(
            "POST",
            f"/institutions/{institution_id}/receivership-proceeds",
            payload,
            headers,
        )

    def terminate_receivership(self, institution_id, headers, payload=None):
        return self._request(
            "POST",
            f"/institutions/{institution_id}/terminate-receivership",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Readiness submissions
    # ------------------------------------------------------------------
    def create_readiness_submission(self, institution_id, payload, headers):
        return self._request(
            "POST",
            f"/institutions/{institution_id}/readiness-submissions",
            payload,
            headers,
        )

    def list_readiness_submissions(self, institution_id, headers, params=None):
        return self._request(
            "GET",
            f"/institutions/{institution_id}/readiness-submissions",
            headers=headers,
            params=params,
        )

    def standardize_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST",
            f"/readiness-submissions/{submission_id}/standardize",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Depositor records
    # ------------------------------------------------------------------
    def create_depositor_record(self, institution_id, payload, headers):
        return self._request(
            "POST", f"/institutions/{institution_id}/depositor-records", payload, headers
        )

    def list_depositor_records(self, headers, params=None):
        return self._request("GET", "/depositor-records", headers=headers, params=params)

    def get_depositor_record(self, depositor_record_id, headers):
        return self._request(
            "GET", f"/depositor-records/{depositor_record_id}", headers=headers
        )

    def list_depositor_ownership_interests(self, depositor_record_id, headers, params=None):
        return self._request(
            "GET",
            f"/depositor-records/{depositor_record_id}/ownership-interests",
            headers=headers,
            params=params,
        )

    def acknowledge_notice(self, depositor_record_id, headers, payload=None):
        return self._request(
            "POST",
            f"/depositor-records/{depositor_record_id}/acknowledge-notice",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Deposit accounts and ownership interests
    # ------------------------------------------------------------------
    def create_deposit_account(self, payload, headers):
        return self._request("POST", "/deposit-accounts", payload, headers)

    def list_deposit_accounts(self, headers, params=None):
        return self._request("GET", "/deposit-accounts", headers=headers, params=params)

    def get_deposit_account(self, account_id, headers):
        return self._request("GET", f"/deposit-accounts/{account_id}", headers=headers)

    def create_ownership_interest(self, account_id, payload, headers):
        return self._request(
            "POST", f"/deposit-accounts/{account_id}/ownership-interests", payload, headers
        )

    def list_account_ownership_interests(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/deposit-accounts/{account_id}/ownership-interests",
            headers=headers,
            params=params,
        )

    def release_hold(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/deposit-accounts/{account_id}/release-hold", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Insurance determinations
    # ------------------------------------------------------------------
    def create_determination(self, payload, headers):
        return self._request("POST", "/insurance-determinations", payload, headers)

    def list_determinations(self, headers, params=None):
        return self._request(
            "GET", "/insurance-determinations", headers=headers, params=params
        )

    def get_determination(self, determination_id, headers):
        return self._request(
            "GET", f"/insurance-determinations/{determination_id}", headers=headers
        )

    def prepare_determination(self, determination_id, payload, headers):
        return self._request(
            "POST",
            f"/insurance-determinations/{determination_id}/prepare",
            payload,
            headers,
        )

    def submit_determination_review(self, determination_id, headers, payload=None):
        return self._request(
            "POST",
            f"/insurance-determinations/{determination_id}/submit-review",
            payload or {},
            headers,
        )

    def certify_determination(self, determination_id, headers, payload=None):
        return self._request(
            "POST",
            f"/insurance-determinations/{determination_id}/certify",
            payload or {},
            headers,
        )

    def request_determination_revision(self, determination_id, payload, headers):
        return self._request(
            "POST",
            f"/insurance-determinations/{determination_id}/request-revision",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Receivership certificates
    # ------------------------------------------------------------------
    def list_certificates(self, headers, params=None):
        return self._request(
            "GET", "/receivership-certificates", headers=headers, params=params
        )

    def get_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/receivership-certificates/{certificate_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Bidders and bids
    # ------------------------------------------------------------------
    def create_bidder(self, payload, headers):
        return self._request("POST", "/bidders", payload, headers)

    def list_bidders(self, headers, params=None):
        return self._request("GET", "/bidders", headers=headers, params=params)

    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"/bidders/{bidder_id}", headers=headers)

    def decide_qualification(self, bidder_id, payload, headers):
        return self._request(
            "POST", f"/bidders/{bidder_id}/qualification", payload, headers
        )

    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, bid_id, headers, payload=None):
        return self._request("POST", f"/bids/{bid_id}/withdraw", payload or {}, headers)

    # ------------------------------------------------------------------
    # The least-cost test
    # ------------------------------------------------------------------
    def evaluate_least_cost_test(self, institution_id, payload, headers):
        return self._request(
            "POST",
            f"/institutions/{institution_id}/least-cost-test/evaluate",
            payload,
            headers,
        )

    def award_least_cost_test(self, institution_id, headers, payload=None):
        return self._request(
            "POST",
            f"/institutions/{institution_id}/least-cost-test/award",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Branch reopenings
    # ------------------------------------------------------------------
    def create_branch_reopening(self, institution_id, payload, headers):
        return self._request(
            "POST", f"/institutions/{institution_id}/branch-reopenings", payload, headers
        )

    def list_branch_reopenings(self, institution_id, headers, params=None):
        return self._request(
            "GET",
            f"/institutions/{institution_id}/branch-reopenings",
            headers=headers,
            params=params,
        )

    def get_branch_reopening(self, branch_reopening_id, headers):
        return self._request(
            "GET", f"/branch-reopenings/{branch_reopening_id}", headers=headers
        )

    def reschedule_branch_reopening(self, branch_reopening_id, payload, headers):
        return self._request(
            "POST",
            f"/branch-reopenings/{branch_reopening_id}/reschedule",
            payload,
            headers,
        )

    def reopen_branch(self, branch_reopening_id, headers, payload=None):
        return self._request(
            "POST",
            f"/branch-reopenings/{branch_reopening_id}/reopen",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # Dividend distributions
    # ------------------------------------------------------------------
    def declare_dividend(self, institution_id, payload, headers):
        return self._request(
            "POST",
            f"/institutions/{institution_id}/dividend-distributions",
            payload,
            headers,
        )

    def list_dividends(self, headers, params=None):
        return self._request(
            "GET", "/dividend-distributions", headers=headers, params=params
        )

    def get_dividend(self, distribution_id, headers):
        return self._request(
            "GET", f"/dividend-distributions/{distribution_id}", headers=headers
        )

    def settle_dividend(self, distribution_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dividend-distributions/{distribution_id}/settle",
            payload or {},
            headers,
        )

    def void_dividend(self, distribution_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dividend-distributions/{distribution_id}/void",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------------
    # The logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def set_clock_raw(self, payload, headers):
        """Advance the clock with a caller-supplied payload, valid or not."""
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
