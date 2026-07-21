"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Tenants ----
    def create_tenant(self, headers, payload):
        return self._request("POST", "/api/tenants", payload, headers=headers)

    def get_tenant(self, headers, tenant_id):
        return self._request("GET", f"/api/tenants/{tenant_id}", headers=headers)

    def get_credit_summary(self, headers, tenant_id):
        return self._request("GET", f"/api/tenants/{tenant_id}/credit-summary", headers=headers)

    def list_score_snapshots(self, headers, tenant_id, params=None):
        return self._request("GET", f"/api/tenants/{tenant_id}/score-snapshots", headers=headers, params=params)

    # ---- Landlords ----
    def create_landlord(self, headers, payload):
        return self._request("POST", "/api/landlords", payload, headers=headers)

    def get_landlord(self, headers, landlord_id):
        return self._request("GET", f"/api/landlords/{landlord_id}", headers=headers)

    # ---- Subscription plans ----
    def create_plan(self, headers, payload):
        return self._request("POST", "/api/subscription-plans", payload, headers=headers)

    def get_plan(self, headers, plan_id):
        return self._request("GET", f"/api/subscription-plans/{plan_id}", headers=headers)

    # ---- Enrollments ----
    def create_enrollment(self, headers, payload):
        return self._request("POST", "/api/enrollments", payload, headers=headers)

    def get_enrollment(self, headers, enrollment_id):
        return self._request("GET", f"/api/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/api/enrollments", headers=headers, params=params)

    def cancel_enrollment(self, headers, enrollment_id):
        return self._request("POST", f"/api/enrollments/{enrollment_id}/cancel", {}, headers=headers)

    # ---- Leases ----
    def create_lease(self, headers, payload):
        return self._request("POST", "/api/leases", payload, headers=headers)

    def get_lease(self, headers, lease_id):
        return self._request("GET", f"/api/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/api/leases", headers=headers, params=params)

    def verify_lease(self, headers, lease_id, payload):
        return self._request("POST", f"/api/leases/{lease_id}/verify", payload, headers=headers)

    # ---- Rent payments ----
    def create_rent_payment(self, headers, payload):
        return self._request("POST", "/api/rent-payments", payload, headers=headers)

    def get_rent_payment(self, headers, payment_id):
        return self._request("GET", f"/api/rent-payments/{payment_id}", headers=headers)

    def list_rent_payments(self, headers, params=None):
        return self._request("GET", "/api/rent-payments", headers=headers, params=params)

    def report_rent_payment(self, headers, payment_id):
        return self._request("POST", f"/api/rent-payments/{payment_id}/report", {}, headers=headers)

    # ---- Reported items ----
    def get_reported_item(self, headers, item_id):
        return self._request("GET", f"/api/reported-items/{item_id}", headers=headers)

    def list_reported_items(self, headers, params=None):
        return self._request("GET", "/api/reported-items", headers=headers, params=params)

    def retract_reported_item(self, headers, item_id, payload=None):
        return self._request("POST", f"/api/reported-items/{item_id}/retract", payload or {}, headers=headers)

    # ---- Disputes ----
    def create_dispute(self, headers, payload):
        return self._request("POST", "/api/disputes", payload, headers=headers)

    def get_dispute(self, headers, dispute_id):
        return self._request("GET", f"/api/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", "/api/disputes", headers=headers, params=params)

    def investigate_dispute(self, headers, dispute_id):
        return self._request("POST", f"/api/disputes/{dispute_id}/investigate", {}, headers=headers)

    def resolve_dispute(self, headers, dispute_id, payload):
        return self._request("POST", f"/api/disputes/{dispute_id}/resolve", payload, headers=headers)

    def withdraw_dispute(self, headers, dispute_id):
        return self._request("POST", f"/api/disputes/{dispute_id}/withdraw", {}, headers=headers)

    # ---- Back-report requests ----
    def create_back_report_request(self, headers, payload):
        return self._request("POST", "/api/back-report-requests", payload, headers=headers)

    def get_back_report_request(self, headers, br_id):
        return self._request("GET", f"/api/back-report-requests/{br_id}", headers=headers)

    def list_back_report_requests(self, headers, params=None):
        return self._request("GET", "/api/back-report-requests", headers=headers, params=params)

    def decide_back_report_request(self, headers, br_id, payload):
        return self._request("POST", f"/api/back-report-requests/{br_id}/decision", payload, headers=headers)

    def complete_back_report_request(self, headers, br_id):
        return self._request("POST", f"/api/back-report-requests/{br_id}/complete", {}, headers=headers)

    # ---- Invoices ----
    def get_invoice(self, headers, invoice_id):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def pay_invoice(self, headers, invoice_id):
        return self._request("POST", f"/api/invoices/{invoice_id}/pay", {}, headers=headers)

    # ---- Score snapshots ----
    def create_score_snapshot(self, headers, payload):
        return self._request("POST", "/api/score-snapshots", payload, headers=headers)

    # ---- Logical clock ----
    def set_clock(self, headers, payload):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
