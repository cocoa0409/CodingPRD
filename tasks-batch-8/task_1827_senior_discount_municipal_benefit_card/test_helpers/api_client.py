"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/senior-benefits"


class ApiClient(GenericApiClient):
    def __init__(self, base_url=None):
        super().__init__(base_url)
        # The runner's per-test-server isolation SIGKILLs and respawns the API
        # server before every test. A pooled keep-alive connection opened
        # against the previous server instance can be reused in the window
        # before the kernel finishes delivering that instance's FIN/RST,
        # failing the first request of a test with ConnectionError ("Remote
        # end closed connection without response" / "Connection reset by
        # peer"). Sending `Connection: close` makes every request open a
        # fresh TCP connection, so no request can ever ride a connection
        # that predates the current server instance. No assertion or fixture
        # semantics change — this is transport hygiene only.
        self.session.headers["Connection"] = "close"

    # ------------------------------------------------------------------
    # Logical clock (test-driving capability)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Applications and verification documents
    # ------------------------------------------------------------------
    def create_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}", headers=headers)

    def start_review(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/start-review",
            {}, headers)

    def request_info(self, application_id, reason, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/request-info",
            {"reason": reason}, headers)

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/approve", {}, headers)

    def deny_application(self, application_id, reason, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/deny",
            {"reason": reason}, headers)

    def add_document(self, application_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/applications/{application_id}/documents",
            payload, headers)

    def list_documents(self, application_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/applications/{application_id}/documents",
            headers=headers, params=params)

    def review_document(self, application_id, document_id, decision, headers,
                        rejection_reason=None):
        payload = {"decision": decision}
        if rejection_reason is not None:
            payload["rejection_reason"] = rejection_reason
        return self._request(
            "POST",
            f"{PREFIX}/applications/{application_id}/documents/{document_id}/review",
            payload, headers)

    # ------------------------------------------------------------------
    # Cardholders, cards, fee waivers
    # ------------------------------------------------------------------
    def get_cardholder(self, cardholder_id, headers):
        return self._request(
            "GET", f"{PREFIX}/cardholders/{cardholder_id}", headers=headers)

    def list_cardholder_applications(self, cardholder_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cardholders/{cardholder_id}/applications",
            headers=headers, params=params)

    def issue_card(self, cardholder_id, reason, expected_cardholder_version, headers):
        return self._request(
            "POST", f"{PREFIX}/cardholders/{cardholder_id}/cards",
            {"reason": reason,
             "expected_cardholder_version": expected_cardholder_version},
            headers)

    def list_cards(self, cardholder_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cardholders/{cardholder_id}/cards",
            headers=headers, params=params)

    def revoke_cardholder(self, cardholder_id, reason, headers):
        return self._request(
            "POST", f"{PREFIX}/cardholders/{cardholder_id}/revoke",
            {"reason": reason}, headers)

    def grant_fee_waiver(self, cardholder_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/cardholders/{cardholder_id}/fee-waivers",
            payload, headers)

    def list_fee_waivers(self, cardholder_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/cardholders/{cardholder_id}/fee-waivers",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Merchants and discount offers
    # ------------------------------------------------------------------
    def create_merchant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/merchants", payload, headers)

    def get_merchant(self, merchant_id, headers):
        return self._request(
            "GET", f"{PREFIX}/merchants/{merchant_id}", headers=headers)

    def terminate_merchant(self, merchant_id, headers):
        return self._request(
            "POST", f"{PREFIX}/merchants/{merchant_id}/terminate", {}, headers)

    def create_offer(self, merchant_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/merchants/{merchant_id}/offers", payload, headers)

    def list_offers(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/merchants/{merchant_id}/offers",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Usage transactions
    # ------------------------------------------------------------------
    def create_usage_transaction(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-transactions", payload, headers)

    def list_usage_transactions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/usage-transactions", headers=headers, params=params)

    def get_usage_transaction(self, transaction_id, headers):
        return self._request(
            "GET", f"{PREFIX}/usage-transactions/{transaction_id}", headers=headers)

    def void_transaction(self, transaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-transactions/{transaction_id}/void",
            {}, headers)

    def flag_transaction(self, transaction_id, reason, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-transactions/{transaction_id}/flag",
            {"reason": reason}, headers)

    def clear_flag(self, transaction_id, headers):
        return self._request(
            "POST", f"{PREFIX}/usage-transactions/{transaction_id}/clear-flag",
            {}, headers)

    # ------------------------------------------------------------------
    # Program funds and reimbursement claims
    # ------------------------------------------------------------------
    def create_program_fund(self, payload, headers):
        return self._request("POST", f"{PREFIX}/program-funds", payload, headers)

    def get_program_fund(self, fund_id, headers):
        return self._request(
            "GET", f"{PREFIX}/program-funds/{fund_id}", headers=headers)

    def create_reimbursement_claim(self, merchant_id, period_month, headers):
        return self._request(
            "POST", f"{PREFIX}/merchants/{merchant_id}/reimbursement-claims",
            {"period_month": period_month}, headers)

    def list_reimbursement_claims(self, merchant_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/merchants/{merchant_id}/reimbursement-claims",
            headers=headers, params=params)

    def approve_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/reimbursement-claims/{claim_id}/approve",
            {}, headers)

    def deny_claim(self, claim_id, reason, headers):
        return self._request(
            "POST", f"{PREFIX}/reimbursement-claims/{claim_id}/deny",
            {"reason": reason}, headers)


api_client = ApiClient()
