"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- test-driving / config ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- reference data ----
    def create_courtroom(self, payload, headers):
        return self._request("POST", "/courtrooms", payload, headers)

    def get_courtroom(self, courtroom_id, headers):
        return self._request("GET", f"/courtrooms/{courtroom_id}", headers=headers)

    def create_service_site(self, payload, headers):
        return self._request("POST", "/service-sites", payload, headers)

    def get_service_site(self, site_id, headers):
        return self._request("GET", f"/service-sites/{site_id}", headers=headers)

    def create_amnesty_program(self, payload, headers):
        return self._request("POST", "/amnesty-programs", payload, headers)

    # ---- defendants ----
    def create_defendant(self, payload, headers):
        return self._request("POST", "/defendants", payload, headers)

    def get_defendant(self, defendant_id, headers):
        return self._request("GET", f"/defendants/{defendant_id}", headers=headers)

    def list_defendant_cases(self, defendant_id, headers, params=None):
        return self._request(
            "GET", f"/defendants/{defendant_id}/cases", headers=headers, params=params
        )

    # ---- cases & charges ----
    def create_case(self, payload, headers):
        return self._request("POST", "/cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}", headers=headers)

    def create_charge(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/charges", payload, headers)

    def list_charges(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/charges", headers=headers, params=params
        )

    # ---- arraignment & plea ----
    def create_arraignment(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/arraignments", payload, headers)

    def get_arraignment(self, arraignment_id, headers):
        return self._request("GET", f"/arraignments/{arraignment_id}", headers=headers)

    def list_arraignments(self, headers, params=None):
        return self._request("GET", "/arraignments", headers=headers, params=params)

    def enter_plea(self, arraignment_id, payload, headers):
        return self._request(
            "POST", f"/arraignments/{arraignment_id}/plea", payload, headers
        )

    # ---- diversion ----
    def grant_diversion(self, case_id, payload, headers):
        return self._request(
            "POST", f"/cases/{case_id}/diversion-agreements", payload, headers
        )

    def list_diversion_agreements(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/diversion-agreements", headers=headers, params=params
        )

    def accept_diversion(self, diversion_id, headers):
        return self._request(
            "POST", f"/diversion-agreements/{diversion_id}/accept", {}, headers
        )

    # ---- service assignments ----
    def create_service_assignment(self, diversion_id, payload, headers):
        return self._request(
            "POST", f"/diversion-agreements/{diversion_id}/service-assignments", payload, headers
        )

    def get_service_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/service-assignments/{assignment_id}", headers=headers
        )

    def list_service_assignments(self, headers, params=None):
        return self._request(
            "GET", "/service-assignments", headers=headers, params=params
        )

    def progress_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/service-assignments/{assignment_id}/progress", payload, headers
        )

    def verify_completion(self, assignment_id, headers):
        return self._request(
            "POST", f"/service-assignments/{assignment_id}/verify-completion", {}, headers
        )

    def waive_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/service-assignments/{assignment_id}/waive", {}, headers
        )

    # ---- financial ----
    def get_case_ledger_account(self, case_id, headers):
        return self._request("GET", f"/cases/{case_id}/ledger-account", headers=headers)

    def get_ledger_account(self, account_id, headers):
        return self._request("GET", f"/ledger-accounts/{account_id}", headers=headers)

    def create_installment_plan(self, account_id, payload, headers):
        return self._request(
            "POST", f"/ledger-accounts/{account_id}/installment-plans", payload, headers
        )

    def list_installment_plans(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/ledger-accounts/{account_id}/installment-plans", headers=headers, params=params
        )

    def create_payment(self, account_id, payload, headers):
        return self._request(
            "POST", f"/ledger-accounts/{account_id}/payments", payload, headers
        )

    def list_payments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/ledger-accounts/{account_id}/payments", headers=headers, params=params
        )

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # ---- compliance / warrant / amnesty / expungement ----
    def dismiss_case(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/dismiss", {}, headers)

    def issue_warrant(self, case_id, headers):
        return self._request("POST", f"/cases/{case_id}/warrant", {}, headers)

    def list_warrants(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/warrants", headers=headers, params=params
        )

    def reinstate_case(self, case_id, payload, headers):
        return self._request("POST", f"/cases/{case_id}/reinstate", payload, headers)

    def list_expungement_referrals(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/cases/{case_id}/expungement-referrals", headers=headers, params=params
        )

    def submit_expungement_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/expungement-referrals/{referral_id}/submit", {}, headers
        )


api_client = ApiClient()
