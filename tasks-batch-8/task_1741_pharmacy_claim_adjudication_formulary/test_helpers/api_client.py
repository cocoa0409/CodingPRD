"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Plans ----
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/activate", headers=headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/retire", headers=headers)

    # ---- Drugs ----
    def create_drug(self, payload, headers):
        return self._request("POST", "/drugs", payload, headers)

    def get_drug(self, drug_id, headers):
        return self._request("GET", f"/drugs/{drug_id}", headers=headers)

    # ---- Formulary entries ----
    def create_formulary_entry(self, payload, headers):
        return self._request("POST", "/formulary-entries", payload, headers)

    def list_formulary_entries(self, headers, params=None):
        return self._request("GET", "/formulary-entries", headers=headers, params=params)

    def get_formulary_entry(self, entry_id, headers):
        return self._request("GET", f"/formulary-entries/{entry_id}", headers=headers)

    def update_formulary_entry(self, entry_id, payload, headers):
        return self._request("PUT", f"/formulary-entries/{entry_id}", payload, headers)

    # ---- Pharmacies ----
    def create_pharmacy(self, payload, headers):
        return self._request("POST", "/pharmacies", payload, headers)

    def get_pharmacy(self, pharmacy_id, headers):
        return self._request("GET", f"/pharmacies/{pharmacy_id}", headers=headers)

    def create_balance_adjustment(self, pharmacy_id, payload, headers):
        return self._request(
            "POST", f"/pharmacies/{pharmacy_id}/balance-adjustments", payload, headers
        )

    def reinstate_pharmacy(self, pharmacy_id, headers):
        return self._request("POST", f"/pharmacies/{pharmacy_id}/reinstate", headers=headers)

    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # ---- Prior authorizations ----
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/prior-authorizations", payload, headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request("GET", "/prior-authorizations", headers=headers, params=params)

    def get_prior_authorization(self, pa_id, headers):
        return self._request("GET", f"/prior-authorizations/{pa_id}", headers=headers)

    def approve_prior_authorization(self, pa_id, payload, headers):
        return self._request(
            "POST", f"/prior-authorizations/{pa_id}/approve", payload, headers
        )

    def deny_prior_authorization(self, pa_id, payload, headers):
        return self._request(
            "POST", f"/prior-authorizations/{pa_id}/deny", payload, headers
        )

    # ---- Claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", payload, headers)

    def reverse_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reverse", payload, headers)

    def reprocess_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reprocess", payload, headers)

    def list_dur_alerts(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/claims/{claim_id}/dur-alerts", headers=headers, params=params
        )

    # ---- Pharmacy audits ----
    def create_audit(self, payload, headers):
        return self._request("POST", "/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/audits/{audit_id}", headers=headers)

    def record_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/findings", payload, headers)

    def dispute_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/audits/{audit_id}/dispute", payload, headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"/audits/{audit_id}/close", headers=headers)


api_client = ApiClient()
