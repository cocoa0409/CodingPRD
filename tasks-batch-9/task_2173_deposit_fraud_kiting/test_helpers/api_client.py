"""API client: one method per endpoint defined in the PRD (§4)."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/deposit-fraud"


class ApiClient(GenericApiClient):
    # ---- Customers -------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def list_customer_accounts(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/customers/{customer_id}/accounts", headers=headers, params=params
        )

    def list_customer_subpoenas(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/customers/{customer_id}/subpoenas", headers=headers, params=params
        )

    def create_subpoena(self, customer_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/customers/{customer_id}/subpoenas", payload, headers
        )

    # ---- Accounts --------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/accounts/{account_id}", headers=headers)

    def create_funding_source(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/funding-sources", payload, headers
        )

    def list_funding_sources(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/accounts/{account_id}/funding-sources", headers=headers, params=params
        )

    def submit_verification_attempt(self, funding_source_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/funding-sources/{funding_source_id}/verification-attempts",
            payload,
            headers,
        )

    def resend_micro_deposits(self, funding_source_id, headers):
        return self._request(
            "POST", f"{PREFIX}/funding-sources/{funding_source_id}/resend", {}, headers
        )

    # ---- Association links ----------------------------------------------
    def create_account_link(self, payload, headers):
        return self._request("POST", f"{PREFIX}/account-links", payload, headers)

    def list_account_links(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/accounts/{account_id}/links", headers=headers, params=params
        )

    # ---- Deposited items -------------------------------------------------
    def create_deposit_item(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/deposit-items", payload, headers
        )

    def list_account_deposit_items(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/accounts/{account_id}/deposit-items", headers=headers, params=params
        )

    def get_deposit_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/deposit-items/{item_id}", headers=headers)

    def settle_deposit_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/deposit-items/{item_id}/settle", payload, headers
        )

    def list_item_holds(self, item_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/deposit-items/{item_id}/holds", headers=headers, params=params
        )

    # ---- Check holds -----------------------------------------------------
    def get_check_hold(self, hold_id, headers):
        return self._request("GET", f"{PREFIX}/check-holds/{hold_id}", headers=headers)

    def create_override_review(self, hold_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/check-holds/{hold_id}/override-reviews", payload, headers
        )

    def list_hold_override_reviews(self, hold_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/check-holds/{hold_id}/override-reviews", headers=headers, params=params
        )

    # ---- Override reviews ------------------------------------------------
    def get_override_review(self, review_id, headers):
        return self._request(
            "GET", f"{PREFIX}/hold-override-reviews/{review_id}", headers=headers
        )

    def submit_override_review(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/hold-override-reviews/{review_id}/submit", {}, headers
        )

    def decide_override_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/hold-override-reviews/{review_id}/decide", payload, headers
        )

    def execute_override_review(self, review_id, headers):
        return self._request(
            "POST", f"{PREFIX}/hold-override-reviews/{review_id}/execute", {}, headers
        )

    # ---- Account takeover ------------------------------------------------
    def record_access_review(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/access-review", payload, headers
        )

    def submit_step_up_response(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/step-up-response", payload, headers
        )

    # ---- Kiting detection ------------------------------------------------
    def run_kiting_scan(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/kiting-scan", payload, headers
        )

    # ---- Fraud cases -----------------------------------------------------
    def create_fraud_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fraud-cases", payload, headers)

    def get_fraud_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/fraud-cases/{case_id}", headers=headers)

    def list_account_fraud_cases(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/accounts/{account_id}/fraud-cases", headers=headers, params=params
        )

    def advance_fraud_case(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/fraud-cases/{case_id}/advance", {}, headers)

    def dispose_fraud_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fraud-cases/{case_id}/disposition", payload, headers
        )

    def close_fraud_case(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/fraud-cases/{case_id}/close", {}, headers)

    # ---- BSA referrals ---------------------------------------------------
    def create_bsa_referral(self, case_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fraud-cases/{case_id}/bsa-referrals", payload, headers
        )

    def list_case_bsa_referrals(self, case_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fraud-cases/{case_id}/bsa-referrals", headers=headers, params=params
        )

    def submit_bsa_referral(self, referral_id, headers):
        return self._request(
            "POST", f"{PREFIX}/bsa-referrals/{referral_id}/submit", {}, headers
        )

    def adjudicate_bsa_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bsa-referrals/{referral_id}/adjudicate", payload, headers
        )

    # ---- Charge-off and recovery ----------------------------------------
    def create_charge_off(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/accounts/{account_id}/charge-offs", payload, headers
        )

    def list_account_charge_offs(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/accounts/{account_id}/charge-offs", headers=headers, params=params
        )

    def get_charge_off(self, charge_off_id, headers):
        return self._request("GET", f"{PREFIX}/charge-offs/{charge_off_id}", headers=headers)

    def approve_charge_off(self, charge_off_id, headers):
        return self._request(
            "POST", f"{PREFIX}/charge-offs/{charge_off_id}/approve", {}, headers
        )

    def book_charge_off(self, charge_off_id, headers):
        return self._request("POST", f"{PREFIX}/charge-offs/{charge_off_id}/book", {}, headers)

    def create_recovery_posting(self, charge_off_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/charge-offs/{charge_off_id}/recovery-postings", payload, headers
        )

    def reverse_charge_off(self, charge_off_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/charge-offs/{charge_off_id}/reverse", payload, headers
        )

    # ---- Subpoena handling ----------------------------------------------
    def get_subpoena(self, subpoena_id, headers):
        return self._request("GET", f"{PREFIX}/subpoenas/{subpoena_id}", headers=headers)

    def legal_review_subpoena(self, subpoena_id, headers):
        return self._request(
            "POST", f"{PREFIX}/subpoenas/{subpoena_id}/legal-review", {}, headers
        )

    def respond_to_subpoena(self, subpoena_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subpoenas/{subpoena_id}/respond", payload, headers
        )

    # ---- Logical clock ---------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
