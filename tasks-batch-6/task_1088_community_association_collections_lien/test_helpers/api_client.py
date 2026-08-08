"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/collections/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Association ---
    def create_association(self, payload, headers):
        return self._request("POST", "/collections/associations", payload, headers)

    def get_association(self, association_id, headers):
        return self._request("GET", f"/collections/associations/{association_id}", headers=headers)

    def get_aging_report(self, association_id, headers):
        return self._request("GET", f"/collections/associations/{association_id}/aging-report",
                             headers=headers)

    # --- Account ---
    def create_account(self, payload, headers):
        return self._request("POST", "/collections/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/collections/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/collections/accounts", headers=headers, params=params)

    def transition_account(self, account_id, to_status, headers):
        return self._request("POST", f"/collections/accounts/{account_id}/transition",
                             {"to_status": to_status}, headers)

    # --- Assessment ---
    def create_assessment(self, payload, headers):
        return self._request("POST", "/collections/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/collections/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/collections/assessments", headers=headers, params=params)

    def waive_assessment(self, assessment_id, headers):
        return self._request("POST", f"/collections/assessments/{assessment_id}/waive",
                             {}, headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/collections/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/collections/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/collections/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, reversal_reason, headers):
        return self._request("POST", f"/collections/payments/{payment_id}/reverse",
                             {"reversal_reason": reversal_reason}, headers)

    # --- Notice ---
    def create_notice(self, payload, headers):
        return self._request("POST", "/collections/notices", payload, headers)

    def get_notice(self, notice_id, headers):
        return self._request("GET", f"/collections/notices/{notice_id}", headers=headers)

    def list_notices(self, headers, params=None):
        return self._request("GET", "/collections/notices", headers=headers, params=params)

    def transition_notice(self, notice_id, to_status, headers):
        return self._request("POST", f"/collections/notices/{notice_id}/transition",
                             {"to_status": to_status}, headers)

    # --- PaymentPlan ---
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/collections/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/collections/payment-plans/{plan_id}", headers=headers)

    def list_payment_plans(self, headers, params=None):
        return self._request("GET", "/collections/payment-plans", headers=headers, params=params)

    def transition_payment_plan(self, plan_id, to_status, headers):
        return self._request("POST", f"/collections/payment-plans/{plan_id}/transition",
                             {"to_status": to_status}, headers)

    # --- Lien ---
    def create_lien(self, payload, headers):
        return self._request("POST", "/collections/liens", payload, headers)

    def get_lien(self, lien_id, headers):
        return self._request("GET", f"/collections/liens/{lien_id}", headers=headers)

    def list_liens(self, headers, params=None):
        return self._request("GET", "/collections/liens", headers=headers, params=params)

    def transition_lien(self, lien_id, to_status, headers):
        return self._request("POST", f"/collections/liens/{lien_id}/transition",
                             {"to_status": to_status}, headers)

    # --- ForeclosureReferral ---
    def create_foreclosure_referral(self, payload, headers):
        return self._request("POST", "/collections/foreclosure-referrals", payload, headers)

    def get_foreclosure_referral(self, referral_id, headers):
        return self._request("GET", f"/collections/foreclosure-referrals/{referral_id}",
                             headers=headers)

    def list_foreclosure_referrals(self, headers, params=None):
        return self._request("GET", "/collections/foreclosure-referrals", headers=headers,
                             params=params)

    def transition_foreclosure_referral(self, referral_id, to_status, headers):
        return self._request("POST", f"/collections/foreclosure-referrals/{referral_id}/transition",
                             {"to_status": to_status}, headers)

    # --- BankruptcyCase ---
    def create_bankruptcy_case(self, payload, headers):
        return self._request("POST", "/collections/bankruptcy-cases", payload, headers)

    def get_bankruptcy_case(self, case_id, headers):
        return self._request("GET", f"/collections/bankruptcy-cases/{case_id}", headers=headers)

    def list_bankruptcy_cases(self, headers, params=None):
        return self._request("GET", "/collections/bankruptcy-cases", headers=headers, params=params)

    def transition_bankruptcy_case(self, case_id, to_status, headers):
        return self._request("POST", f"/collections/bankruptcy-cases/{case_id}/transition",
                             {"to_status": to_status}, headers)

    # --- Remittance ---
    def create_remittance(self, payload, headers):
        return self._request("POST", "/collections/remittances", payload, headers)

    def get_remittance(self, remittance_id, headers):
        return self._request("GET", f"/collections/remittances/{remittance_id}", headers=headers)

    def list_remittances(self, headers, params=None):
        return self._request("GET", "/collections/remittances", headers=headers, params=params)

    def transition_remittance(self, remittance_id, to_status, headers):
        return self._request("POST", f"/collections/remittances/{remittance_id}/transition",
                             {"to_status": to_status}, headers)

    # --- Payoff quote (dual-variant computed read) ---
    def get_payoff_quote(self, account_id, headers, variant=None):
        params = None if variant is None else {"variant": variant}
        return self._request("GET", f"/collections/accounts/{account_id}/payoff-quote",
                             headers=headers, params=params)


api_client = ApiClient()
