"""API client: one method per endpoint defined in the PRD (PRD §4).

Subclasses the framework's `GenericApiClient` to inherit the `_request` HTTP
plumbing; this module supplies only the per-endpoint thin wrappers.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Products (PRD §3.1, §4) ─────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    # ─── Coverage tiers (PRD §3.1, §4) ───────────────────────────
    def create_coverage_tier(self, payload, headers):
        return self._request("POST", "/coverage-tiers", payload, headers)

    def get_coverage_tier(self, tier_id, headers):
        return self._request("GET", f"/coverage-tiers/{tier_id}", headers=headers)

    def list_coverage_tiers(self, headers, params=None):
        return self._request("GET", "/coverage-tiers", headers=headers, params=params)

    # ─── Owners (PRD §3.2, §4) ───────────────────────────────────
    def create_owner(self, payload, headers):
        return self._request("POST", "/owners", payload, headers)

    def get_owner(self, owner_id, headers):
        return self._request("GET", f"/owners/{owner_id}", headers=headers)

    # ─── Registrations (PRD §3.2, §3.11, §3.13, §4) ──────────────
    def create_registration(self, payload, headers):
        return self._request("POST", "/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/registrations", headers=headers, params=params)

    def transfer_registration(self, registration_id, payload, headers):
        return self._request(
            "POST", f"/registrations/{registration_id}/transfer", payload, headers
        )

    def accept_transfer(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/transfer/accept",
            payload if payload is not None else {},
            headers,
        )

    def reject_transfer(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/transfer/reject",
            payload if payload is not None else {},
            headers,
        )

    def void_registration(self, registration_id, headers, payload=None):
        return self._request(
            "POST",
            f"/registrations/{registration_id}/void",
            payload if payload is not None else {},
            headers,
        )

    def list_registration_ledger(self, registration_id, headers, params=None):
        return self._request(
            "GET", f"/registrations/{registration_id}/ledger", headers=headers, params=params
        )

    def list_registration_transfers(self, registration_id, headers, params=None):
        return self._request(
            "GET", f"/registrations/{registration_id}/transfers", headers=headers, params=params
        )

    # ─── Extended warranties (PRD §3.4, §4) ──────────────────────
    def create_extended_warranty(self, payload, headers):
        return self._request("POST", "/extended-warranties", payload, headers)

    def cancel_extended_warranty(self, ew_id, headers, payload=None):
        return self._request(
            "POST",
            f"/extended-warranties/{ew_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def get_extended_warranty(self, ew_id, headers):
        return self._request("GET", f"/extended-warranties/{ew_id}", headers=headers)

    def list_extended_warranties(self, headers, params=None):
        return self._request("GET", "/extended-warranties", headers=headers, params=params)

    # ─── Proofs of purchase (PRD §3.3, §4) ───────────────────────
    def create_proof(self, payload, headers):
        return self._request("POST", "/proofs", payload, headers)

    def validate_proof(self, proof_id, headers, payload=None):
        return self._request(
            "POST",
            f"/proofs/{proof_id}/validate",
            payload if payload is not None else {},
            headers,
        )

    def get_proof(self, proof_id, headers):
        return self._request("GET", f"/proofs/{proof_id}", headers=headers)

    def list_proofs(self, headers, params=None):
        return self._request("GET", "/proofs", headers=headers, params=params)

    # ─── Claims (PRD §3.5, §3.6, §3.7, §3.10, §4) ────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def issue_rma(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"/claims/{claim_id}/issue-rma",
            payload if payload is not None else {},
            headers,
        )

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/adjudicate", payload, headers
        )

    def fulfill_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"/claims/{claim_id}/fulfill",
            payload if payload is not None else {},
            headers,
        )

    def withdraw_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"/claims/{claim_id}/withdraw",
            payload if payload is not None else {},
            headers,
        )

    # ─── Test-driving clock (PRD §3.13, §4) ──────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
