"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Test-driving logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Organizations ---
    def create_organization(self, payload, headers):
        return self._request("POST", "/organizations", payload, headers)

    def get_organization(self, org_id, headers):
        return self._request("GET", f"/organizations/{org_id}", headers=headers)

    def reinstate_organization(self, org_id, headers):
        return self._request("POST", f"/organizations/{org_id}/reinstate", {}, headers)

    # --- Facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/facilities/{facility_id}", headers=headers)

    def record_facility_condition(self, facility_id, payload, headers):
        return self._request("POST", f"/facilities/{facility_id}/condition", payload, headers)

    # --- Fee schedules ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", "/fee-schedules", payload, headers)

    def get_fee_schedule(self, schedule_id, headers):
        return self._request("GET", f"/fee-schedules/{schedule_id}", headers=headers)

    def publish_fee_schedule(self, schedule_id, headers):
        return self._request("POST", f"/fee-schedules/{schedule_id}/publish", {}, headers)

    # --- Allocation windows ---
    def create_allocation_window(self, payload, headers):
        return self._request("POST", "/allocation-windows", payload, headers)

    def get_allocation_window(self, window_id, headers):
        return self._request("GET", f"/allocation-windows/{window_id}", headers=headers)

    def open_allocation_window(self, window_id, headers):
        return self._request("POST", f"/allocation-windows/{window_id}/open", {}, headers)

    def close_allocation_window(self, window_id, headers):
        return self._request("POST", f"/allocation-windows/{window_id}/close", {}, headers)

    def run_allocation(self, window_id, headers):
        return self._request("POST", f"/allocation-windows/{window_id}/run-allocation", {}, headers)

    # --- Permit applications ---
    def create_permit_application(self, payload, headers):
        return self._request("POST", "/permit-applications", payload, headers)

    def list_permit_applications(self, headers, params=None):
        return self._request("GET", "/permit-applications", headers=headers, params=params)

    def get_permit_application(self, application_id, headers):
        return self._request("GET", f"/permit-applications/{application_id}", headers=headers)

    def withdraw_application(self, application_id, headers):
        return self._request("POST", f"/permit-applications/{application_id}/withdraw", {}, headers)

    def request_info(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/request-info", payload, headers)

    def respond_to_info(self, application_id, payload, headers):
        return self._request("POST", f"/permit-applications/{application_id}/respond", payload, headers)

    # --- Permits ---
    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def confirm_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/confirm", {}, headers)

    def cancel_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/cancel", {}, headers)

    def check_in_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/check-in", payload, headers)

    def mark_no_show(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/mark-no-show", {}, headers)

    def reschedule_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/reschedule", payload, headers)

    def revoke_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", payload, headers)

    def settle_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/settle", payload, headers)

    # --- Field closures ---
    def create_field_closure(self, payload, headers):
        return self._request("POST", "/field-closures", payload, headers)

    def list_field_closures(self, headers, params=None):
        return self._request("GET", "/field-closures", headers=headers, params=params)

    def get_field_closure(self, closure_id, headers):
        return self._request("GET", f"/field-closures/{closure_id}", headers=headers)

    def lift_closure(self, closure_id, headers):
        return self._request("POST", f"/field-closures/{closure_id}/lift", {}, headers)

    # --- Invoices ---
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/issue", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def record_payment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/payments", payload, headers)

    def create_refund(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/refunds", payload, headers)

    def post_adjustment(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/adjustments", payload, headers)

    # --- Payments ---
    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def approve_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/approve", {}, headers)

    # --- Strike records ---
    def list_strike_records(self, headers, params=None):
        return self._request("GET", "/strike-records", headers=headers, params=params)

    def get_strike_record(self, strike_id, headers):
        return self._request("GET", f"/strike-records/{strike_id}", headers=headers)

    def rescind_strike(self, strike_id, headers):
        return self._request("POST", f"/strike-records/{strike_id}/rescind", {}, headers)

    # --- Usage ledgers ---
    def list_usage_ledgers(self, headers, params=None):
        return self._request("GET", "/usage-ledgers", headers=headers, params=params)

    def get_usage_ledger(self, ledger_id, headers):
        return self._request("GET", f"/usage-ledgers/{ledger_id}", headers=headers)


api_client = ApiClient()
