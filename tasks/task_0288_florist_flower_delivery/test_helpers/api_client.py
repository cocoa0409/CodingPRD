"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/floral/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/floral/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/floral/customers", headers=headers, params=params)

    # ---- Zones ----
    def create_zone(self, payload, headers):
        return self._request("POST", "/floral/zones", payload, headers)

    def get_zone(self, zone_id, headers):
        return self._request("GET", f"/floral/zones/{zone_id}", headers=headers)

    def list_zones(self, headers, params=None):
        return self._request("GET", "/floral/zones", headers=headers, params=params)

    def list_zone_delivery_slots(self, zone_id, headers, params=None):
        return self._request("GET", f"/floral/zones/{zone_id}/delivery-slots", headers=headers, params=params)

    # ---- Arrangements ----
    def create_arrangement(self, payload, headers):
        return self._request("POST", "/floral/arrangements", payload, headers)

    def get_arrangement(self, arrangement_id, headers):
        return self._request("GET", f"/floral/arrangements/{arrangement_id}", headers=headers)

    def list_arrangements(self, headers, params=None):
        return self._request("GET", "/floral/arrangements", headers=headers, params=params)

    # ---- Holiday windows ----
    def create_holiday_window(self, payload, headers):
        return self._request("POST", "/floral/holiday-windows", payload, headers)

    def get_holiday_window(self, window_id, headers):
        return self._request("GET", f"/floral/holiday-windows/{window_id}", headers=headers)

    def list_holiday_windows(self, headers, params=None):
        return self._request("GET", "/floral/holiday-windows", headers=headers, params=params)

    # ---- Florists ----
    def create_florist(self, payload, headers):
        return self._request("POST", "/floral/florists", payload, headers)

    def get_florist(self, florist_id, headers):
        return self._request("GET", f"/floral/florists/{florist_id}", headers=headers)

    def list_florists(self, headers, params=None):
        return self._request("GET", "/floral/florists", headers=headers, params=params)

    def update_florist(self, florist_id, payload, headers):
        return self._request("PATCH", f"/floral/florists/{florist_id}", payload, headers)

    # ---- Orders ----
    def create_order(self, payload, headers):
        return self._request("POST", "/floral/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/floral/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/floral/orders", headers=headers, params=params)

    def quote_order(self, order_id, headers):
        return self._request("POST", f"/floral/orders/{order_id}/quote", {}, headers)

    def authorize_payment(self, order_id, headers):
        return self._request("POST", f"/floral/orders/{order_id}/authorize-payment", {}, headers)

    def book_order(self, order_id, payload, headers):
        return self._request("POST", f"/floral/orders/{order_id}/book", payload, headers)

    def dispatch_order(self, order_id, headers):
        return self._request("POST", f"/floral/orders/{order_id}/dispatch", {}, headers)

    def confirm_delivery(self, order_id, headers):
        return self._request("POST", f"/floral/orders/{order_id}/confirm-delivery", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/floral/orders/{order_id}/cancel", {}, headers)

    def list_order_wire_fulfillments(self, order_id, headers, params=None):
        return self._request("GET", f"/floral/orders/{order_id}/wire-fulfillments", headers=headers, params=params)

    def list_order_substitutions(self, order_id, headers, params=None):
        return self._request("GET", f"/floral/orders/{order_id}/substitutions", headers=headers, params=params)

    def list_order_delivery_slots(self, order_id, headers, params=None):
        return self._request("GET", f"/floral/orders/{order_id}/delivery-slots", headers=headers, params=params)

    def list_order_claims(self, order_id, headers, params=None):
        return self._request("GET", f"/floral/orders/{order_id}/claims", headers=headers, params=params)

    # ---- Wire fulfillments ----
    def get_wire_fulfillment(self, wf_id, headers):
        return self._request("GET", f"/floral/wire-fulfillments/{wf_id}", headers=headers)

    def list_wire_fulfillments(self, headers, params=None):
        return self._request("GET", "/floral/wire-fulfillments", headers=headers, params=params)

    def accept_wire_fulfillment(self, wf_id, headers):
        return self._request("POST", f"/floral/wire-fulfillments/{wf_id}/accept", {}, headers)

    # ---- Substitutions ----
    def create_substitution(self, payload, headers):
        return self._request("POST", "/floral/substitutions", payload, headers)

    def get_substitution(self, sub_id, headers):
        return self._request("GET", f"/floral/substitutions/{sub_id}", headers=headers)

    def list_substitutions(self, headers, params=None):
        return self._request("GET", "/floral/substitutions", headers=headers, params=params)

    # ---- Quality claims ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/floral/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/floral/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/floral/claims", headers=headers, params=params)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/floral/claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/floral/claims/{claim_id}/reject", {}, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/floral/claims/{claim_id}/resolve", payload, headers)

    # ---- Recurring schedules ----
    def create_recurring_schedule(self, payload, headers):
        return self._request("POST", "/floral/recurring-schedules", payload, headers)

    def get_recurring_schedule(self, schedule_id, headers):
        return self._request("GET", f"/floral/recurring-schedules/{schedule_id}", headers=headers)

    def list_recurring_schedules(self, headers, params=None):
        return self._request("GET", "/floral/recurring-schedules", headers=headers, params=params)

    def emit_schedule(self, schedule_id, headers):
        return self._request("POST", f"/floral/recurring-schedules/{schedule_id}/emit", {}, headers)

    def pause_schedule(self, schedule_id, headers):
        return self._request("POST", f"/floral/recurring-schedules/{schedule_id}/pause", {}, headers)

    def resume_schedule(self, schedule_id, headers):
        return self._request("POST", f"/floral/recurring-schedules/{schedule_id}/resume", {}, headers)

    def cancel_schedule(self, schedule_id, headers):
        return self._request("POST", f"/floral/recurring-schedules/{schedule_id}/cancel", {}, headers)

    # ---- Simulated clock (test-driving) ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/floral/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers):
        return self._request("GET", "/floral/_clock", headers=headers)

    # ---- Test-driving helpers ----
    def mark_authorized(self, payload, headers):
        return self._request("POST", "/floral/_payments/mark_authorized", payload, headers)

    def set_loyalty_tier(self, payload, headers):
        return self._request("POST", "/floral/_inject/set_loyalty_tier", payload, headers)

    def credit_wallet(self, payload, headers):
        return self._request("POST", "/floral/_inject/credit_wallet", payload, headers)


api_client = ApiClient()
