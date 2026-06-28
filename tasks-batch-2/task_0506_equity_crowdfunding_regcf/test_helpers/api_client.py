"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.9) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # --- Issuer ---
    def create_issuer(self, payload, headers):
        return self._request("POST", "/issuers", payload, headers=headers)

    def get_issuer(self, issuer_id, headers):
        return self._request("GET", f"/issuers/{issuer_id}", headers=headers)

    def list_issuers(self, headers, params=None):
        return self._request("GET", "/issuers", headers=headers, params=params)

    def verify_issuer(self, issuer_id, headers):
        return self._request("POST", f"/issuers/{issuer_id}/verify", headers=headers)

    def bar_issuer(self, issuer_id, headers):
        return self._request("POST", f"/issuers/{issuer_id}/bar", headers=headers)

    # --- Offering + Form C ---
    def create_offering(self, payload, headers):
        return self._request("POST", "/offerings", payload, headers=headers)

    def get_offering(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}", headers=headers)

    def list_offerings(self, headers, params=None):
        return self._request("GET", "/offerings", headers=headers, params=params)

    def submit_form_c(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/form-c/submit", headers=headers)

    def qualify_form_c(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/form-c/qualify", headers=headers)

    def reject_form_c(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/form-c/reject", headers=headers)

    def amend_form_c(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/form-c/amend", headers=headers)

    def go_live(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/go-live", headers=headers)

    def rolling_close(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/rolling-close", headers=headers)

    def close_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/close", headers=headers)

    def cancel_offering(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/cancel", headers=headers)

    def enable_secondary(self, offering_id, headers):
        return self._request("POST", f"/offerings/{offering_id}/enable-secondary", headers=headers)

    def get_escrow(self, offering_id, headers):
        return self._request("GET", f"/offerings/{offering_id}/escrow", headers=headers)

    def get_cap_table(self, offering_id, headers, params=None):
        return self._request("GET", f"/offerings/{offering_id}/cap-table", headers=headers, params=params)

    def get_cap_table_entry(self, entry_id, headers):
        return self._request("GET", f"/cap-table-entries/{entry_id}", headers=headers)

    def list_cap_table_entries(self, headers, params=None):
        return self._request("GET", "/cap-table-entries", headers=headers, params=params)

    # --- Investor + accreditation ---
    def create_investor(self, payload, headers):
        return self._request("POST", "/investors", payload, headers=headers)

    def get_investor(self, investor_id, headers):
        return self._request("GET", f"/investors/{investor_id}", headers=headers)

    def create_accreditation_request(self, payload, headers):
        return self._request("POST", "/accreditation-requests", payload, headers=headers)

    def get_accreditation_request(self, request_id, headers):
        return self._request("GET", f"/accreditation-requests/{request_id}", headers=headers)

    def list_accreditation_requests(self, headers, params=None):
        return self._request("GET", "/accreditation-requests", headers=headers, params=params)

    def approve_accreditation_request(self, request_id, headers):
        return self._request("POST", f"/accreditation-requests/{request_id}/approve", headers=headers)

    def deny_accreditation_request(self, request_id, headers):
        return self._request("POST", f"/accreditation-requests/{request_id}/deny", headers=headers)

    # --- Investment ---
    def create_investment(self, payload, headers):
        return self._request("POST", "/investments", payload, headers=headers)

    def get_investment(self, investment_id, headers):
        return self._request("GET", f"/investments/{investment_id}", headers=headers)

    def list_investments(self, headers, params=None):
        return self._request("GET", "/investments", headers=headers, params=params)

    def reconfirm_investment(self, investment_id, headers):
        return self._request("POST", f"/investments/{investment_id}/reconfirm", headers=headers)

    def withdraw_investment(self, investment_id, headers):
        return self._request("POST", f"/investments/{investment_id}/withdraw", headers=headers)

    # --- Investor updates ---
    def create_investor_update(self, payload, headers):
        return self._request("POST", "/investor-updates", payload, headers=headers)

    def get_investor_update(self, update_id, headers):
        return self._request("GET", f"/investor-updates/{update_id}", headers=headers)

    def list_investor_updates(self, headers, params=None):
        return self._request("GET", "/investor-updates", headers=headers, params=params)

    def publish_investor_update(self, update_id, headers):
        return self._request("POST", f"/investor-updates/{update_id}/publish", headers=headers)


api_client = ApiClient()
