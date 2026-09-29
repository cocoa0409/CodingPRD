"""API client: one method per endpoint defined in the PRD."""

from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the state insurance guaranty association API."""

    # ---------------------------------------------------------------- coverage
    def create_coverage_profile(self, payload, headers):
        return self._request("POST", "/coverage-profiles", payload, headers)

    def list_coverage_profiles(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/coverage-profiles", headers=headers, params=params)

    # ------------------------------------------------------------- insolvencies
    def create_insolvency(self, payload, headers):
        return self._request("POST", "/insolvencies", payload, headers)

    def get_insolvency(self, insolvency_id, headers):
        return self._request("GET", f"/insolvencies/{insolvency_id}", headers=headers)

    def trigger_insolvency(self, insolvency_id, headers, payload=None):
        return self._request(
            "POST", f"/insolvencies/{insolvency_id}/trigger", payload or {}, headers
        )

    def create_estate_remittance(self, insolvency_id, payload, headers):
        return self._request(
            "POST", f"/insolvencies/{insolvency_id}/estate-remittances", payload, headers
        )

    def run_distribution(self, insolvency_id, payload, headers):
        return self._request(
            "POST", f"/insolvencies/{insolvency_id}/distributions", payload, headers
        )

    def close_insolvency(self, insolvency_id, headers, payload=None):
        return self._request(
            "POST", f"/insolvencies/{insolvency_id}/close", payload or {}, headers
        )

    # -------------------------------------------------------- proof of claim
    def create_poc_transfer(self, insolvency_id, payload, headers):
        return self._request(
            "POST", f"/insolvencies/{insolvency_id}/poc-transfers", payload, headers
        )

    def list_poc_transfers(self, insolvency_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/insolvencies/{insolvency_id}/poc-transfers", headers=headers, params=params
        )

    def convert_poc_transfer(self, transfer_id, headers, payload=None):
        return self._request(
            "POST", f"/poc-transfers/{transfer_id}/convert", payload or {}, headers
        )

    def get_poc_transfer(self, transfer_id, headers):
        return self._request("GET", f"/poc-transfers/{transfer_id}", headers=headers)

    # ---------------------------------------------------------- member insurers
    def create_member_insurer(self, payload, headers):
        return self._request("POST", "/member-insurers", payload, headers)

    def update_member_insurer(self, member_insurer_id, payload, headers):
        return self._request(
            "PATCH", f"/member-insurers/{member_insurer_id}", payload, headers
        )

    def get_member_insurer(self, member_insurer_id, headers):
        return self._request("GET", f"/member-insurers/{member_insurer_id}", headers=headers)

    # ----------------------------------------------------------------- policies
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def create_premium_refund(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/premium-refunds", payload, headers
        )

    def list_premium_refunds(self, policy_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/policies/{policy_id}/premium-refunds", headers=headers, params=params
        )

    # ------------------------------------------------------------------- claims
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def get_settlement_worksheet(self, claim_id, headers):
        return self._request(
            "GET", f"/claims/{claim_id}/settlement-worksheet", headers=headers
        )

    def screen_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/screen", payload, headers)

    # --------------------------------------------------------- other insurance
    def create_other_insurance(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/other-insurance", payload, headers
        )

    def update_other_insurance(self, claim_id, coverage_id, payload, headers):
        return self._request(
            "PATCH", f"/claims/{claim_id}/other-insurance/{coverage_id}", payload, headers
        )

    def list_other_insurance(self, claim_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/claims/{claim_id}/other-insurance", headers=headers, params=params
        )

    # ------------------------------------------------------------------ vendors
    def create_vendor_assignment(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/vendor-assignments", payload, headers
        )

    def list_vendor_assignments(self, claim_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/claims/{claim_id}/vendor-assignments", headers=headers, params=params
        )

    def create_vendor_invoice(self, claim_id, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/claims/{claim_id}/vendor-assignments/{assignment_id}/invoices",
            payload,
            headers,
        )

    # ------------------------------------------------------ claims committee
    def recommend_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/recommend", payload, headers)

    def remand_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/remand", payload, headers)

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/claims/{claim_id}/approve", payload or {}, headers
        )

    # ---------------------------------------------------------------- referrals
    def create_referral(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/referrals", payload, headers)

    def list_referrals(self, claim_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/claims/{claim_id}/referrals", headers=headers, params=params
        )

    def respond_referral(self, claim_id, referral_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/referrals/{referral_id}/respond", payload, headers
        )

    # -------------------------------------------------------------- assessments
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def certify_assessment(self, assessment_id, headers, payload=None):
        return self._request(
            "POST", f"/assessments/{assessment_id}/certify", payload or {}, headers
        )

    def list_insolvency_assessments(self, insolvency_id, headers, params: Optional[dict] = None):
        return self._request(
            "GET", f"/insolvencies/{insolvency_id}/assessments", headers=headers, params=params
        )

    # ------------------------------------------------------- member assessments
    def list_member_assessments(self, headers, params: Optional[dict] = None):
        return self._request("GET", "/member-assessments", headers=headers, params=params)

    def get_member_assessment(self, member_assessment_id, headers):
        return self._request(
            "GET", f"/member-assessments/{member_assessment_id}", headers=headers
        )

    def create_member_payment(self, member_assessment_id, payload, headers):
        return self._request(
            "POST", f"/member-assessments/{member_assessment_id}/payments", payload, headers
        )

    def create_surcharge_filing(self, member_assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/member-assessments/{member_assessment_id}/surcharge-filings",
            payload,
            headers,
        )

    def create_recoupment_remittance(self, member_assessment_id, payload, headers):
        return self._request(
            "POST",
            f"/member-assessments/{member_assessment_id}/recoupment-remittances",
            payload,
            headers,
        )

    # -------------------------------------------------------------- logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
