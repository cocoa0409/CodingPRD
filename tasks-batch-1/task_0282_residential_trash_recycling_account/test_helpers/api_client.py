"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Service plans ---
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def list_service_plans(self, headers, params=None):
        return self._request("GET", "/service-plans", params=params, headers=headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    def archive_service_plan(self, plan_id, headers):
        return self._request("POST", f"/service-plans/{plan_id}/archive", {}, headers)

    # --- Collection zones ---
    def create_collection_zone(self, payload, headers):
        return self._request("POST", "/collection-zones", payload, headers)

    def get_collection_zone(self, zone_id, headers):
        return self._request("GET", f"/collection-zones/{zone_id}", headers=headers)

    def create_holiday(self, zone_id, payload, headers):
        return self._request("POST", f"/collection-zones/{zone_id}/holidays", payload, headers)

    def list_holidays(self, zone_id, headers, params=None):
        return self._request("GET", f"/collection-zones/{zone_id}/holidays", params=params, headers=headers)

    # --- Accounts ---
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", params=params, headers=headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def create_cart(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/carts", payload, headers)

    def list_carts(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/carts", params=params, headers=headers)

    def remove_cart(self, cart_id, headers):
        return self._request("POST", f"/carts/{cart_id}/remove", {}, headers)

    def activate_start(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/activate-start", {}, headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def resume_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/resume", {}, headers)

    def stop_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/stop", {}, headers)

    def transfer_out(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/transfer-out", payload, headers)

    def set_payment_method(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/payment-method", payload, headers)

    def set_autopay(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/autopay", payload, headers)

    # --- Invoices ---
    def generate_invoice(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/invoices", payload, headers)

    def list_invoices(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/invoices", params=params, headers=headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def list_payments(self, invoice_id, headers, params=None):
        return self._request("GET", f"/invoices/{invoice_id}/payments", params=params, headers=headers)

    # --- Pickup schedules / events ---
    def list_pickup_schedules(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/pickup-schedules", params=params, headers=headers)

    def get_pickup_schedule(self, schedule_id, headers):
        return self._request("GET", f"/pickup-schedules/{schedule_id}", headers=headers)

    def report_event(self, schedule_id, payload, headers):
        return self._request("POST", f"/pickup-schedules/{schedule_id}/events", payload, headers)

    def list_events(self, schedule_id, headers, params=None):
        return self._request("GET", f"/pickup-schedules/{schedule_id}/events", params=params, headers=headers)

    # --- Extra pickups ---
    def create_extra_pickup(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/extra-pickups", payload, headers)

    def list_extra_pickups(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/extra-pickups", params=params, headers=headers)

    def get_extra_pickup(self, request_id, headers):
        return self._request("GET", f"/extra-pickups/{request_id}", headers=headers)

    def schedule_extra_pickup(self, request_id, headers):
        return self._request("POST", f"/extra-pickups/{request_id}/schedule", {}, headers)

    def complete_extra_pickup(self, request_id, headers):
        return self._request("POST", f"/extra-pickups/{request_id}/complete", {}, headers)

    def cancel_extra_pickup(self, request_id, headers):
        return self._request("POST", f"/extra-pickups/{request_id}/cancel", {}, headers)

    # --- Credits ---
    def list_account_credits(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/credits", params=params, headers=headers)

    def list_credits(self, headers, params=None):
        return self._request("GET", "/credits", params=params, headers=headers)

    def get_credit(self, credit_id, headers):
        return self._request("GET", f"/credits/{credit_id}", headers=headers)

    # --- Contamination notices ---
    def list_account_contamination_notices(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/contamination-notices", params=params, headers=headers)

    def list_contamination_notices(self, headers, params=None):
        return self._request("GET", "/contamination-notices", params=params, headers=headers)

    def get_contamination_notice(self, notice_id, headers):
        return self._request("GET", f"/contamination-notices/{notice_id}", headers=headers)

    def acknowledge_contamination_notice(self, notice_id, headers):
        return self._request("POST", f"/contamination-notices/{notice_id}/acknowledge", {}, headers)

    def waive_contamination_notice(self, notice_id, headers):
        return self._request("POST", f"/contamination-notices/{notice_id}/waive", {}, headers)

    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
