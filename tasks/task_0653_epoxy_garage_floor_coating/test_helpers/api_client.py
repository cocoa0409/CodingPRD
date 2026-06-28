"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Coating systems ----
    def create_coating_system(self, payload, headers):
        return self._request("POST", "/coating-systems", payload, headers)

    def get_coating_system(self, system_id, headers):
        return self._request("GET", f"/coating-systems/{system_id}", headers=headers)

    def list_color_options(self, system_id, headers, params=None):
        return self._request(
            "GET", f"/coating-systems/{system_id}/color-options",
            headers=headers, params=params,
        )

    # ---- Color options ----
    def create_color_option(self, payload, headers):
        return self._request("POST", "/color-options", payload, headers)

    # ---- Financing plans ----
    def create_financing_plan(self, payload, headers):
        return self._request("POST", "/financing-plans", payload, headers)

    # ---- Crews ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def list_crew_install_jobs(self, crew_id, headers, params=None):
        return self._request(
            "GET", f"/crews/{crew_id}/install-jobs", headers=headers, params=params
        )

    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def list_customer_projects(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/projects", headers=headers, params=params
        )

    def list_customer_referrals(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/customers/{customer_id}/referrals", headers=headers, params=params
        )

    # ---- Projects ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def create_assessment(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/assessments", payload, headers
        )

    def list_assessments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/assessments", headers=headers, params=params
        )

    def create_quote(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/quotes", payload, headers
        )

    def list_quotes(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/quotes", headers=headers, params=params
        )

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", {}, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers)

    def decline_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/decline", {}, headers)

    def cancel_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", payload, headers)

    # ---- Install jobs ----
    def create_install_job(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/install-jobs", payload, headers
        )

    def list_project_install_jobs(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/install-jobs", headers=headers, params=params
        )

    def start_install_job(self, install_job_id, headers):
        return self._request(
            "POST", f"/install-jobs/{install_job_id}/start", {}, headers
        )

    def complete_install_job(self, install_job_id, payload, headers):
        return self._request(
            "POST", f"/install-jobs/{install_job_id}/complete", payload, headers
        )

    def mark_cured(self, install_job_id, headers):
        return self._request(
            "POST", f"/install-jobs/{install_job_id}/mark-cured", {}, headers
        )

    # ---- Warranties & claims ----
    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def list_project_warranties(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/warranties", headers=headers, params=params
        )

    def create_claim(self, warranty_id, payload, headers):
        return self._request(
            "POST", f"/warranties/{warranty_id}/claims", payload, headers
        )

    def list_warranty_claims(self, warranty_id, headers, params=None):
        return self._request(
            "GET", f"/warranties/{warranty_id}/claims", headers=headers, params=params
        )

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def review_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/claims/{claim_id}/review", payload, headers)

    def resubmit_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/resubmit", {}, headers)

    def schedule_callback(self, claim_id, headers):
        return self._request(
            "POST", f"/claims/{claim_id}/schedule-callback", {}, headers
        )

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/close", {}, headers)

    # ---- Referrals ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)


api_client = ApiClient()
