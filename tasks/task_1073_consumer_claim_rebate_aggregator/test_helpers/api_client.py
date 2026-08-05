"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the /rebate-aggregator prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/rebate-aggregator"


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- RebateProgram ----
    def create_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/programs", headers=headers, params=params)

    def get_program_report(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}/report", headers=headers)

    def get_fund_transactions(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}/fund-transactions",
                             headers=headers)

    def open_program(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/programs/{program_id}/open", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/programs/{program_id}/close", {}, headers)

    # ---- Consumer ----
    def create_consumer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consumers", payload, headers)

    def get_consumer(self, consumer_id, headers):
        return self._request("GET", f"{PREFIX}/consumers/{consumer_id}", headers=headers)

    def verify_consumer(self, consumer_id, headers):
        return self._request("POST", f"{PREFIX}/consumers/{consumer_id}/verify", {}, headers)

    def list_notifications(self, consumer_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/consumers/{consumer_id}/notifications",
                             headers=headers, params=params)

    # ---- Match ----
    def create_match(self, payload, headers):
        return self._request("POST", f"{PREFIX}/matches", payload, headers)

    def get_match(self, match_id, headers):
        return self._request("GET", f"{PREFIX}/matches/{match_id}", headers=headers)

    def list_matches(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/matches", headers=headers, params=params)

    # ---- Claim ----
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def upload_document(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/documents", payload, headers)

    def list_documents(self, claim_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}/documents",
                             headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/submit", {}, headers)

    def start_review(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/start-review", {}, headers)

    def request_info(self, claim_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/request-info",
                             payload or {}, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/resubmit", {}, headers)

    def approve_claim(self, claim_id, expected_program_version, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/approve",
                             {"expected_program_version": expected_program_version}, headers)

    def reject_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/reject",
                             payload or {}, headers)

    def list_eligibility_assessments(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}/eligibility-assessments",
                             headers=headers)

    # ---- Document review ----
    def verify_document(self, document_id, headers):
        return self._request("POST", f"{PREFIX}/documents/{document_id}/verify", {}, headers)

    def reject_document(self, document_id, rejection_reason, headers):
        return self._request("POST", f"{PREFIX}/documents/{document_id}/reject",
                             {"rejection_reason": rejection_reason}, headers)

    # ---- Fraud ----
    def raise_fraud_flag(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/fraud-flags", payload, headers)

    def list_fraud_flags(self, claim_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}/fraud-flags",
                             headers=headers, params=params)

    def confirm_fraud_flag(self, flag_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/fraud-flags/{flag_id}/confirm",
                             payload or {}, headers)

    def clear_fraud_flag(self, flag_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/fraud-flags/{flag_id}/clear",
                             payload or {}, headers)

    # ---- Payout ----
    def list_payouts(self, claim_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}/payouts",
                             headers=headers, params=params)

    def clear_payout(self, payout_id, headers):
        return self._request("POST", f"{PREFIX}/payouts/{payout_id}/clear", {}, headers)

    def fail_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/payouts/{payout_id}/fail",
                             payload or {}, headers)

    def retry_payout(self, payout_id, headers):
        return self._request("POST", f"{PREFIX}/payouts/{payout_id}/retry", {}, headers)

    def reverse_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/payouts/{payout_id}/reverse",
                             payload or {}, headers)


api_client = ApiClient()
