"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Ledger clock (PRD §3.15) ──────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── ApyTier (PRD §3.11) ───────────────────────────────────────
    def create_apy_tier(self, payload, headers):
        return self._request("POST", "/apy-tiers", payload, headers)

    def list_apy_tiers(self, headers, params=None):
        return self._request("GET", "/apy-tiers", headers=headers, params=params)

    # ─── Customer (PRD §3.1) ───────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_applications(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/applications", headers=headers, params=params
        )

    # ─── Application (PRD §3.1, §3.3) ──────────────────────────────
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def submit_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/submit",
            payload if payload is not None else {}, headers,
        )

    def approve_application(self, application_id, headers, payload=None):
        return self._request(
            "POST", f"/applications/{application_id}/approve",
            payload if payload is not None else {}, headers,
        )

    def reject_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/reject", payload, headers
        )

    # ─── Account (PRD §3.3–§3.8, §3.11) ────────────────────────────
    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def set_courtesy_pay(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/courtesy-pay", payload, headers
        )

    def freeze_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/accounts/{account_id}/freeze",
            payload if payload is not None else {}, headers,
        )

    def unfreeze_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/accounts/{account_id}/unfreeze",
            payload if payload is not None else {}, headers,
        )

    def close_account(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/accounts/{account_id}/close",
            payload if payload is not None else {}, headers,
        )

    def run_dormancy_scan(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/accounts/{account_id}/run-dormancy-scan",
            payload if payload is not None else {}, headers,
        )

    def run_escheat_sweep(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/accounts/{account_id}/run-escheat-sweep",
            payload if payload is not None else {}, headers,
        )

    def run_stop_expiry(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/accounts/{account_id}/run-stop-expiry",
            payload if payload is not None else {}, headers,
        )

    def post_interest(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/post-interest", payload, headers
        )

    # ─── AccountOwner (PRD §3.9) ───────────────────────────────────
    def add_owner(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/owners", payload, headers)

    def list_owners(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/owners", headers=headers, params=params
        )

    def delete_owner(self, account_id, owner_id, headers):
        return self._request(
            "DELETE", f"/accounts/{account_id}/owners/{owner_id}", headers=headers
        )

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    def list_account_owner_rows(self, headers, params=None):
        return self._request("GET", "/owners", headers=headers, params=params)

    # ─── Transaction (PRD §3.5) ────────────────────────────────────
    def create_transaction(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/transactions", payload, headers
        )

    def list_account_transactions(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/transactions", headers=headers, params=params
        )

    def get_transaction(self, transaction_id, headers):
        return self._request("GET", f"/transactions/{transaction_id}", headers=headers)

    def list_transactions(self, headers, params=None):
        return self._request("GET", "/transactions", headers=headers, params=params)

    # ─── FeeAssessment (PRD §3.6) ──────────────────────────────────
    def list_account_fee_assessments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/fee-assessments", headers=headers, params=params
        )

    def get_fee_assessment(self, fee_assessment_id, headers):
        return self._request(
            "GET", f"/fee-assessments/{fee_assessment_id}", headers=headers
        )

    def list_fee_assessments(self, headers, params=None):
        return self._request("GET", "/fee-assessments", headers=headers, params=params)

    # ─── StopPayment (PRD §3.10) ───────────────────────────────────
    def create_stop_payment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/stop-payments", payload, headers
        )

    def list_stop_payments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/stop-payments", headers=headers, params=params
        )

    # ─── InterestPosting (PRD §3.11) ───────────────────────────────
    def list_interest_postings(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/interest-postings", headers=headers, params=params
        )

    # ─── EscheatEvent (PRD §3.7) ───────────────────────────────────
    def list_escheat_events(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/escheat-events", headers=headers, params=params
        )

    # ─── AchOrigination (PRD §3.12–§3.14) ──────────────────────────
    def create_ach_origination(self, payload, headers):
        return self._request("POST", "/ach-originations", payload, headers)

    def get_ach_origination(self, origination_id, headers):
        return self._request("GET", f"/ach-originations/{origination_id}", headers=headers)

    def list_ach_originations(self, headers, params=None):
        return self._request("GET", "/ach-originations", headers=headers, params=params)

    def add_ach_leg(self, origination_id, payload, headers):
        return self._request(
            "POST", f"/ach-originations/{origination_id}/legs", payload, headers
        )

    def list_ach_legs_of_origination(self, origination_id, headers, params=None):
        return self._request(
            "GET", f"/ach-originations/{origination_id}/legs", headers=headers, params=params
        )

    def get_ach_leg(self, leg_id, headers):
        return self._request("GET", f"/ach-legs/{leg_id}", headers=headers)

    def list_ach_legs(self, headers, params=None):
        return self._request("GET", "/ach-legs", headers=headers, params=params)

    def settle_ach_origination(self, origination_id, payload, headers):
        return self._request(
            "POST", f"/ach-originations/{origination_id}/settle", payload, headers
        )

    def reverse_ach_origination(self, origination_id, payload, headers):
        return self._request(
            "POST", f"/ach-originations/{origination_id}/reverse", payload, headers
        )


api_client = ApiClient()
