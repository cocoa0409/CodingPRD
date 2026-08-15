"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Terms & breaks ---
    def create_term(self, payload, headers):
        return self._request("POST", "/r2t4/terms", payload, headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/r2t4/terms", headers=headers,
                             params=params or {})

    def get_term(self, term_id, headers):
        return self._request("GET", f"/r2t4/terms/{term_id}", headers=headers)

    def create_break(self, term_id, payload, headers):
        return self._request("POST", f"/r2t4/terms/{term_id}/breaks",
                             payload, headers)

    def list_breaks(self, term_id, headers, params=None):
        return self._request("GET", f"/r2t4/terms/{term_id}/breaks",
                             headers=headers, params=params or {})

    # --- Students & enrollments ---
    def create_student(self, payload, headers):
        return self._request("POST", "/r2t4/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/r2t4/students/{student_id}",
                             headers=headers)

    def create_enrollment(self, student_id, payload, headers):
        return self._request("POST", f"/r2t4/students/{student_id}/enrollments",
                             payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/r2t4/enrollments", headers=headers,
                             params=params or {})

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/r2t4/enrollments/{enrollment_id}",
                             headers=headers)

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/r2t4/enrollments/{enrollment_id}/withdraw",
                             payload, headers)

    def rescind_withdrawal(self, enrollment_id, headers):
        return self._request(
            "POST", f"/r2t4/enrollments/{enrollment_id}/rescind-withdrawal",
            {}, headers)

    def complete_enrollment(self, enrollment_id, headers):
        return self._request("POST",
                             f"/r2t4/enrollments/{enrollment_id}/complete",
                             {}, headers)

    def record_payment(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/r2t4/enrollments/{enrollment_id}/payments",
                             payload, headers)

    def list_enrollment_awards(self, enrollment_id, headers, params=None):
        return self._request("GET",
                             f"/r2t4/enrollments/{enrollment_id}/awards",
                             headers=headers, params=params or {})

    def list_enrollment_account_entries(self, enrollment_id, headers,
                                        params=None):
        return self._request(
            "GET", f"/r2t4/enrollments/{enrollment_id}/account-entries",
            headers=headers, params=params or {})

    # --- Awards & disbursements ---
    def create_award(self, enrollment_id, payload, headers):
        return self._request("POST",
                             f"/r2t4/enrollments/{enrollment_id}/awards",
                             payload, headers)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/r2t4/awards/{award_id}", headers=headers)

    def accept_award(self, award_id, headers):
        return self._request("POST", f"/r2t4/awards/{award_id}/accept",
                             {}, headers)

    def cancel_award(self, award_id, headers):
        return self._request("POST", f"/r2t4/awards/{award_id}/cancel",
                             {}, headers)

    def create_disbursement(self, award_id, payload, headers):
        return self._request("POST",
                             f"/r2t4/awards/{award_id}/disbursements",
                             payload, headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/r2t4/disbursements", headers=headers,
                             params=params or {})

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/r2t4/disbursements/{disbursement_id}",
                             headers=headers)

    def disburse_disbursement(self, disbursement_id, headers):
        return self._request("POST",
                             f"/r2t4/disbursements/{disbursement_id}/disburse",
                             {}, headers)

    # --- Withdrawal cases ---
    def list_withdrawal_cases(self, headers, params=None):
        return self._request("GET", "/r2t4/withdrawal-cases", headers=headers,
                             params=params or {})

    def get_withdrawal_case(self, case_id, headers):
        return self._request("GET", f"/r2t4/withdrawal-cases/{case_id}",
                             headers=headers)

    def calculate_case(self, case_id, headers):
        return self._request("POST",
                             f"/r2t4/withdrawal-cases/{case_id}/calculate",
                             {}, headers)

    def recalculate_case(self, case_id, payload, headers):
        return self._request("POST",
                             f"/r2t4/withdrawal-cases/{case_id}/recalculate",
                             payload, headers)

    def list_case_obligations(self, case_id, headers, params=None):
        return self._request("GET",
                             f"/r2t4/withdrawal-cases/{case_id}/obligations",
                             headers=headers, params=params or {})

    def list_case_offers(self, case_id, headers, params=None):
        return self._request("GET",
                             f"/r2t4/withdrawal-cases/{case_id}/offers",
                             headers=headers, params=params or {})

    # --- Obligations & offers ---
    def record_return(self, obligation_id, payload, headers):
        return self._request(
            "POST", f"/r2t4/return-obligations/{obligation_id}/record-return",
            payload, headers)

    def list_post_withdrawal_offers(self, headers, params=None):
        return self._request("GET", "/r2t4/post-withdrawal-offers",
                             headers=headers, params=params or {})

    def get_post_withdrawal_offer(self, offer_id, headers):
        return self._request("GET",
                             f"/r2t4/post-withdrawal-offers/{offer_id}",
                             headers=headers)

    def accept_offer(self, offer_id, headers):
        return self._request("POST",
                             f"/r2t4/post-withdrawal-offers/{offer_id}/accept",
                             {}, headers)

    def decline_offer(self, offer_id, headers):
        return self._request("POST",
                             f"/r2t4/post-withdrawal-offers/{offer_id}/decline",
                             {}, headers)

    # --- Ledger reads ---
    def list_account_entries(self, headers, params=None):
        return self._request("GET", "/r2t4/account-entries", headers=headers,
                             params=params or {})

    def get_account_entry(self, entry_id, headers):
        return self._request("GET", f"/r2t4/account-entries/{entry_id}",
                             headers=headers)

    # --- Test-driving logical clock ---
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/r2t4/_clock/set_current_utc", payload,
                             headers)


api_client = ApiClient()
