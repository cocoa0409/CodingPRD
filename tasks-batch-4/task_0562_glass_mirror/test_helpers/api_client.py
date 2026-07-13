"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ContractorAccount ----
    def create_contractor_account(self, payload, headers):
        return self._request("POST", "/contractor-accounts", payload, headers)

    def get_contractor_account(self, account_id, headers):
        return self._request("GET", f"/contractor-accounts/{account_id}", headers=headers)

    def set_account_status(self, account_id, payload, headers):
        return self._request("POST", f"/contractor-accounts/{account_id}/set-status", payload, headers)

    # ---- Quote ----
    def create_quote(self, payload, headers):
        return self._request("POST", "/quotes", payload, headers)

    def get_quote(self, quote_id, headers):
        return self._request("GET", f"/quotes/{quote_id}", headers=headers)

    def list_quotes(self, headers, params=None):
        return self._request("GET", "/quotes", headers=headers, params=params)

    def add_line_item(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/line-items", payload, headers)

    def list_line_items(self, quote_id, headers, params=None):
        return self._request("GET", f"/quotes/{quote_id}/line-items", headers=headers, params=params)

    def send_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/send", {}, headers)

    def revise_quote(self, quote_id, headers):
        return self._request("POST", f"/quotes/{quote_id}/revise", {}, headers)

    def accept_quote(self, quote_id, payload, headers):
        return self._request("POST", f"/quotes/{quote_id}/accept", payload, headers)

    # ---- Job ----
    def get_job(self, job_id, headers):
        return self._request("GET", f"/jobs/{job_id}", headers=headers)

    def list_jobs(self, headers, params=None):
        return self._request("GET", "/jobs", headers=headers, params=params)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"/jobs/{job_id}/cancel", {}, headers)

    # ---- TemperingFurnace ----
    def create_furnace(self, payload, headers):
        return self._request("POST", "/tempering-furnaces", payload, headers)

    def get_furnace(self, furnace_id, headers):
        return self._request("GET", f"/tempering-furnaces/{furnace_id}", headers=headers)

    # ---- TemperingBatch ----
    def create_tempering_batch(self, payload, headers):
        return self._request("POST", "/tempering-batches", payload, headers)

    def get_tempering_batch(self, batch_id, headers):
        return self._request("GET", f"/tempering-batches/{batch_id}", headers=headers)

    def list_tempering_batches(self, headers, params=None):
        return self._request("GET", "/tempering-batches", headers=headers, params=params)

    def complete_tempering_batch(self, batch_id, headers):
        return self._request("POST", f"/tempering-batches/{batch_id}/complete", {}, headers)

    def cancel_tempering_batch(self, batch_id, headers):
        return self._request("POST", f"/tempering-batches/{batch_id}/cancel", {}, headers)

    # ---- InstallCrew ----
    def create_install_crew(self, payload, headers):
        return self._request("POST", "/install-crews", payload, headers)

    # ---- InstallAppointment ----
    def create_install_appointment(self, payload, headers):
        return self._request("POST", "/install-appointments", payload, headers)

    def get_install_appointment(self, appointment_id, headers):
        return self._request("GET", f"/install-appointments/{appointment_id}", headers=headers)

    def list_install_appointments(self, headers, params=None):
        return self._request("GET", "/install-appointments", headers=headers, params=params)

    def complete_install_appointment(self, appointment_id, headers):
        return self._request("POST", f"/install-appointments/{appointment_id}/complete", {}, headers)

    # ---- ClaimReport ----
    def create_claim_report(self, payload, headers):
        return self._request("POST", "/claim-reports", payload, headers)

    def get_claim_report(self, claim_id, headers):
        return self._request("GET", f"/claim-reports/{claim_id}", headers=headers)

    def list_claim_reports(self, headers, params=None):
        return self._request("GET", "/claim-reports", headers=headers, params=params)

    def review_claim_report(self, claim_id, payload, headers):
        return self._request("POST", f"/claim-reports/{claim_id}/review", payload, headers)

    # ---- RemakeOrder ----
    def get_remake_order(self, remake_id, headers):
        return self._request("GET", f"/remake-orders/{remake_id}", headers=headers)

    def list_remake_orders(self, headers, params=None):
        return self._request("GET", "/remake-orders", headers=headers, params=params)

    def complete_remake_order(self, remake_id, headers):
        return self._request("POST", f"/remake-orders/{remake_id}/complete", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
