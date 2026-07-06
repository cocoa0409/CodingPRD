"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP call, envelope, and API_BASE_URL injection. Only PRD-specific endpoint
methods live here.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ Product
    def create_product(self, payload, headers):
        return self._request("POST", "/api/products", payload, headers=headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/api/products/{product_id}", headers=headers)

    # ----------------------------------------------------------------- SalesRep
    def create_sales_rep(self, payload, headers):
        return self._request("POST", "/api/sales-reps", payload, headers=headers)

    def get_sales_rep(self, rep_id, headers):
        return self._request("GET", f"/api/sales-reps/{rep_id}", headers=headers)

    # --------------------------------------------------------------------- Crew
    def create_crew(self, payload, headers):
        return self._request("POST", "/api/crews", payload, headers=headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/api/crews/{crew_id}", headers=headers)

    # --------------------------------------------------------------------- Lead
    def create_lead(self, payload, headers):
        return self._request("POST", "/api/leads", payload, headers=headers)

    def get_lead(self, lead_id, headers):
        return self._request("GET", f"/api/leads/{lead_id}", headers=headers)

    def list_leads(self, headers, params=None):
        return self._request("GET", "/api/leads", headers=headers, params=params)

    def transition_lead(self, lead_id, payload, headers):
        return self._request(
            "POST", f"/api/leads/{lead_id}/transition", payload, headers=headers
        )

    # -------------------------------------------------------------- Appointment
    def create_appointment(self, payload, headers):
        return self._request("POST", "/api/appointments", payload, headers=headers)

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/api/appointments/{appointment_id}", headers=headers
        )

    def list_appointments(self, headers, params=None):
        return self._request(
            "GET", "/api/appointments", headers=headers, params=params
        )

    def transition_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"/api/appointments/{appointment_id}/transition",
            payload,
            headers=headers,
        )

    # -------------------------------------------------------------------- Quote
    def create_quote(self, payload, headers):
        return self._request("POST", "/api/quotes", payload, headers=headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/api/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/api/quotes", headers=headers, params=params)

    def present_quote(self, quote_id, headers):
        return self._request(
            "POST", f"/api/quotes/{quote_id}/present", {}, headers=headers
        )

    def transition_quote(self, quote_id, payload, headers):
        return self._request(
            "POST", f"/api/quotes/{quote_id}/transition", payload, headers=headers
        )

    # ----------------------------------------------------------- FinancingPlan
    def create_financing_plan(self, payload, headers):
        return self._request(
            "POST", "/api/financing-plans", payload, headers=headers
        )

    def get_financing_plan(self, plan_id, headers):
        return self._request(
            "GET", f"/api/financing-plans/{plan_id}", headers=headers
        )

    def list_financing_plans(self, headers, params=None):
        return self._request(
            "GET", "/api/financing-plans", headers=headers, params=params
        )

    def transition_financing_plan(self, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/api/financing-plans/{plan_id}/transition",
            payload,
            headers=headers,
        )

    # --------------------------------------------------------------------- Job
    def get_job(self, job_id, headers):
        return self._request("GET", f"/api/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/api/jobs", headers=headers, params=params)

    def schedule_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/api/jobs/{job_id}/schedule", payload, headers=headers
        )

    def transition_job(self, job_id, payload, headers):
        return self._request(
            "POST", f"/api/jobs/{job_id}/transition", payload, headers=headers
        )

    # ----------------------------------------------------------- WarrantyClaim
    def create_warranty_claim(self, payload, headers):
        return self._request(
            "POST", "/api/warranty-claims", payload, headers=headers
        )

    def get_warranty_claim(self, claim_id, headers):
        return self._request(
            "GET", f"/api/warranty-claims/{claim_id}", headers=headers
        )

    def list_warranty_claims(self, headers, params=None):
        return self._request(
            "GET", "/api/warranty-claims", headers=headers, params=params
        )

    def transition_warranty_claim(self, claim_id, payload, headers):
        return self._request(
            "POST",
            f"/api/warranty-claims/{claim_id}/transition",
            payload,
            headers=headers,
        )

    # ---------------------------------------------------------------- Referral
    def create_referral(self, payload, headers):
        return self._request("POST", "/api/referrals", payload, headers=headers)

    def get_referral(self, referral_id, headers):
        return self._request(
            "GET", f"/api/referrals/{referral_id}", headers=headers
        )

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/api/referrals", headers=headers, params=params)

    def transition_referral(self, referral_id, payload, headers):
        return self._request(
            "POST",
            f"/api/referrals/{referral_id}/transition",
            payload,
            headers=headers,
        )

    # ---------------------------------------------- Test-driving control planes
    def set_clock(self, payload, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", payload, headers=headers
        )

    def set_forecast(self, payload, headers):
        return self._request(
            "POST", "/_weather/set_forecast", payload, headers=headers
        )


api_client = ApiClient()
