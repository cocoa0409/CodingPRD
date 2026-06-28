"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Exchanger ────────────────────────────────────────────────────
    def create_exchanger(self, payload, headers):
        return self._request("POST", "/exchangers", payload, headers)

    def get_exchanger(self, exchanger_id, headers):
        return self._request("GET", f"/exchangers/{exchanger_id}", headers=headers)

    # ── Exchange ─────────────────────────────────────────────────────
    def create_exchange(self, payload, headers):
        return self._request("POST", "/exchanges", payload, headers)

    def get_exchange(self, exchange_id, headers):
        return self._request("GET", f"/exchanges/{exchange_id}", headers=headers)

    def list_exchanges(self, headers, params=None):
        return self._request("GET", "/exchanges", headers=headers, params=params)

    def create_relinquished_property(self, exchange_id, payload, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/relinquished-properties", payload, headers)

    def list_relinquished_properties(self, exchange_id, headers, params=None):
        return self._request("GET", f"/exchanges/{exchange_id}/relinquished-properties", headers=headers, params=params)

    def create_trust(self, exchange_id, headers, payload=None):
        return self._request("POST", f"/exchanges/{exchange_id}/trust", payload if payload is not None else {}, headers)

    def list_trust(self, exchange_id, headers, params=None):
        return self._request("GET", f"/exchanges/{exchange_id}/trust", headers=headers, params=params)

    def close_relinquished(self, exchange_id, headers, payload=None):
        return self._request("POST", f"/exchanges/{exchange_id}/close-relinquished", payload if payload is not None else {}, headers)

    def create_replacement_property(self, exchange_id, payload, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/replacement-properties", payload, headers)

    def list_exchange_replacement_properties(self, exchange_id, headers, params=None):
        return self._request("GET", f"/exchanges/{exchange_id}/replacement-properties", headers=headers, params=params)

    def get_replacement_property(self, replacement_property_id, headers):
        return self._request("GET", f"/replacement-properties/{replacement_property_id}", headers=headers)

    def list_replacement_properties(self, headers, params=None):
        return self._request("GET", "/replacement-properties", headers=headers, params=params)

    def complete_exchange(self, exchange_id, headers, payload=None):
        return self._request("POST", f"/exchanges/{exchange_id}/complete", payload if payload is not None else {}, headers)

    def fail_exchange(self, exchange_id, headers, payload=None):
        return self._request("POST", f"/exchanges/{exchange_id}/fail", payload if payload is not None else {}, headers)

    def terminate_exchange(self, exchange_id, headers, payload=None):
        return self._request("POST", f"/exchanges/{exchange_id}/terminate", payload if payload is not None else {}, headers)

    # ── Identification ───────────────────────────────────────────────
    def create_identification(self, exchange_id, payload, headers):
        return self._request("POST", f"/exchanges/{exchange_id}/identifications", payload, headers)

    def list_identifications(self, exchange_id, headers, params=None):
        return self._request("GET", f"/exchanges/{exchange_id}/identifications", headers=headers, params=params)

    def get_identification(self, identification_id, headers):
        return self._request("GET", f"/identifications/{identification_id}", headers=headers)

    def add_candidate(self, identification_id, payload, headers):
        return self._request("POST", f"/identifications/{identification_id}/candidates", payload, headers)

    def list_candidates(self, identification_id, headers, params=None):
        return self._request("GET", f"/identifications/{identification_id}/candidates", headers=headers, params=params)

    def finalize_identification(self, identification_id, headers, payload=None):
        return self._request("POST", f"/identifications/{identification_id}/finalize", payload if payload is not None else {}, headers)

    def revoke_identification(self, identification_id, headers, payload=None):
        return self._request("POST", f"/identifications/{identification_id}/revoke", payload if payload is not None else {}, headers)

    # ── Disbursement ─────────────────────────────────────────────────
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/disbursements", payload, headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def approve_disbursement(self, disbursement_id, headers, payload=None):
        return self._request("POST", f"/disbursements/{disbursement_id}/approve", payload if payload is not None else {}, headers)

    def void_disbursement(self, disbursement_id, headers, payload=None):
        return self._request("POST", f"/disbursements/{disbursement_id}/void", payload if payload is not None else {}, headers)

    # ── Test-driving clock ───────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
