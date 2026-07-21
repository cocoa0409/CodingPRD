"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    # ---- CensusMember ----
    def create_census_member(self, payload, headers):
        return self._request("POST", "/census-members", payload, headers)

    def get_census_member(self, member_id, headers):
        return self._request("GET", f"/census-members/{member_id}", headers=headers)

    def list_census_members(self, headers, params=None):
        return self._request("GET", "/census-members", headers=headers, params=params)

    def terminate_census_member(self, member_id, headers):
        return self._request("POST", f"/census-members/{member_id}/terminate", {}, headers)

    # ---- MarketingCampaign ----
    def create_campaign(self, payload, headers):
        return self._request("POST", "/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/campaigns/{campaign_id}", headers=headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", "/campaigns", headers=headers, params=params)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/campaigns/{campaign_id}/open", {}, headers)

    # ---- CarrierQuote ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def select_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/select", {}, headers)

    # ---- Policy ----
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def activate_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/activate", {}, headers)

    def terminate_policy(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/terminate", {}, headers)

    def finalize_commission(self, policy_id, headers):
        return self._request("POST", f"/policies/{policy_id}/finalize-commission", {}, headers)

    # ---- Renewal ----
    def create_renewal(self, payload, headers):
        return self._request("POST", "/renewals", payload, headers)

    def get_renewal(self, renewal_id, headers):
        return self._request("GET", f"/renewals/{renewal_id}", headers=headers)

    def list_renewals(self, headers, params=None):
        return self._request("GET", "/renewals", headers=headers, params=params)

    def counter_renewal(self, renewal_id, payload, headers):
        return self._request("POST", f"/renewals/{renewal_id}/counter", payload, headers)

    def settle_renewal(self, renewal_id, payload, headers):
        return self._request("POST", f"/renewals/{renewal_id}/settle", payload, headers)

    # ---- EnrollmentWindow ----
    def create_enrollment_window(self, payload, headers):
        return self._request("POST", "/enrollment-windows", payload, headers)

    def get_enrollment_window(self, window_id, headers):
        return self._request("GET", f"/enrollment-windows/{window_id}", headers=headers)

    def list_enrollment_windows(self, headers, params=None):
        return self._request("GET", "/enrollment-windows", headers=headers, params=params)

    def open_window(self, window_id, headers):
        return self._request("POST", f"/enrollment-windows/{window_id}/open", {}, headers)

    def finalize_window(self, window_id, headers):
        return self._request("POST", f"/enrollment-windows/{window_id}/finalize", {}, headers)

    # ---- Election ----
    def create_election(self, payload, headers):
        return self._request("POST", "/elections", payload, headers)

    def get_election(self, election_id, headers):
        return self._request("GET", f"/elections/{election_id}", headers=headers)

    def list_elections(self, headers, params=None):
        return self._request("GET", "/elections", headers=headers, params=params)

    def confirm_election(self, election_id, headers):
        return self._request("POST", f"/elections/{election_id}/confirm", {}, headers)

    def waive_election(self, election_id, headers):
        return self._request("POST", f"/elections/{election_id}/waive", {}, headers)

    def withdraw_election(self, election_id, headers):
        return self._request("POST", f"/elections/{election_id}/withdraw", {}, headers)

    # ---- ComplianceFiling ----
    def create_filing(self, payload, headers):
        return self._request("POST", "/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/filings", headers=headers, params=params)

    def prepare_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/prepare", {}, headers)

    def certify_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/certify", {}, headers)

    def file_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/file", {}, headers)

    # ---- StopLossPolicy ----
    def create_stop_loss_policy(self, payload, headers):
        return self._request("POST", "/stop-loss-policies", payload, headers)

    def get_stop_loss_policy(self, sl_id, headers):
        return self._request("GET", f"/stop-loss-policies/{sl_id}", headers=headers)

    def list_stop_loss_policies(self, headers, params=None):
        return self._request("GET", "/stop-loss-policies", headers=headers, params=params)

    def record_claim(self, sl_id, payload, headers):
        return self._request("POST", f"/stop-loss-policies/{sl_id}/record-claim", payload, headers)

    # ---- Test-driving: logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
