"""API client: one method per endpoint defined in the PRD.

The API is mounted under `/school-meals`.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Households ----
    def create_household(self, payload, headers):
        return self._request("POST", "/school-meals/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/school-meals/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/school-meals/households", headers=headers, params=params)

    def update_household(self, household_id, payload, headers):
        return self._request("PATCH", f"/school-meals/households/{household_id}", payload, headers)

    def list_household_students(self, household_id, headers, params=None):
        return self._request(
            "GET",
            f"/school-meals/households/{household_id}/students",
            headers=headers,
            params=params,
        )

    def list_household_applications(self, household_id, headers, params=None):
        return self._request(
            "GET",
            f"/school-meals/households/{household_id}/applications",
            headers=headers,
            params=params,
        )

    def list_household_eligibility_determinations(self, household_id, headers, params=None):
        return self._request(
            "GET",
            f"/school-meals/households/{household_id}/eligibility-determinations",
            headers=headers,
            params=params,
        )

    def get_household_parent_account(self, household_id, headers):
        return self._request(
            "GET",
            f"/school-meals/households/{household_id}/parent-account",
            headers=headers,
        )

    # ---- Students ----
    def create_student(self, payload, headers):
        return self._request("POST", "/school-meals/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/school-meals/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/school-meals/students", headers=headers, params=params)

    def get_student_allergy_profile(self, student_id, headers):
        return self._request(
            "GET",
            f"/school-meals/students/{student_id}/allergy-profile",
            headers=headers,
        )

    # ---- AllergyProfile ----
    def create_allergy_profile(self, payload, headers):
        return self._request("POST", "/school-meals/allergy-profiles", payload, headers)

    def update_allergy_profile(self, profile_id, payload, headers):
        return self._request(
            "PATCH", f"/school-meals/allergy-profiles/{profile_id}", payload, headers
        )

    # ---- MealApplication ----
    def create_application(self, payload, headers):
        return self._request("POST", "/school-meals/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/school-meals/applications/{application_id}", headers=headers
        )

    def list_applications(self, headers, params=None):
        return self._request(
            "GET", "/school-meals/applications", headers=headers, params=params
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/school-meals/applications/{application_id}/submit", {}, headers
        )

    def start_review_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/school-meals/applications/{application_id}/start-review",
            {},
            headers,
        )

    def approve_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/applications/{application_id}/approve",
            payload,
            headers,
        )

    def deny_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/applications/{application_id}/deny",
            payload,
            headers,
        )

    def appeal_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/applications/{application_id}/appeal",
            payload,
            headers,
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST",
            f"/school-meals/applications/{application_id}/withdraw",
            {},
            headers,
        )

    # ---- EligibilityDetermination ----
    def create_eligibility_determination(self, payload, headers):
        return self._request(
            "POST", "/school-meals/eligibility-determinations", payload, headers
        )

    def get_eligibility_determination(self, det_id, headers):
        return self._request(
            "GET", f"/school-meals/eligibility-determinations/{det_id}", headers=headers
        )

    def list_eligibility_determinations(self, headers, params=None):
        return self._request(
            "GET",
            "/school-meals/eligibility-determinations",
            headers=headers,
            params=params,
        )

    def verify_eligibility_determination(self, det_id, headers):
        return self._request(
            "POST",
            f"/school-meals/eligibility-determinations/{det_id}/verify",
            {},
            headers,
        )

    def defer_eligibility_determination(self, det_id, headers):
        return self._request(
            "POST",
            f"/school-meals/eligibility-determinations/{det_id}/defer",
            {},
            headers,
        )

    def revoke_eligibility_determination(self, det_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/eligibility-determinations/{det_id}/revoke",
            payload,
            headers,
        )

    # ---- MenuItem ----
    def create_menu_item(self, payload, headers):
        return self._request("POST", "/school-meals/menu-items", payload, headers)

    def get_menu_item(self, menu_id, headers):
        return self._request("GET", f"/school-meals/menu-items/{menu_id}", headers=headers)

    def list_menu_items(self, headers, params=None):
        return self._request(
            "GET", "/school-meals/menu-items", headers=headers, params=params
        )

    # ---- ParentAccount & Ledger ----
    def get_parent_account(self, account_id, headers):
        return self._request(
            "GET", f"/school-meals/parent-accounts/{account_id}", headers=headers
        )

    def topup_parent_account(self, account_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/parent-accounts/{account_id}/topup",
            payload,
            headers,
        )

    def list_parent_account_ledger(self, account_id, headers, params=None):
        return self._request(
            "GET",
            f"/school-meals/parent-accounts/{account_id}/ledger",
            headers=headers,
            params=params,
        )

    def get_ledger_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/school-meals/ledger-entries/{entry_id}", headers=headers
        )

    def list_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/school-meals/ledger-entries", headers=headers, params=params
        )

    # ---- ServiceTransaction ----
    def create_service_transaction(self, payload, headers):
        return self._request(
            "POST", "/school-meals/service-transactions", payload, headers
        )

    def get_service_transaction(self, tx_id, headers):
        return self._request(
            "GET", f"/school-meals/service-transactions/{tx_id}", headers=headers
        )

    def list_service_transactions(self, headers, params=None):
        return self._request(
            "GET",
            "/school-meals/service-transactions",
            headers=headers,
            params=params,
        )

    def settle_service_transaction(self, tx_id, headers):
        return self._request(
            "POST",
            f"/school-meals/service-transactions/{tx_id}/settle",
            {},
            headers,
        )

    def reject_service_transaction(self, tx_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/service-transactions/{tx_id}/reject",
            payload,
            headers,
        )

    def refund_service_transaction(self, tx_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/service-transactions/{tx_id}/refund",
            payload,
            headers,
        )

    def dispute_service_transaction(self, tx_id, headers):
        return self._request(
            "POST",
            f"/school-meals/service-transactions/{tx_id}/dispute",
            {},
            headers,
        )

    def resolve_dispute_service_transaction(self, tx_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/service-transactions/{tx_id}/resolve-dispute",
            payload,
            headers,
        )

    # ---- ReimbursementClaim ----
    def create_reimbursement_claim(self, payload, headers):
        return self._request(
            "POST", "/school-meals/reimbursement-claims", payload, headers
        )

    def get_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/school-meals/reimbursement-claims/{claim_id}", headers=headers
        )

    def list_reimbursement_claims(self, headers, params=None):
        return self._request(
            "GET",
            "/school-meals/reimbursement-claims",
            headers=headers,
            params=params,
        )

    def submit_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "POST",
            f"/school-meals/reimbursement-claims/{claim_id}/submit",
            {},
            headers,
        )

    def finalize_reimbursement_claim(self, claim_id, headers):
        return self._request(
            "POST",
            f"/school-meals/reimbursement-claims/{claim_id}/finalize",
            {},
            headers,
        )

    def reject_reimbursement_claim(self, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/school-meals/reimbursement-claims/{claim_id}/reject",
            payload,
            headers,
        )

    # ---- Administrative (PlatformAdmin) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/school-meals/_clock/set_current_utc",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def advance_and_expire(self, to_iso8601, headers):
        return self._request(
            "POST",
            "/school-meals/_clock/advance_and_expire",
            {"to_iso8601": to_iso8601},
            headers,
        )

    def run_auto_renewal(self, payload, headers):
        return self._request(
            "POST", "/school-meals/_renewal/run_auto_renewal", payload, headers
        )


api_client = ApiClient()
