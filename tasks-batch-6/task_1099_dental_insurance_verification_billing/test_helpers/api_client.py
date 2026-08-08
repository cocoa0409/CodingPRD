"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Ops / clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_billing(self, headers):
        return self._request("POST", "/billing/run", {}, headers)

    # --- Patient ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    # --- InsurancePlan ---
    def create_insurance_plan(self, payload, headers):
        return self._request("POST", "/insurance-plans", payload, headers)

    # --- Procedure ---
    def create_procedure(self, payload, headers):
        return self._request("POST", "/procedures", payload, headers)

    # --- MembershipPlan ---
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    # --- Coverage ---
    def create_coverage(self, payload, headers):
        return self._request("POST", "/coverages", payload, headers)

    def get_coverage(self, coverage_id, headers):
        return self._request("GET", f"/coverages/{coverage_id}", headers=headers)

    def list_coverages(self, headers, params=None):
        return self._request("GET", "/coverages", headers=headers, params=params)

    def create_verification(self, coverage_id, payload, headers):
        return self._request("POST", f"/coverages/{coverage_id}/verifications",
                             payload, headers)

    # --- Verification ---
    def get_verification(self, verification_id, headers):
        return self._request("GET", f"/verifications/{verification_id}", headers=headers)

    def list_verifications(self, headers, params=None):
        return self._request("GET", "/verifications", headers=headers, params=params)

    # --- PreAuthorization ---
    def create_preauthorization(self, payload, headers):
        return self._request("POST", "/preauthorizations", payload, headers)

    def get_preauthorization(self, preauth_id, headers):
        return self._request("GET", f"/preauthorizations/{preauth_id}", headers=headers)

    def list_preauthorizations(self, headers, params=None):
        return self._request("GET", "/preauthorizations", headers=headers, params=params)

    def submit_preauthorization(self, preauth_id, headers):
        return self._request("POST", f"/preauthorizations/{preauth_id}/submit", {}, headers)

    def decide_preauthorization(self, preauth_id, outcome, headers):
        return self._request("POST", f"/preauthorizations/{preauth_id}/decision",
                             {"outcome": outcome}, headers)

    # --- Attachment ---
    def create_attachment(self, payload, headers):
        return self._request("POST", "/attachments", payload, headers)

    def get_attachment(self, attachment_id, headers):
        return self._request("GET", f"/attachments/{attachment_id}", headers=headers)

    def list_attachments(self, headers, params=None):
        return self._request("GET", "/attachments", headers=headers, params=params)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/submit", {}, headers)

    def appeal_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/appeal", {}, headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/reverse", {}, headers)

    # --- Membership ---
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def pay_membership(self, membership_id, amount_cents, headers):
        return self._request("POST", f"/memberships/{membership_id}/pay",
                             {"amount_cents": amount_cents}, headers)


api_client = ApiClient()
