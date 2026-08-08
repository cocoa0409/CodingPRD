"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fraud-recovery"


class ApiClient(GenericApiClient):
    # ---- Subject ----
    def create_subject(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subjects", payload, headers)

    def get_subject(self, subject_id, headers):
        return self._request("GET", f"{PREFIX}/subjects/{subject_id}", headers=headers)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def decide_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/decide", payload, headers)

    # ---- Case ----
    def create_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases", headers=headers, params=params)

    def assign_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/assign", payload, headers)

    def submit_review(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/submit-review", {}, headers)

    def adjudicate_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/adjudicate", payload, headers)

    def create_evidence(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/evidence", payload, headers)

    def list_evidence(self, case_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases/{case_id}/evidence", headers=headers, params=params)

    # ---- Overpayment ----
    def create_overpayment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/overpayments", payload, headers)

    def get_overpayment(self, overpayment_id, headers):
        return self._request("GET", f"{PREFIX}/overpayments/{overpayment_id}", headers=headers)

    def list_overpayments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/overpayments", headers=headers, params=params)

    def create_month(self, overpayment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/overpayments/{overpayment_id}/months", payload, headers)

    def list_months(self, overpayment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/overpayments/{overpayment_id}/months", headers=headers, params=params)

    def calculate_overpayment(self, overpayment_id, headers):
        return self._request("POST", f"{PREFIX}/overpayments/{overpayment_id}/calculate", {}, headers)

    def establish_overpayment(self, overpayment_id, headers):
        return self._request("POST", f"{PREFIX}/overpayments/{overpayment_id}/establish", {}, headers)

    def demand_overpayment(self, overpayment_id, headers):
        return self._request("POST", f"{PREFIX}/overpayments/{overpayment_id}/demand", {}, headers)

    def post_adjustment(self, overpayment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/overpayments/{overpayment_id}/adjustments", payload, headers)

    def write_off_overpayment(self, overpayment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/overpayments/{overpayment_id}/write-off", payload, headers)

    def list_overpayment_transactions(self, overpayment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/overpayments/{overpayment_id}/transactions", headers=headers, params=params)

    # ---- Disqualification ----
    def create_disqualification(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disqualifications", payload, headers)

    def get_disqualification(self, disqualification_id, headers):
        return self._request("GET", f"{PREFIX}/disqualifications/{disqualification_id}", headers=headers)

    def list_disqualifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disqualifications", headers=headers, params=params)

    def refer_adh(self, disqualification_id, headers):
        return self._request("POST", f"{PREFIX}/disqualifications/{disqualification_id}/refer-adh", {}, headers)

    def rescind_disqualification(self, disqualification_id, payload, headers):
        return self._request("POST", f"{PREFIX}/disqualifications/{disqualification_id}/rescind", payload, headers)

    # ---- Hearing ----
    def create_hearing(self, payload, headers):
        return self._request("POST", f"{PREFIX}/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"{PREFIX}/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/hearings", headers=headers, params=params)

    def hold_hearing(self, hearing_id, headers):
        return self._request("POST", f"{PREFIX}/hearings/{hearing_id}/hold", {}, headers)

    def decide_hearing(self, hearing_id, payload, headers):
        return self._request("POST", f"{PREFIX}/hearings/{hearing_id}/decide", payload, headers)

    # ---- Recovery ----
    def create_recovery_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/recovery-plans", payload, headers)

    def get_recovery_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/recovery-plans/{plan_id}", headers=headers)

    def list_recovery_plans(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/recovery-plans", headers=headers, params=params)

    def default_plan(self, plan_id, headers):
        return self._request("POST", f"{PREFIX}/recovery-plans/{plan_id}/default", {}, headers)

    def create_transaction(self, payload, headers):
        return self._request("POST", f"{PREFIX}/recovery-transactions", payload, headers)

    def list_plan_transactions(self, plan_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/recovery-plans/{plan_id}/transactions", headers=headers, params=params)

    def void_transaction(self, transaction_id, payload, headers):
        return self._request("POST", f"{PREFIX}/recovery-transactions/{transaction_id}/void", payload, headers)

    # ---- Reporting ----
    def get_recovery_summary(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reports/recovery-summary", headers=headers, params=params)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
