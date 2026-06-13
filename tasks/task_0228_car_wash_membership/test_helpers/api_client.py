"""API client for the Car Wash Membership API: one method per endpoint.

Subclasses GenericApiClient; the base _request() handles HTTP + envelope.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Plans ─────────────────────────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/retire", {}, headers)

    # ─── Locations ─────────────────────────────────────────────────────────
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def close_location(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/close", {}, headers)

    def reopen_location(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/reopen", {}, headers)

    # ─── Add-ons ───────────────────────────────────────────────────────────
    def create_addon(self, payload, headers):
        return self._request("POST", "/addons", payload, headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/addons", headers=headers, params=params)

    # ─── Accounts ──────────────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def suspend_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/suspend", {}, headers)

    def reactivate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reactivate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    def create_vehicle(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/vehicles", payload, headers)

    def list_vehicles(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def remove_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/remove", {}, headers)

    def get_vehicle_usage_intensity(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}/usage-intensity", headers=headers)

    def list_wallet_transactions(self, account_id, headers, params=None):
        return self._request("GET", f"/accounts/{account_id}/wallet-transactions", headers=headers, params=params)

    def create_adjustment(self, account_id, payload, headers):
        return self._request("POST", f"/accounts/{account_id}/adjustments", payload, headers)

    # ─── Memberships ───────────────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def change_plan(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/change-plan", payload, headers)

    def freeze_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/freeze", {}, headers)

    def freeze_scheduled(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/freeze-scheduled", payload, headers)

    def unfreeze_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/unfreeze", {}, headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", {}, headers)

    def topup_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/topup", payload, headers)

    def attach_addon(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/addons", payload, headers)

    def list_membership_addons(self, headers, params=None):
        return self._request("GET", "/membership-addons", headers=headers, params=params)

    def get_membership_addon(self, ma_id, headers):
        return self._request("GET", f"/membership-addons/{ma_id}", headers=headers)

    def detach_addon(self, ma_id, headers):
        return self._request("POST", f"/membership-addons/{ma_id}/detach", {}, headers)

    def list_freezes(self, membership_id, headers, params=None):
        return self._request("GET", f"/memberships/{membership_id}/freezes", headers=headers, params=params)

    def cancel_freeze(self, freeze_id, headers):
        return self._request("POST", f"/freezes/{freeze_id}/cancel", {}, headers)

    # ─── Wash events ───────────────────────────────────────────────────────
    def create_wash_event(self, payload, headers):
        return self._request("POST", "/wash-events", payload, headers)

    def get_wash_event(self, we_id, headers):
        return self._request("GET", f"/wash-events/{we_id}", headers=headers)

    def list_wash_events(self, headers, params=None):
        return self._request("GET", "/wash-events", headers=headers, params=params)

    def complete_wash_event(self, we_id, headers):
        return self._request("POST", f"/wash-events/{we_id}/complete", {}, headers)

    # ─── Invoices & billing ────────────────────────────────────────────────
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def retry_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/retry", {}, headers)

    def write_off_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/write-off", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    def billing_run(self, payload, headers):
        return self._request("POST", "/billing/run", payload, headers)

    # ─── Administrative / test-driving ─────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def simulate_payment(self, payload, headers):
        return self._request("POST", "/_payments/simulate", payload, headers)


api_client = ApiClient()
