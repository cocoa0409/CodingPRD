"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Bootstrap / configuration ----
    def create_borrower(self, payload, headers=None):
        return self._request("POST", "/borrowers", payload, headers=headers)

    def get_borrower(self, borrower_id, headers):
        return self._request("GET", f"/borrowers/{borrower_id}", headers=headers)

    def create_abs_pool(self, payload, headers):
        return self._request("POST", "/abs-pools", payload, headers=headers)

    def get_abs_pool(self, pool_id, headers):
        return self._request("GET", f"/abs-pools/{pool_id}", headers=headers)

    def close_abs_pool(self, pool_id, headers):
        return self._request("POST", f"/abs-pools/{pool_id}/close", headers=headers)

    def create_rate_grid_entry(self, payload, headers):
        return self._request("POST", "/rate-grid-entries", payload, headers=headers)

    def list_rate_grid_entries(self, headers, params=None):
        return self._request("GET", "/rate-grid-entries", headers=headers, params=params)

    # ---- Applications ----
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers=headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def prequalify_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/prequalify", {}, headers=headers)

    def approve_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/approve", {}, headers=headers)

    def decline_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/decline", {}, headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/withdraw", {}, headers=headers)

    def expire_offers(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/expire-offers", {}, headers=headers)

    def fund_application(self, application_id, headers):
        return self._request("POST", f"/applications/{application_id}/fund", {}, headers=headers)

    # ---- Offers ----
    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/offers/{offer_id}", headers=headers)

    def list_offers(self, headers, params=None):
        return self._request("GET", "/offers", headers=headers, params=params)

    def lock_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/offers/{offer_id}/lock", payload, headers=headers)

    # ---- Cosigners ----
    def create_cosigner(self, payload, headers):
        return self._request("POST", "/cosigners", payload, headers=headers)

    def get_cosigner(self, cosigner_id, headers):
        return self._request("GET", f"/cosigners/{cosigner_id}", headers=headers)

    def list_cosigners(self, headers, params=None):
        return self._request("GET", "/cosigners", headers=headers, params=params)

    def consent_cosigner(self, cosigner_id, headers):
        return self._request("POST", f"/cosigners/{cosigner_id}/consent", {}, headers=headers)

    def decline_cosigner(self, cosigner_id, headers):
        return self._request("POST", f"/cosigners/{cosigner_id}/decline", {}, headers=headers)

    def release_cosigner(self, cosigner_id, headers):
        return self._request("POST", f"/cosigners/{cosigner_id}/release", {}, headers=headers)

    # ---- Loans ----
    def get_loan(self, loan_id, headers):
        return self._request("GET", f"/loans/{loan_id}", headers=headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", "/loans", headers=headers, params=params)

    def create_payment(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/payments", payload, headers=headers)

    def list_payments(self, loan_id, headers, params=None):
        return self._request("GET", f"/loans/{loan_id}/payments", headers=headers, params=params)

    def start_forbearance(self, loan_id, payload, headers):
        return self._request("POST", f"/loans/{loan_id}/forbearance", payload, headers=headers)

    def mark_delinquent(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/mark-delinquent", {}, headers=headers)

    def charge_off(self, loan_id, headers):
        return self._request("POST", f"/loans/{loan_id}/charge-off", {}, headers=headers)

    # ---- Forbearance ----
    def get_forbearance_plan(self, plan_id, headers):
        return self._request("GET", f"/forbearance-plans/{plan_id}", headers=headers)

    def list_forbearance_plans(self, headers, params=None):
        return self._request("GET", "/forbearance-plans", headers=headers, params=params)

    def end_forbearance(self, plan_id, headers):
        return self._request("POST", f"/forbearance-plans/{plan_id}/end", {}, headers=headers)

    # ---- Disbursements ----
    def create_disbursement(self, payload, headers):
        return self._request("POST", "/disbursements", payload, headers=headers)

    def get_disbursement(self, disbursement_id, headers):
        return self._request("GET", f"/disbursements/{disbursement_id}", headers=headers)

    def list_disbursements(self, headers, params=None):
        return self._request("GET", "/disbursements", headers=headers, params=params)

    def send_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/send", {}, headers=headers)

    def confirm_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/confirm", {}, headers=headers)

    def return_disbursement(self, disbursement_id, headers):
        return self._request("POST", f"/disbursements/{disbursement_id}/return", {}, headers=headers)

    # ---- Audit ----
    def list_audit_events(self, headers, params=None):
        return self._request("GET", "/audit-events", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
