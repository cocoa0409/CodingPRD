"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Rent cap policies (PRD §3.1) ---
    def create_rent_cap_policy(self, payload, headers):
        return self._request("POST", "/rent-cap-policies", payload, headers)

    def get_rent_cap_policy(self, policy_id, headers):
        return self._request("GET", f"/rent-cap-policies/{policy_id}", headers=headers)

    def patch_rent_cap_policy(self, policy_id, payload, headers):
        return self._request("PATCH", f"/rent-cap-policies/{policy_id}", payload, headers)

    # --- Properties (PRD §3.1) ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def patch_property(self, property_id, payload, headers):
        return self._request("PATCH", f"/properties/{property_id}", payload, headers)

    def get_retention_metrics(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/properties/{property_id}/retention-metrics", headers=headers, params=params
        )

    def get_expiration_forecast(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/properties/{property_id}/expiration-forecast", headers=headers, params=params
        )

    # --- Units (PRD §3.1) ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    # --- Residents (PRD §3.1) ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/residents", headers=headers, params=params)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    # --- Leases (PRD §3.2) ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    # --- Renewal offers (PRD §3.3, §3.4) ---
    def create_renewal_offer(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/renewal-offers", payload, headers)

    def list_renewal_offers(self, headers, params=None):
        return self._request("GET", "/renewal-offers", headers=headers, params=params)

    def get_renewal_offer(self, offer_id, headers):
        return self._request("GET", f"/renewal-offers/{offer_id}", headers=headers)

    def issue_renewal_offer(self, offer_id, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/issue", {}, headers)

    def respond_to_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/respond", payload, headers)

    def revise_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/revise", payload, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/renewal-offers/{offer_id}/withdraw", {}, headers)

    # --- Concession approvals (PRD §3.5) ---
    def create_concession_approval(self, offer_id, payload, headers):
        return self._request(
            "POST", f"/renewal-offers/{offer_id}/concession-approvals", payload, headers
        )

    def list_concession_approvals(self, headers, params=None):
        return self._request("GET", "/concession-approvals", headers=headers, params=params)

    def get_concession_approval(self, concession_id, headers):
        return self._request("GET", f"/concession-approvals/{concession_id}", headers=headers)

    def approve_concession(self, concession_id, headers):
        return self._request("POST", f"/concession-approvals/{concession_id}/approve", {}, headers)

    def deny_concession(self, concession_id, headers):
        return self._request("POST", f"/concession-approvals/{concession_id}/deny", {}, headers)

    # --- Non-renewal notices (PRD §3.6) ---
    def create_non_renewal_notice(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/non-renewal-notices", payload, headers)

    def list_non_renewal_notices(self, headers, params=None):
        return self._request("GET", "/non-renewal-notices", headers=headers, params=params)

    def get_non_renewal_notice(self, notice_id, headers):
        return self._request("GET", f"/non-renewal-notices/{notice_id}", headers=headers)

    def serve_notice(self, notice_id, headers):
        return self._request("POST", f"/non-renewal-notices/{notice_id}/serve", {}, headers)

    def rescind_notice(self, notice_id, headers):
        return self._request("POST", f"/non-renewal-notices/{notice_id}/rescind", {}, headers)

    # --- Renewal documents (PRD §3.7) ---
    def list_renewal_documents(self, headers, params=None):
        return self._request("GET", "/renewal-documents", headers=headers, params=params)

    def get_renewal_document(self, document_id, headers):
        return self._request("GET", f"/renewal-documents/{document_id}", headers=headers)

    def sign_document_resident(self, document_id, headers):
        return self._request("POST", f"/renewal-documents/{document_id}/sign-resident", {}, headers)

    def countersign_document(self, document_id, headers):
        return self._request("POST", f"/renewal-documents/{document_id}/countersign", {}, headers)

    def rescind_document(self, document_id, headers):
        return self._request("POST", f"/renewal-documents/{document_id}/rescind", {}, headers)


api_client = ApiClient()
