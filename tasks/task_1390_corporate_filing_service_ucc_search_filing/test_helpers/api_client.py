"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Client accounts ---
    def create_client_account(self, payload, headers):
        return self._request("POST", "/client-accounts", payload, headers)

    def list_client_accounts(self, headers, params=None):
        return self._request("GET", "/client-accounts", headers=headers, params=params)

    def get_client_account(self, client_id, headers):
        return self._request("GET", f"/client-accounts/{client_id}", headers=headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/client-accounts/{client_id}/suspend", {}, headers)

    def reinstate_client(self, client_id, headers):
        return self._request("POST", f"/client-accounts/{client_id}/reinstate", {}, headers)

    # --- Jurisdiction profiles ---
    def create_jurisdiction_profile(self, payload, headers):
        return self._request("POST", "/jurisdiction-profiles", payload, headers)

    def list_jurisdiction_profiles(self, headers, params=None):
        return self._request("GET", "/jurisdiction-profiles", headers=headers, params=params)

    def get_jurisdiction_profile(self, profile_id, headers):
        return self._request("GET", f"/jurisdiction-profiles/{profile_id}", headers=headers)

    def update_jurisdiction_profile(self, profile_id, payload, headers):
        return self._request("PUT", f"/jurisdiction-profiles/{profile_id}", payload, headers)

    # --- Debtors ---
    def create_debtor(self, client_id, payload, headers):
        return self._request("POST", f"/client-accounts/{client_id}/debtors", payload, headers)

    def list_debtors(self, client_id, headers, params=None):
        return self._request("GET", f"/client-accounts/{client_id}/debtors", headers=headers, params=params)

    def get_debtor(self, debtor_id, headers):
        return self._request("GET", f"/debtors/{debtor_id}", headers=headers)

    def update_debtor(self, debtor_id, payload, headers):
        return self._request("PATCH", f"/debtors/{debtor_id}", payload, headers)

    # --- Secured parties ---
    def create_secured_party(self, client_id, payload, headers):
        return self._request("POST", f"/client-accounts/{client_id}/secured-parties", payload, headers)

    def list_secured_parties(self, client_id, headers, params=None):
        return self._request("GET", f"/client-accounts/{client_id}/secured-parties", headers=headers, params=params)

    def get_secured_party(self, secured_party_id, headers):
        return self._request("GET", f"/secured-parties/{secured_party_id}", headers=headers)

    # --- Filing requests ---
    def create_filing_request(self, payload, headers):
        return self._request("POST", "/filing-requests", payload, headers)

    def list_filing_requests(self, headers, params=None):
        return self._request("GET", "/filing-requests", headers=headers, params=params)

    def get_filing_request(self, request_id, headers):
        return self._request("GET", f"/filing-requests/{request_id}", headers=headers)

    def patch_filing_request(self, request_id, payload, headers):
        return self._request("PATCH", f"/filing-requests/{request_id}", payload, headers)

    def submit_intake(self, request_id, headers):
        return self._request("POST", f"/filing-requests/{request_id}/submit-intake", {}, headers)

    def approve_preparation(self, request_id, headers):
        return self._request("POST", f"/filing-requests/{request_id}/approve-preparation", {}, headers)

    def cancel_filing_request(self, request_id, headers):
        return self._request("POST", f"/filing-requests/{request_id}/cancel", {}, headers)

    # --- Filing attempts (UCC filings) ---
    def create_attempt(self, request_id, payload, headers):
        return self._request("POST", f"/filing-requests/{request_id}/attempts", payload, headers)

    def list_attempts(self, request_id, headers, params=None):
        return self._request("GET", f"/filing-requests/{request_id}/attempts", headers=headers, params=params)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/filings", headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def name_check_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}/name-check", headers=headers)

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/submit", {}, headers)

    def record_acceptance(self, filing_id, payload, headers):
        return self._request("POST", f"/filings/{filing_id}/record-acceptance", payload, headers)

    def record_rejection(self, filing_id, payload, headers):
        return self._request("POST", f"/filings/{filing_id}/record-rejection", payload, headers)

    def withdraw_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/withdraw", {}, headers)

    def list_filing_events(self, filing_id, headers, params=None):
        return self._request("GET", f"/filings/{filing_id}/events", headers=headers, params=params)

    # --- Lien searches ---
    def create_lien_search(self, payload, headers):
        return self._request("POST", "/lien-searches", payload, headers)

    def list_lien_searches(self, headers, params=None):
        return self._request("GET", "/lien-searches", headers=headers, params=params)

    def get_lien_search(self, search_id, headers):
        return self._request("GET", f"/lien-searches/{search_id}", headers=headers)

    def record_search_results(self, search_id, payload, headers):
        return self._request("POST", f"/lien-searches/{search_id}/record-results", payload, headers)

    def list_search_hits(self, search_id, headers, params=None):
        return self._request("GET", f"/lien-searches/{search_id}/hits", headers=headers, params=params)

    # --- Perfection reports ---
    def create_perfection_report(self, client_id, payload, headers):
        return self._request("POST", f"/client-accounts/{client_id}/perfection-reports", payload, headers)

    def list_perfection_reports(self, client_id, headers, params=None):
        return self._request("GET", f"/client-accounts/{client_id}/perfection-reports", headers=headers, params=params)

    def get_perfection_report(self, report_id, headers):
        return self._request("GET", f"/perfection-reports/{report_id}", headers=headers)


api_client = ApiClient()
# Per-test-server isolation kills and respawns the API on the same port before
# every test. A keep-alive connection pooled from the previous server process
# would be reused by the next test's first request and surface as a spurious
# ConnectionResetError/RemoteDisconnected. Closing every response keeps the
# pool empty across restarts. Transport-level only; no API semantics change.
api_client.session.headers["Connection"] = "close"
