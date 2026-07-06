"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Estate ---
    def create_estate(self, payload, headers):
        return self._request("POST", "/estates", payload, headers)

    def get_estate(self, estate_id, headers):
        return self._request("GET", f"/estates/{estate_id}", headers=headers)

    def list_estates(self, headers, params=None):
        return self._request("GET", "/estates", headers=headers, params=params)

    # --- Petition ---
    def create_petition(self, payload, headers):
        return self._request("POST", "/petitions", payload, headers)

    def get_petition(self, petition_id, headers):
        return self._request("GET", f"/petitions/{petition_id}", headers=headers)

    def list_petitions(self, headers, params=None):
        return self._request("GET", "/petitions", headers=headers, params=params)

    def grant_petition(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/petitions/{petition_id}/grant", payload, headers
        )

    def deny_petition(self, petition_id, payload, headers):
        return self._request(
            "POST", f"/petitions/{petition_id}/deny", payload, headers
        )

    # --- PersonalRepresentative ---
    def create_representative(self, payload, headers):
        return self._request("POST", "/representatives", payload, headers)

    def get_representative(self, rep_id, headers):
        return self._request("GET", f"/representatives/{rep_id}", headers=headers)

    def list_representatives(self, headers, params=None):
        return self._request(
            "GET", "/representatives", headers=headers, params=params
        )

    def appoint_representative(self, rep_id, payload, headers):
        return self._request(
            "POST", f"/representatives/{rep_id}/appoint", payload, headers
        )

    def suspend_representative(self, rep_id, payload, headers):
        return self._request(
            "POST", f"/representatives/{rep_id}/suspend", payload, headers
        )

    def reinstate_representative(self, rep_id, payload, headers):
        return self._request(
            "POST", f"/representatives/{rep_id}/reinstate", payload, headers
        )

    def remove_representative(self, rep_id, payload, headers):
        return self._request(
            "POST", f"/representatives/{rep_id}/remove", payload, headers
        )

    def discharge_representative(self, rep_id, payload, headers):
        return self._request(
            "POST", f"/representatives/{rep_id}/discharge", payload, headers
        )

    # --- Bond ---
    def create_bond(self, payload, headers):
        return self._request("POST", "/bonds", payload, headers)

    def get_bond(self, bond_id, headers):
        return self._request("GET", f"/bonds/{bond_id}", headers=headers)

    def list_bonds(self, headers, params=None):
        return self._request("GET", "/bonds", headers=headers, params=params)

    def approve_bond(self, bond_id, payload, headers):
        return self._request("POST", f"/bonds/{bond_id}/approve", payload, headers)

    # --- Beneficiary ---
    def create_beneficiary(self, payload, headers):
        return self._request("POST", "/beneficiaries", payload, headers)

    def get_beneficiary(self, ben_id, headers):
        return self._request("GET", f"/beneficiaries/{ben_id}", headers=headers)

    def list_beneficiaries(self, headers, params=None):
        return self._request("GET", "/beneficiaries", headers=headers, params=params)

    # --- CreditorClaim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def allow_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/allow", payload, headers)

    def reject_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/reject", payload, headers)

    def pay_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/pay", payload, headers)

    # --- Asset ---
    def create_asset(self, payload, headers):
        return self._request("POST", "/assets", payload, headers)

    def get_asset(self, asset_id, headers):
        return self._request("GET", f"/assets/{asset_id}", headers=headers)

    def list_assets(self, headers, params=None):
        return self._request("GET", "/assets", headers=headers, params=params)

    def appraise_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/appraise", payload, headers)

    def marshal_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/assets/{asset_id}/marshal", payload, headers)

    def liquidate_asset(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/liquidate", payload, headers
        )

    def distribute_asset_in_kind(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/assets/{asset_id}/distribute-in-kind", payload, headers
        )

    # --- Distribution ---
    def create_distribution(self, payload, headers):
        return self._request("POST", "/distributions", payload, headers)

    def get_distribution(self, dist_id, headers):
        return self._request("GET", f"/distributions/{dist_id}", headers=headers)

    def list_distributions(self, headers, params=None):
        return self._request(
            "GET", "/distributions", headers=headers, params=params
        )

    def approve_distribution(self, dist_id, payload, headers):
        return self._request(
            "POST", f"/distributions/{dist_id}/approve", payload, headers
        )

    def pay_distribution(self, dist_id, payload, headers):
        return self._request(
            "POST", f"/distributions/{dist_id}/pay", payload, headers
        )

    def return_distribution(self, dist_id, payload, headers):
        return self._request(
            "POST", f"/distributions/{dist_id}/return", payload, headers
        )

    # --- AccountingReport ---
    def create_accounting(self, payload, headers):
        return self._request("POST", "/accountings", payload, headers)

    def get_accounting(self, acct_id, headers):
        return self._request("GET", f"/accountings/{acct_id}", headers=headers)

    def list_accountings(self, headers, params=None):
        return self._request("GET", "/accountings", headers=headers, params=params)

    def file_accounting(self, acct_id, payload, headers):
        return self._request(
            "POST", f"/accountings/{acct_id}/file", payload, headers
        )

    def approve_accounting(self, acct_id, payload, headers):
        return self._request(
            "POST", f"/accountings/{acct_id}/approve", payload, headers
        )

    def reject_accounting(self, acct_id, payload, headers):
        return self._request(
            "POST", f"/accountings/{acct_id}/reject", payload, headers
        )

    # --- Hearing ---
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def hold_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/hold", payload, headers
        )

    def vacate_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/vacate", payload, headers
        )


api_client = ApiClient()
