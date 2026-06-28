"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- System / clock ----------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- CoverageProduct ---------------------------------------------------
    def create_coverage_product(self, payload, headers):
        return self._request("POST", "/coverage-products", payload, headers)

    def list_coverage_products(self, headers, params=None):
        return self._request("GET", "/coverage-products", headers=headers, params=params)

    def retire_coverage_product(self, product_id, headers):
        return self._request("POST", f"/coverage-products/{product_id}/retire", headers=headers)

    # ---- Vendor ------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def flag_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/flag", headers=headers)

    def default_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/default", headers=headers)

    def clear_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/clear", headers=headers)

    # ---- ForceMajeureEvent -------------------------------------------------
    def create_force_majeure_event(self, payload, headers):
        return self._request("POST", "/force-majeure-events", payload, headers)

    def list_force_majeure_events(self, headers, params=None):
        return self._request("GET", "/force-majeure-events", headers=headers, params=params)

    def activate_peril(self, event_id, headers):
        return self._request("POST", f"/force-majeure-events/{event_id}/activate", headers=headers)

    def expire_peril(self, event_id, headers):
        return self._request("POST", f"/force-majeure-events/{event_id}/expire", headers=headers)

    # ---- Policy ------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def bind_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/bind", headers=headers)

    def pay_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/pay", payload, headers)

    def activate_coverage(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/activate-coverage", headers=headers)

    def cancel_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/cancel", headers=headers)

    def expire_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/expire", headers=headers)

    def list_ledger(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/ledger", headers=headers, params=params)

    # ---- EventProfile ------------------------------------------------------
    def create_event_profile(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/event-profiles", payload, headers)

    def list_event_profiles(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/event-profiles", headers=headers, params=params)

    # ---- Coverage ----------------------------------------------------------
    def create_coverage(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/coverages", payload, headers)

    def list_coverages(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/coverages", headers=headers, params=params)

    def get_coverage(self, policy_id, coverage_id, headers):
        return self._request("GET", f"/policies/{policy_id}/coverages/{coverage_id}", headers=headers)

    # ---- Rider -------------------------------------------------------------
    def create_rider(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/riders", payload, headers)

    def list_riders(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/riders", headers=headers, params=params)

    # ---- Certificate -------------------------------------------------------
    def create_certificate(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/certificates", payload, headers)

    def list_certificates(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/certificates", headers=headers, params=params)

    def issue_certificate(self, policy_id, certificate_id, headers):
        return self._request("POST", f"/policies/{policy_id}/certificates/{certificate_id}/issue", headers=headers)

    def revoke_certificate(self, policy_id, certificate_id, headers):
        return self._request("POST", f"/policies/{policy_id}/certificates/{certificate_id}/revoke", headers=headers)

    # ---- Endorsement -------------------------------------------------------
    def create_endorsement(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/endorsements", payload, headers)

    def list_endorsements(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/endorsements", headers=headers, params=params)

    def apply_endorsement(self, policy_id, endorsement_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/endorsements/{endorsement_id}/apply", payload, headers)

    def reject_endorsement(self, policy_id, endorsement_id, headers):
        return self._request("POST", f"/policies/{policy_id}/endorsements/{endorsement_id}/reject", headers=headers)

    # ---- Claim -------------------------------------------------------------
    def create_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/claims", payload, headers)

    def list_claims(self, policy_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/claims", headers=headers, params=params)

    def get_claim(self, policy_id, claim_id, headers):
        return self._request("GET", f"/policies/{policy_id}/claims/{claim_id}", headers=headers)

    def create_claim_document(self, policy_id, claim_id, payload, headers):
        return self._request("POST", f"/policies/{policy_id}/claims/{claim_id}/documents", payload, headers)

    def list_claim_documents(self, policy_id, claim_id, headers, params=None):
        return self._request("GET", f"/policies/{policy_id}/claims/{claim_id}/documents", headers=headers, params=params)

    def request_info_claim(self, policy_id, claim_id, headers):
        return self._request("POST", f"/policies/{policy_id}/claims/{claim_id}/request-info", headers=headers)

    def resubmit_claim(self, policy_id, claim_id, headers):
        return self._request("POST", f"/policies/{policy_id}/claims/{claim_id}/resubmit", headers=headers)

    def approve_claim(self, policy_id, claim_id, headers):
        return self._request("POST", f"/policies/{policy_id}/claims/{claim_id}/approve", headers=headers)

    def deny_claim(self, policy_id, claim_id, headers):
        return self._request("POST", f"/policies/{policy_id}/claims/{claim_id}/deny", headers=headers)

    def pay_claim(self, policy_id, claim_id, headers):
        return self._request("POST", f"/policies/{policy_id}/claims/{claim_id}/pay", headers=headers)


api_client = ApiClient()
