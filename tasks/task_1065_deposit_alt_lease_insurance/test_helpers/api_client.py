"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Landlord / Renter registration ---
    def create_landlord(self, payload, headers):
        return self._request("POST", "/landlords", payload, headers)

    def get_landlord(self, landlord_id, headers):
        return self._request("GET", f"/landlords/{landlord_id}", headers=headers)

    def create_renter(self, payload, headers):
        return self._request("POST", "/renters", payload, headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_landlord_properties(self, landlord_id, headers, params=None):
        return self._request("GET", f"/landlords/{landlord_id}/properties", headers=headers, params=params)

    def update_property_program_status(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/program-status", payload, headers)

    # --- RenterEnrollment ---
    def create_renter_enrollment(self, payload, headers):
        return self._request("POST", "/renter-enrollments", payload, headers)

    def list_renter_enrollments(self, headers, params=None):
        return self._request("GET", "/renter-enrollments", headers=headers, params=params)

    def get_renter_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/renter-enrollments/{enrollment_id}", headers=headers)

    def submit_underwriting(self, enrollment_id, headers):
        return self._request("POST", f"/renter-enrollments/{enrollment_id}/submit-underwriting", {}, headers)

    def decide_renter_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/renter-enrollments/{enrollment_id}/decide", payload, headers)

    def get_renter_enrollment_policy(self, enrollment_id, headers):
        return self._request("GET", f"/renter-enrollments/{enrollment_id}/policy", headers=headers)

    # --- Policy ---
    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", {}, headers)

    def adjust_coverage_limit(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/coverage-limit-adjustments", payload, headers)

    def list_policy_invoices(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/invoices", headers=headers, params=params)

    # --- PremiumInvoice / Billing ---
    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def run_billing_cycle(self, headers):
        return self._request("POST", "/_billing/run-cycle", {}, headers)

    # --- Claim ---
    def create_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_policy_claims(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/claims", headers=headers, params=params)

    def claim_info_transition(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/info-transition", payload, headers)

    def decide_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/decide", payload, headers)

    def list_claim_payouts(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/payouts", headers=headers, params=params)

    # --- Payout ---
    def payout_transition(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/transition", payload, headers)

    # --- SubrogationCase / RecoveryPayment ---
    def create_subrogation_case(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/subrogation-cases", payload, headers)

    def list_claim_subrogation_cases(self, claim_id, headers, params=None):
        return self._request("GET", f"/claims/{claim_id}/subrogation-cases", headers=headers, params=params)

    def get_subrogation_case(self, subrogation_case_id, headers):
        return self._request("GET", f"/subrogation-cases/{subrogation_case_id}", headers=headers)

    def subrogation_case_transition(self, subrogation_case_id, payload, headers):
        return self._request("POST", f"/subrogation-cases/{subrogation_case_id}/transition", payload, headers)

    def create_recovery_payment(self, subrogation_case_id, payload, headers):
        return self._request("POST", f"/subrogation-cases/{subrogation_case_id}/recovery-payments", payload, headers)

    def list_recovery_payments(self, subrogation_case_id, headers, params=None):
        return self._request("GET", f"/subrogation-cases/{subrogation_case_id}/recovery-payments", headers=headers, params=params)

    def reverse_recovery_payment(self, recovery_payment_id, headers):
        return self._request("POST", f"/recovery-payments/{recovery_payment_id}/reverse", {}, headers)

    # --- StateComplianceRule ---
    def create_state_compliance_rule(self, payload, headers):
        return self._request("POST", "/state-compliance-rules", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
