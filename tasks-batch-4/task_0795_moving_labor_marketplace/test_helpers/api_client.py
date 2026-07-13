"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Helpers ----
    def create_helper(self, payload, headers):
        return self._request("POST", "/helpers", payload, headers)

    def get_helper(self, helper_id, headers):
        return self._request("GET", f"/helpers/{helper_id}", headers=headers)

    def vet_helper(self, helper_id, payload, headers):
        return self._request("POST", f"/helpers/{helper_id}/vet", payload, headers)

    # ---- Config: rate cards / insurance / trucks ----
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/rate-cards", payload, headers)

    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/insurance-policies", payload, headers)

    def create_truck(self, payload, headers):
        return self._request("POST", "/trucks", payload, headers)

    def get_truck(self, truck_id, headers):
        return self._request("GET", f"/trucks/{truck_id}", headers=headers)

    # ---- Jobs ----
    def create_job(self, payload, headers):
        return self._request("POST", "/jobs", payload, headers)

    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def add_addon(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/add-ons", payload, headers)

    def quote_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/quote", {}, headers)

    def book_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/book", payload, headers)

    def reschedule_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/reschedule", payload, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/cancel", {}, headers)

    def assign_truck(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/assign-truck", payload, headers)

    def start_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/start", {}, headers)

    def complete_job(self, job_id, payload, headers):
        return self._request("POST", f"/jobs/{job_id}/complete", payload, headers)

    def settle_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/settle", {}, headers)

    # ---- Add-ons / quotes read ----
    def get_addon(self, addon_id, headers):
        return self._request("GET", f"/add-ons/{addon_id}", headers=headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/add-ons", headers=headers, params=params)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    # ---- Assignments ----
    def create_assignment(self, payload, headers):
        return self._request("POST", "/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def check_in(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-in", {}, headers)

    def check_out(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-out", {}, headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/no-show", {}, headers)

    # ---- Claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/review", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/deny", {}, headers)

    # ---- Ratings ----
    def create_rating(self, payload, headers):
        return self._request("POST", "/ratings", payload, headers)

    def get_rating(self, rating_id, headers):
        return self._request("GET", f"/ratings/{rating_id}", headers=headers)

    def list_ratings(self, headers, params=None):
        return self._request("GET", "/ratings", headers=headers, params=params)

    # ---- Payouts ----
    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def reverse_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/reverse", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
