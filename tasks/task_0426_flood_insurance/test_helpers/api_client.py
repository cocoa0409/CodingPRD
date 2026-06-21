"""API client: one method per endpoint defined in the Flood Insurance PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Community ---
    def create_community(self, payload, headers):
        return self._request("POST", "/communities", payload, headers)

    def get_community(self, community_id, headers):
        return self._request("GET", f"/communities/{community_id}", headers=headers)

    def update_community(self, community_id, payload, headers):
        return self._request("PATCH", f"/communities/{community_id}", payload, headers)

    def list_community_properties(self, community_id, headers, params=None):
        return self._request(
            "GET", f"/communities/{community_id}/properties", headers=headers, params=params
        )

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def list_property_elevation_certificates(self, property_id, headers, params=None):
        return self._request(
            "GET",
            f"/properties/{property_id}/elevation-certificates",
            headers=headers,
            params=params,
        )

    def list_property_policies(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/properties/{property_id}/policies", headers=headers, params=params
        )

    # --- ElevationCertificate ---
    def create_elevation_certificate(self, payload, headers):
        return self._request("POST", "/elevation-certificates", payload, headers)

    def get_elevation_certificate(self, certificate_id, headers):
        return self._request(
            "GET", f"/elevation-certificates/{certificate_id}", headers=headers
        )

    # --- Policy (quote / lifecycle) ---
    def quote_policy(self, property_id, payload, headers):
        return self._request(
            "POST", f"/properties/{property_id}/policies", payload, headers
        )

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def bind_policy(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/policies/{policy_id}/bind", payload or {}, headers
        )

    def expire_quote(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/policies/{policy_id}/expire-quote", payload or {}, headers
        )

    def activate_policy(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/policies/{policy_id}/activate", payload or {}, headers
        )

    def cancel_policy(self, policy_id, payload, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/cancel", payload, headers
        )

    def lapse_policy(self, policy_id, headers, payload=None):
        return self._request(
            "POST", f"/policies/{policy_id}/lapse", payload or {}, headers
        )

    # --- PolicyTransfer ---
    def create_policy_transfer(self, payload, headers):
        return self._request("POST", "/policy-transfers", payload, headers)

    def get_policy_transfer(self, transfer_id, headers):
        return self._request("GET", f"/policy-transfers/{transfer_id}", headers=headers)

    def list_policy_transfers(self, headers, params=None):
        return self._request("GET", "/policy-transfers", headers=headers, params=params)

    # --- Claim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def open_review(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/claims/{claim_id}/open-review", payload or {}, headers
        )

    def approve_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/approve", payload, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", payload, headers)

    def list_claim_proofs_of_loss(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"/claims/{claim_id}/proofs-of-loss", headers=headers, params=params
        )

    # --- ProofOfLoss ---
    def create_proof_of_loss(self, payload, headers):
        return self._request("POST", "/proofs-of-loss", payload, headers)

    def get_proof_of_loss(self, proof_id, headers):
        return self._request("GET", f"/proofs-of-loss/{proof_id}", headers=headers)

    def accept_proof_of_loss(self, proof_id, headers, payload=None):
        return self._request(
            "POST", f"/proofs-of-loss/{proof_id}/accept", payload or {}, headers
        )

    def reject_proof_of_loss(self, proof_id, headers, payload=None):
        return self._request(
            "POST", f"/proofs-of-loss/{proof_id}/reject", payload or {}, headers
        )

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
