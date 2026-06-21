"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customer ────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    def list_customer_wallet_ledger(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/wallet-ledger",
                             headers=headers, params=params)

    def list_customer_recurring_plans(self, customer_id, headers, params=None):
        return self._request("GET", f"/customers/{customer_id}/recurring-plans",
                             headers=headers, params=params)

    # ─── ServiceCatalog ──────────────────────────────────────
    def create_service_catalog(self, payload, headers):
        return self._request("POST", "/service-catalogs", payload, headers)

    def get_service_catalog(self, catalog_id, headers):
        return self._request("GET", f"/service-catalogs/{catalog_id}", headers=headers)

    def list_service_catalogs(self, headers, params=None):
        return self._request("GET", "/service-catalogs", headers=headers, params=params)

    # ─── Crew ────────────────────────────────────────────────
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def crew_out_of_service(self, crew_id, headers):
        return self._request("POST", f"/crews/{crew_id}/out-of-service", {}, headers)

    def list_crew_scheduled_slots(self, crew_id, headers, params=None):
        return self._request("GET", f"/crews/{crew_id}/scheduled-slots",
                             headers=headers, params=params)

    # ─── RecurringPlan ───────────────────────────────────────
    def create_recurring_plan(self, payload, headers):
        return self._request("POST", "/recurring-plans", payload, headers)

    def get_recurring_plan(self, plan_id, headers):
        return self._request("GET", f"/recurring-plans/{plan_id}", headers=headers)

    def pause_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/pause", {}, headers)

    # ─── CleaningJob ─────────────────────────────────────────
    def create_cleaning_job(self, payload, headers):
        return self._request("POST", "/cleaning-jobs", payload, headers)

    def get_cleaning_job(self, job_id, headers):
        return self._request("GET", f"/cleaning-jobs/{job_id}", headers=headers)

    def list_cleaning_jobs(self, headers, params=None):
        return self._request("GET", "/cleaning-jobs", headers=headers, params=params)

    def add_room(self, job_id, payload, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/rooms", payload, headers)

    def list_rooms(self, job_id, headers, params=None):
        return self._request("GET", f"/cleaning-jobs/{job_id}/rooms",
                             headers=headers, params=params)

    def add_addon(self, job_id, payload, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/add-ons", payload, headers)

    def list_addons(self, job_id, headers, params=None):
        return self._request("GET", f"/cleaning-jobs/{job_id}/add-ons",
                             headers=headers, params=params)

    def list_job_scheduled_slots(self, job_id, headers, params=None):
        return self._request("GET", f"/cleaning-jobs/{job_id}/scheduled-slots",
                             headers=headers, params=params)

    def list_job_wallet_ledger(self, job_id, headers, params=None):
        return self._request("GET", f"/cleaning-jobs/{job_id}/wallet-ledger",
                             headers=headers, params=params)

    def quote_job(self, job_id, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/quote", {}, headers)

    def book_job(self, job_id, payload, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/book", payload, headers)

    def reschedule_job(self, job_id, payload, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/reschedule", payload, headers)

    def start_job(self, job_id, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/start", {}, headers)

    def complete_job(self, job_id, payload, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/complete", payload, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/cancel", {}, headers)

    # ─── Invoice / Payment ───────────────────────────────────
    def issue_invoice(self, job_id, headers):
        return self._request("POST", f"/cleaning-jobs/{job_id}/invoice", {}, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_job_invoices(self, job_id, headers, params=None):
        return self._request("GET", f"/cleaning-jobs/{job_id}/invoices",
                             headers=headers, params=params)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments",
                             headers=headers, params=params)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ─── GuaranteeClaim ──────────────────────────────────────
    def file_claim(self, payload, headers):
        return self._request("POST", "/guarantee-claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/guarantee-claims/{claim_id}", headers=headers)

    def list_job_claims(self, job_id, headers, params=None):
        return self._request("GET", f"/cleaning-jobs/{job_id}/guarantee-claims",
                             headers=headers, params=params)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/guarantee-claims", headers=headers, params=params)

    def grant_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/grant", {}, headers)

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"/guarantee-claims/{claim_id}/deny", {}, headers)


api_client = ApiClient()
