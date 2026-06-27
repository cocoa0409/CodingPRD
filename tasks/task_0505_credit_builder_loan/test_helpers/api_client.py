"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Account -----
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", headers=headers, params=params)

    def kyc_decision(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/kyc-decision", payload, headers)

    def freeze_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/freeze", payload, headers)

    def unfreeze_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/unfreeze", payload, headers)

    def close_account(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/close", payload, headers)

    def get_score(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/score", headers=headers, params=params)

    def list_score_snapshots(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/score-snapshots", headers=headers, params=params)

    # ----- Disclosure -----
    def create_disclosure(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/disclosures", payload, headers)

    def list_disclosures(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/disclosures", headers=headers, params=params)

    def get_disclosure(self, disclosure_id, headers):
        return self._request("GET", f"/disclosures/{disclosure_id}", headers=headers)

    def acknowledge_disclosure(self, disclosure_id, payload, headers):
        return self._request("POST", f"/disclosures/{disclosure_id}/acknowledge", payload, headers)

    # ----- CreditBuilderLoan -----
    def create_loan(self, payload, headers):
        return self._request("POST", "/loans", payload, headers)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def fund_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/fund", payload, headers)

    def cancel_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/cancel", payload, headers)

    def graduate_loan(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/graduate", payload, headers)

    def list_schedule(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/schedule", headers=headers, params=params)

    def list_loan_payments(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/payments", headers=headers, params=params)

    def list_loan_bureau_reports(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/bureau-reports", headers=headers, params=params)

    def create_payoff_quote(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/payoff-quote", payload, headers)

    def list_payoff_quotes(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/payoff-quotes", headers=headers, params=params)

    def early_payoff(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/early-payoff", payload, headers)

    # ----- Payment -----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ----- SecuredCard -----
    def create_secured_card(self, payload, headers):
        return self._request("POST", "/secured-cards", payload, headers)

    def get_secured_card(self, card_id, headers):
        return self._request("GET", f"/secured-cards/{card_id}", headers=headers)

    def list_secured_cards(self, headers, params=None):
        return self._request("GET", "/secured-cards", headers=headers, params=params)

    def create_deposit(self, card_id, payload, headers):
        return self._request("POST", f"/secured-cards/{card_id}/deposits", payload, headers)

    def list_deposits(self, card_id, headers, params=None):
        return self._request("GET", f"/secured-cards/{card_id}/deposits", headers=headers, params=params)

    def activate_card(self, card_id, payload, headers):
        return self._request("POST", f"/secured-cards/{card_id}/activate", payload, headers)

    def charge_card(self, card_id, payload, headers):
        return self._request("POST", f"/secured-cards/{card_id}/charges", payload, headers)

    def suspend_card(self, card_id, payload, headers):
        return self._request("POST", f"/secured-cards/{card_id}/suspend", payload, headers)

    def resume_card(self, card_id, payload, headers):
        return self._request("POST", f"/secured-cards/{card_id}/resume", payload, headers)

    def release_deposit(self, card_id, payload, headers):
        return self._request("POST", f"/secured-cards/{card_id}/release-deposit", payload, headers)

    def list_card_bureau_reports(self, card_id, headers, params=None):
        return self._request("GET", f"/secured-cards/{card_id}/bureau-reports", headers=headers, params=params)

    # ----- AutopayEnrollment -----
    def create_autopay(self, payload, headers):
        return self._request("POST", "/autopay-enrollments", payload, headers)

    def list_autopay(self, headers, params=None):
        return self._request("GET", "/autopay-enrollments", headers=headers, params=params)

    def get_autopay(self, enrollment_id, headers):
        return self._request("GET", f"/autopay-enrollments/{enrollment_id}", headers=headers)

    def patch_autopay(self, enrollment_id, payload, headers):
        return self._request("PATCH", f"/autopay-enrollments/{enrollment_id}", payload, headers)

    # ----- Clock + batch sweeps -----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_autopay(self, payload, headers):
        return self._request("POST", "/_clock/run-autopay", payload, headers)

    def run_delinquency_sweep(self, payload, headers):
        return self._request("POST", "/_clock/run-delinquency-sweep", payload, headers)

    def run_bureau_sweep(self, payload, headers):
        return self._request("POST", "/_clock/run-bureau-sweep", payload, headers)


api_client = ApiClient()
