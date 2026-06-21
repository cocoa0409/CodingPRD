"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; only PRD-specific endpoint
methods are defined here. The base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- Corridors ----
    def create_corridor(self, payload, headers):
        return self._request("POST", "/corridors", payload, headers)

    def get_corridor(self, corridor_id, headers):
        return self._request("GET", f"/corridors/{corridor_id}", headers=headers)

    def list_corridors(self, headers, params=None):
        return self._request("GET", "/corridors", headers=headers, params=params)

    def suspend_corridor(self, corridor_id, headers):
        return self._request("POST", f"/corridors/{corridor_id}/suspend", headers=headers)

    # ---- FX rates ----
    def create_fx_rate(self, payload, headers):
        return self._request("POST", "/fx-rates", payload, headers)

    def get_fx_rate(self, fx_rate_id, headers):
        return self._request("GET", f"/fx-rates/{fx_rate_id}", headers=headers)

    def list_fx_rates(self, headers, params=None):
        return self._request("GET", "/fx-rates", headers=headers, params=params)

    # ---- Senders ----
    def create_sender(self, payload, headers):
        return self._request("POST", "/senders", payload, headers)

    def get_sender(self, sender_id, headers):
        return self._request("GET", f"/senders/{sender_id}", headers=headers)

    def list_senders(self, headers, params=None):
        return self._request("GET", "/senders", headers=headers, params=params)

    def verify_sender_kyc(self, sender_id, payload, headers):
        return self._request("POST", f"/senders/{sender_id}/verify-kyc", payload, headers)

    # ---- Recipients ----
    def create_recipient(self, payload, headers):
        return self._request("POST", "/recipients", payload, headers)

    def get_recipient(self, recipient_id, headers):
        return self._request("GET", f"/recipients/{recipient_id}", headers=headers)

    def list_recipients(self, headers, params=None):
        return self._request("GET", "/recipients", headers=headers, params=params)

    def submit_recipient_kyc(self, recipient_id, payload, headers):
        return self._request("POST", f"/recipients/{recipient_id}/submit-kyc", payload, headers)

    def decide_recipient_kyc(self, recipient_id, payload, headers):
        return self._request("POST", f"/recipients/{recipient_id}/decide-kyc", payload, headers)

    # ---- Quotes ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def lock_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/lock", headers=headers)

    # ---- Transfers ----
    def create_transfer(self, payload, headers):
        return self._request("POST", "/transfers", payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/transfers/{transfer_id}", headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/transfers", headers=headers, params=params)

    def fund_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/fund", headers=headers)

    def screen_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/screen", headers=headers)

    def dispatch_transfer(self, transfer_id, headers):
        return self._request("POST", f"/transfers/{transfer_id}/dispatch", headers=headers)

    # ---- Compliance cases ----
    def get_compliance_case(self, case_id, headers):
        return self._request("GET", f"/compliance-cases/{case_id}", headers=headers)

    def list_compliance_cases(self, headers, params=None):
        return self._request("GET", "/compliance-cases", headers=headers, params=params)

    def request_info_compliance_case(self, case_id, headers, payload=None):
        return self._request("POST", f"/compliance-cases/{case_id}/request-info",
                             payload if payload is not None else {}, headers)

    def provide_info_compliance_case(self, case_id, payload, headers):
        return self._request("POST", f"/compliance-cases/{case_id}/provide-info", payload, headers)

    def escalate_compliance_case(self, case_id, headers):
        return self._request("POST", f"/compliance-cases/{case_id}/escalate", headers=headers)

    def decide_compliance_case(self, case_id, payload, headers):
        return self._request("POST", f"/compliance-cases/{case_id}/decide", payload, headers)

    # ---- Sanctions list ----
    def create_sanctions_list_entry(self, payload, headers):
        return self._request("POST", "/sanctions-list", payload, headers)

    def get_sanctions_list_entry(self, list_entry_id, headers):
        return self._request("GET", f"/sanctions-list/{list_entry_id}", headers=headers)

    def list_sanctions_list_entries(self, headers, params=None):
        return self._request("GET", "/sanctions-list", headers=headers, params=params)

    # ---- Sanctions hits ----
    def get_sanctions_hit(self, hit_id, headers):
        return self._request("GET", f"/sanctions-hits/{hit_id}", headers=headers)

    def list_sanctions_hits(self, headers, params=None):
        return self._request("GET", "/sanctions-hits", headers=headers, params=params)

    # ---- Payout attempts ----
    def get_payout_attempt(self, attempt_id, headers):
        return self._request("GET", f"/payout-attempts/{attempt_id}", headers=headers)

    def list_payout_attempts(self, headers, params=None):
        return self._request("GET", "/payout-attempts", headers=headers, params=params)

    def report_payout_outcome(self, attempt_id, payload, headers):
        return self._request("POST", f"/payout-attempts/{attempt_id}/report-outcome", payload, headers)

    # ---- Refunds ----
    def create_refund(self, payload, headers):
        return self._request("POST", "/refunds", payload, headers)

    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", headers=headers, params=params)

    # ---- Ledger entries ----
    def get_ledger_entry(self, ledger_entry_id, headers):
        return self._request("GET", f"/ledger-entries/{ledger_entry_id}", headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/ledger-entries", headers=headers, params=params)

    # ---- Logical clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def advance_clock(self, payload, headers):
        return self._request("POST", "/_clock/advance", payload, headers)


api_client = ApiClient()
