"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Drug catalog (PRD §3.1)
    # ------------------------------------------------------------------
    def create_drug(self, payload, headers):
        return self._request("POST", "/api/drugs", payload, headers)

    def list_drugs(self, headers, params=None):
        return self._request("GET", "/api/drugs", headers=headers, params=params)

    def get_drug(self, drug_id, headers):
        return self._request("GET", f"/api/drugs/{drug_id}", headers=headers)

    # ------------------------------------------------------------------
    # ASP rate schedules (PRD §3.3)
    # ------------------------------------------------------------------
    def create_asp_schedule(self, payload, headers):
        return self._request("POST", "/api/asp-schedules", payload, headers)

    def list_asp_schedules(self, headers, params=None):
        return self._request("GET", "/api/asp-schedules", headers=headers, params=params)

    def get_asp_schedule(self, schedule_id, headers):
        return self._request(
            "GET", f"/api/asp-schedules/{schedule_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Clinical policies (PRD §3.2)
    # ------------------------------------------------------------------
    def create_clinical_policy(self, payload, headers):
        return self._request("POST", "/api/clinical-policies", payload, headers)

    def list_clinical_policies(self, headers, params=None):
        return self._request(
            "GET", "/api/clinical-policies", headers=headers, params=params
        )

    def get_clinical_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/api/clinical-policies/{policy_id}", headers=headers
        )

    def activate_clinical_policy(self, policy_id, payload, headers):
        return self._request(
            "POST",
            f"/api/clinical-policies/{policy_id}/activate",
            payload,
            headers,
        )

    # ------------------------------------------------------------------
    # Provider accounts (PRD §2.10, §3.3)
    # ------------------------------------------------------------------
    def create_provider_account(self, payload, headers):
        return self._request("POST", "/api/provider-accounts", payload, headers)

    def list_provider_accounts(self, headers, params=None):
        return self._request(
            "GET", "/api/provider-accounts", headers=headers, params=params
        )

    def get_provider_account(self, account_id, headers):
        return self._request(
            "GET", f"/api/provider-accounts/{account_id}", headers=headers
        )

    def settle_recoupment(self, account_id, headers):
        return self._request(
            "POST",
            f"/api/provider-accounts/{account_id}/settle-recoupment",
            {},
            headers,
        )

    # ------------------------------------------------------------------
    # Prior authorizations (PRD §3.4)
    # ------------------------------------------------------------------
    def create_prior_authorization(self, payload, headers):
        return self._request("POST", "/api/prior-authorizations", payload, headers)

    def list_prior_authorizations(self, headers, params=None):
        return self._request(
            "GET", "/api/prior-authorizations", headers=headers, params=params
        )

    def get_prior_authorization(self, auth_id, headers):
        return self._request(
            "GET", f"/api/prior-authorizations/{auth_id}", headers=headers
        )

    def approve_auth(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/api/prior-authorizations/{auth_id}/approve", payload, headers
        )

    def deny_auth(self, auth_id, payload, headers):
        return self._request(
            "POST", f"/api/prior-authorizations/{auth_id}/deny", payload, headers
        )

    def suspend_auth(self, auth_id, headers):
        return self._request(
            "POST", f"/api/prior-authorizations/{auth_id}/suspend", {}, headers
        )

    def reinstate_auth(self, auth_id, headers):
        return self._request(
            "POST", f"/api/prior-authorizations/{auth_id}/reinstate", {}, headers
        )

    def cancel_auth(self, auth_id, headers):
        return self._request(
            "POST", f"/api/prior-authorizations/{auth_id}/cancel", {}, headers
        )

    # ------------------------------------------------------------------
    # Infusion claims (PRD §3.6)
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/api/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/api/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/api/claims/{claim_id}", headers=headers)

    def override_approve_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/api/claims/{claim_id}/override-approve", {}, headers
        )

    def deny_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/api/claims/{claim_id}/deny", payload, headers
        )

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/api/claims/{claim_id}/pay", {}, headers)

    # ------------------------------------------------------------------
    # Claim adjustments (read-only repricing log, PRD §3.3)
    # ------------------------------------------------------------------
    def list_claim_adjustments(self, headers, params=None):
        return self._request(
            "GET", "/api/claim-adjustments", headers=headers, params=params
        )

    def get_claim_adjustment(self, adjustment_id, headers):
        return self._request(
            "GET", f"/api/claim-adjustments/{adjustment_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Site-of-care redirections (PRD §3.5)
    # ------------------------------------------------------------------
    def list_redirections(self, headers, params=None):
        return self._request("GET", "/api/redirections", headers=headers, params=params)

    def get_redirection(self, redirection_id, headers):
        return self._request(
            "GET", f"/api/redirections/{redirection_id}", headers=headers
        )

    def accept_redirection(self, redirection_id, payload, headers):
        return self._request(
            "POST", f"/api/redirections/{redirection_id}/accept", payload, headers
        )

    def decline_redirection(self, redirection_id, headers):
        return self._request(
            "POST", f"/api/redirections/{redirection_id}/decline", {}, headers
        )

    # ------------------------------------------------------------------
    # Biosimilar policies (PRD §3.7)
    # ------------------------------------------------------------------
    def create_biosimilar_policy(self, payload, headers):
        return self._request("POST", "/api/biosimilar-policies", payload, headers)

    def list_biosimilar_policies(self, headers, params=None):
        return self._request(
            "GET", "/api/biosimilar-policies", headers=headers, params=params
        )

    def get_biosimilar_policy(self, policy_id, headers):
        return self._request(
            "GET", f"/api/biosimilar-policies/{policy_id}", headers=headers
        )

    def activate_biosimilar_policy(self, policy_id, headers):
        return self._request(
            "POST", f"/api/biosimilar-policies/{policy_id}/activate", {}, headers
        )

    # ------------------------------------------------------------------
    # Pipeline drugs and spend forecasts (PRD §3.8)
    # ------------------------------------------------------------------
    def create_pipeline_drug(self, payload, headers):
        return self._request("POST", "/api/pipeline-drugs", payload, headers)

    def list_pipeline_drugs(self, headers, params=None):
        return self._request("GET", "/api/pipeline-drugs", headers=headers, params=params)

    def get_pipeline_drug(self, pipeline_drug_id, headers):
        return self._request(
            "GET", f"/api/pipeline-drugs/{pipeline_drug_id}", headers=headers
        )

    def create_spend_forecast(self, payload, headers):
        return self._request("POST", "/api/spend-forecasts", payload, headers)

    def get_spend_forecast(self, forecast_id, headers):
        return self._request(
            "GET", f"/api/spend-forecasts/{forecast_id}", headers=headers
        )


api_client = ApiClient()
