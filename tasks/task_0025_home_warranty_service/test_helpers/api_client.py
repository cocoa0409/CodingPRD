"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── ContractPackage (PRD §3.1, §4) ──────────────────────────
    def create_contract_package(self, payload, headers):
        return self._request("POST", "/contract-packages", payload, headers)

    def get_contract_package(self, package_id, headers):
        return self._request("GET", f"/contract-packages/{package_id}", headers=headers)

    def list_contract_packages(self, headers, params=None):
        return self._request("GET", "/contract-packages", headers=headers, params=params)

    def retire_contract_package(self, package_id, headers, payload=None):
        return self._request(
            "POST",
            f"/contract-packages/{package_id}/retire",
            payload if payload is not None else {},
            headers,
        )

    # ─── Customer (PRD §3.1, §4) ─────────────────────────────────
    def register_customer(self, payload, headers=None):
        return self._request(
            "POST", "/customers", payload, headers if headers is not None else {}
        )

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ─── Contract (PRD §3.2, §3.8, §4) ───────────────────────────
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def activate_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"/contracts/{contract_id}/activate",
            payload if payload is not None else {},
            headers,
        )

    def renew_contract(self, contract_id, payload, headers):
        return self._request(
            "POST", f"/contracts/{contract_id}/renew", payload, headers
        )

    def cancel_contract(self, contract_id, headers, payload=None):
        return self._request(
            "POST",
            f"/contracts/{contract_id}/cancel",
            payload if payload is not None else {},
            headers,
        )

    def list_renewal_reminders(self, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/contracts/{contract_id}/renewal-reminders",
            headers=headers,
            params=params,
        )

    # ─── CoveredItem (PRD §3.3, §4) ──────────────────────────────
    def create_covered_item(self, payload, headers):
        return self._request("POST", "/covered-items", payload, headers)

    def get_covered_item(self, item_id, headers):
        return self._request("GET", f"/covered-items/{item_id}", headers=headers)

    def list_covered_items(self, headers, params=None):
        return self._request("GET", "/covered-items", headers=headers, params=params)

    # ─── ClaimTicket (PRD §3.4–§3.6, §4) ─────────────────────────
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def assess_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/assess", payload, headers)

    def reject_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reject", payload, headers)

    def dispatch_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/dispatch", payload, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/resolve", payload, headers)

    def reopen_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST",
            f"/claims/{claim_id}/reopen",
            payload if payload is not None else {},
            headers,
        )

    # ─── Dispatch (PRD §3.5, §4) ─────────────────────────────────
    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/dispatches", headers=headers, params=params)

    def start_dispatch(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dispatches/{dispatch_id}/start",
            payload if payload is not None else {},
            headers,
        )

    def complete_dispatch(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dispatches/{dispatch_id}/complete",
            payload if payload is not None else {},
            headers,
        )

    def mark_return_needed(self, dispatch_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dispatches/{dispatch_id}/mark-return-needed",
            payload if payload is not None else {},
            headers,
        )

    # ─── Test-driving (PRD §3.9) ─────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def tick_clock(self, headers, payload=None):
        return self._request(
            "POST",
            "/_clock/tick",
            payload if payload is not None else {},
            headers,
        )


api_client = ApiClient()
