"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ---------------------------------------------------- #
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def get_clock(self, headers):
        return self._request("GET", "/_clock", headers=headers)

    # ---- ProductPlan ------------------------------------------------------ #
    def create_product_plan(self, payload, headers):
        return self._request("POST", "/product-plans", payload, headers)

    def get_product_plan(self, plan_id, headers):
        return self._request("GET", f"/product-plans/{plan_id}", headers=headers)

    def list_product_plans(self, headers, params=None):
        return self._request("GET", "/product-plans", headers=headers, params=params)

    # ---- Applicant -------------------------------------------------------- #
    def create_applicant(self, payload, headers):
        return self._request("POST", "/applicants", payload, headers)

    def get_applicant(self, applicant_id, headers):
        return self._request("GET", f"/applicants/{applicant_id}", headers=headers)

    # ---- Application ------------------------------------------------------ #
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def attach_questionnaire(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/questionnaire", payload, headers
        )

    def get_questionnaire(self, questionnaire_id, headers):
        return self._request(
            "GET", f"/health-questionnaires/{questionnaire_id}", headers=headers
        )

    def list_questionnaires(self, headers, params=None):
        return self._request(
            "GET", "/health-questionnaires", headers=headers, params=params
        )

    def submit_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/submit", {}, headers
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/approve", {}, headers
        )

    def decline_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/decline", {}, headers
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/withdraw", {}, headers
        )

    def issue_application(self, application_id, payload, headers):
        return self._request(
            "POST", f"/applications/{application_id}/issue", payload, headers
        )

    # ---- Policy ----------------------------------------------------------- #
    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def lapse_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/lapse", {}, headers)

    def reinstate_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/reinstate", {}, headers)

    def surrender_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/surrender", {}, headers)

    # ---- Beneficiary ------------------------------------------------------ #
    def create_beneficiary(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/beneficiaries", payload, headers
        )

    def list_beneficiaries(self, policy_id, headers, params=None):
        return self._request(
            "GET", f"/policies/{policy_id}/beneficiaries", headers=headers, params=params
        )

    def revoke_beneficiary(self, policy_id, beneficiary_id, headers):
        return self._request(
            "POST",
            f"/policies/{policy_id}/beneficiaries/{beneficiary_id}/revoke",
            {},
            headers,
        )

    # ---- FuneralHomeAssignment ------------------------------------------- #
    def create_funeral_home_assignment(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/funeral-home-assignment", payload, headers
        )

    def list_funeral_home_assignments(self, policy_id, headers, params=None):
        return self._request(
            "GET",
            f"/policies/{policy_id}/funeral-home-assignments",
            headers=headers,
            params=params,
        )

    # ---- PremiumPayment --------------------------------------------------- #
    def create_premium_payment(self, payload, headers):
        return self._request("POST", "/premium-payments", payload, headers)

    def get_premium_payment(self, payment_id, headers):
        return self._request(
            "GET", f"/premium-payments/{payment_id}", headers=headers
        )

    def list_premium_payments(self, headers, params=None):
        return self._request(
            "GET", "/premium-payments", headers=headers, params=params
        )

    def reverse_premium_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/premium-payments/{payment_id}/reverse", {}, headers
        )

    # ---- PolicyLoan ------------------------------------------------------- #
    def create_policy_loan(self, payload, headers):
        return self._request("POST", "/policy-loans", payload, headers)

    def get_policy_loan(self, loan_id, headers):
        return self._request("GET", f"/policy-loans/{loan_id}", headers=headers)

    def list_policy_loans(self, headers, params=None):
        return self._request("GET", "/policy-loans", headers=headers, params=params)

    def repay_policy_loan(self, loan_id, payload, headers):
        return self._request(
            "POST", f"/policy-loans/{loan_id}/repay", payload, headers
        )

    # ---- Claim ------------------------------------------------------------ #
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def attach_death_certificate(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/death-certificate", payload, headers
        )

    def get_death_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/death-certificates/{certificate_id}", headers=headers
        )

    def list_death_certificates(self, headers, params=None):
        return self._request(
            "GET", "/death-certificates", headers=headers, params=params
        )

    def start_review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/start-review", {}, headers)

    def contest_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/contest", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    # ---- LedgerEntry ------------------------------------------------------ #
    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/ledger-entries/{entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)


api_client = ApiClient()
