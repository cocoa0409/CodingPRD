"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles URL construction,
header attachment, and JSON/query encoding (GET passes payload as query params).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Products ─────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def retire_product(self, product_id, headers):
        return self._request("POST", f"/products/{product_id}/retire", {}, headers)

    # ─── Contracts ────────────────────────────────────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def get_projection(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/projection", headers=headers, params=params
        )

    def list_contract_premiums(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/premiums", headers=headers, params=params
        )

    def list_contract_withdrawals(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/withdrawals", headers=headers, params=params
        )

    def list_contract_crediting_events(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/crediting-events", headers=headers, params=params
        )

    def list_contract_beneficiaries(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/beneficiaries", headers=headers, params=params
        )

    def list_contract_sub_account_allocations(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/sub-account-allocations", headers=headers, params=params
        )

    def list_contract_index_segments(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/index-segments", headers=headers, params=params
        )

    def list_contract_annuitizations(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/annuitizations", headers=headers, params=params
        )

    def list_contract_death_claims(self, contract_id, headers, params=None):
        return self._request(
            "GET", f"/contracts/{contract_id}/death-claims", headers=headers, params=params
        )

    # ─── Premiums ─────────────────────────────────────────────────────────
    def create_premium(self, payload, headers):
        return self._request("POST", "/premiums", payload, headers)

    def list_premiums(self, headers, params=None):
        return self._request("GET", "/premiums", headers=headers, params=params)

    def get_premium(self, premium_id, headers):
        return self._request("GET", f"/premiums/{premium_id}", headers=headers)

    def clear_premium(self, premium_id, headers):
        return self._request("POST", f"/premiums/{premium_id}/clear", {}, headers)

    def reject_premium(self, premium_id, headers):
        return self._request("POST", f"/premiums/{premium_id}/reject", {}, headers)

    # ─── Sub-account allocations ──────────────────────────────────────────
    def create_sub_account_allocation(self, payload, headers):
        return self._request("POST", "/sub-account-allocations", payload, headers)

    def get_sub_account_allocation(self, alloc_id, headers):
        return self._request("GET", f"/sub-account-allocations/{alloc_id}", headers=headers)

    # ─── Index segments ───────────────────────────────────────────────────
    def create_index_segment(self, payload, headers):
        return self._request("POST", "/index-segments", payload, headers)

    def get_index_segment(self, segment_id, headers):
        return self._request("GET", f"/index-segments/{segment_id}", headers=headers)

    # ─── Crediting events ─────────────────────────────────────────────────
    def create_crediting_event(self, payload, headers):
        return self._request("POST", "/crediting-events", payload, headers)

    def list_crediting_events(self, headers, params=None):
        return self._request("GET", "/crediting-events", headers=headers, params=params)

    def get_crediting_event(self, event_id, headers):
        return self._request("GET", f"/crediting-events/{event_id}", headers=headers)

    # ─── Withdrawals ──────────────────────────────────────────────────────
    def create_withdrawal(self, payload, headers):
        return self._request("POST", "/withdrawals", payload, headers)

    def get_withdrawal(self, withdrawal_id, headers):
        return self._request("GET", f"/withdrawals/{withdrawal_id}", headers=headers)

    def settle_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/withdrawals/{withdrawal_id}/settle", {}, headers)

    def reject_withdrawal(self, withdrawal_id, headers):
        return self._request("POST", f"/withdrawals/{withdrawal_id}/reject", {}, headers)

    # ─── Beneficiaries ────────────────────────────────────────────────────
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, beneficiary_id, headers):
        return self._request("GET", f"/beneficiaries/{beneficiary_id}", headers=headers)

    def revoke_beneficiary(self, beneficiary_id, headers):
        return self._request("POST", f"/beneficiaries/{beneficiary_id}/revoke", {}, headers)

    # ─── Annuitizations ───────────────────────────────────────────────────
    def create_annuitization(self, payload, headers):
        return self._request("POST", "/annuitizations", payload, headers)

    def get_annuitization(self, annuitization_id, headers):
        return self._request("GET", f"/annuitizations/{annuitization_id}", headers=headers)

    def begin_payout(self, annuitization_id, headers):
        return self._request(
            "POST", f"/annuitizations/{annuitization_id}/begin-payout", {}, headers
        )

    def decline_annuitization(self, annuitization_id, headers):
        return self._request(
            "POST", f"/annuitizations/{annuitization_id}/decline", {}, headers
        )

    # ─── Death claims ─────────────────────────────────────────────────────
    def create_death_claim(self, payload, headers):
        return self._request("POST", "/death-claims", payload, headers)

    def get_death_claim(self, claim_id, headers):
        return self._request("GET", f"/death-claims/{claim_id}", headers=headers)

    def verify_identity(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/verify-identity", {}, headers)

    def value_benefit(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/value-benefit", {}, headers)

    def fund_death_claim(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/fund", {}, headers)

    def deny_death_claim(self, claim_id, headers):
        return self._request("POST", f"/death-claims/{claim_id}/deny", {}, headers)

    # ─── 1035 exchanges ───────────────────────────────────────────────────
    def create_exchange(self, payload, headers):
        return self._request("POST", "/exchanges-1035", payload, headers)

    def list_exchanges(self, headers, params=None):
        return self._request("GET", "/exchanges-1035", headers=headers, params=params)

    def get_exchange(self, exchange_id, headers):
        return self._request("GET", f"/exchanges-1035/{exchange_id}", headers=headers)

    def submit_exchange(self, exchange_id, headers):
        return self._request("POST", f"/exchanges-1035/{exchange_id}/submit", {}, headers)

    def request_revision_exchange(self, exchange_id, headers):
        return self._request(
            "POST", f"/exchanges-1035/{exchange_id}/request-revision", {}, headers
        )

    def approve_exchange(self, exchange_id, payload, headers):
        return self._request("POST", f"/exchanges-1035/{exchange_id}/approve", payload, headers)

    def reject_exchange(self, exchange_id, headers):
        return self._request("POST", f"/exchanges-1035/{exchange_id}/reject", {}, headers)

    def settle_exchange(self, exchange_id, headers):
        return self._request("POST", f"/exchanges-1035/{exchange_id}/settle", {}, headers)

    # ─── Test-driving clock endpoints ─────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def roll_anniversary(self, contract_id, headers):
        return self._request(
            "POST", "/_clock/roll_anniversary", {"contract_id": contract_id}, headers
        )


api_client = ApiClient()
