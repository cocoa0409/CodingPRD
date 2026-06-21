"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------- Clock (test driving) ----------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---------- SubscriptionPlan ----------
    def create_subscription_plan(self, payload, headers):
        return self._request("POST", "/subscription-plans", payload, headers)

    def list_subscription_plans(self, headers, params=None):
        return self._request("GET", "/subscription-plans", headers=headers, params=params)

    def get_subscription_plan(self, plan_id, headers):
        return self._request("GET", f"/subscription-plans/{plan_id}", headers=headers)

    # ---------- Customer ----------
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def block_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/block", {}, headers)

    # ---------- Subscription ----------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def change_subscription_plan(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/change-plan", payload, headers)

    def cancel_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", payload, headers)

    # ---------- RouteWindow ----------
    def create_route_window(self, payload, headers):
        return self._request("POST", "/route-windows", payload, headers)

    def list_route_windows(self, headers, params=None):
        return self._request("GET", "/route-windows", headers=headers, params=params)

    def get_route_window(self, window_id, headers):
        return self._request("GET", f"/route-windows/{window_id}", headers=headers)

    # ---------- Locker ----------
    def create_locker(self, payload, headers):
        return self._request("POST", "/lockers", payload, headers)

    def list_lockers(self, headers, params=None):
        return self._request("GET", "/lockers", headers=headers, params=params)

    def get_locker(self, locker_id, headers):
        return self._request("GET", f"/lockers/{locker_id}", headers=headers)

    # ---------- Order ----------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def add_garment(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/garments", payload, headers)

    def list_garments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/garments", headers=headers, params=params)

    def get_garment(self, order_id, garment_id, headers):
        return self._request("GET", f"/orders/{order_id}/garments/{garment_id}", headers=headers)

    def schedule_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/schedule", payload or {}, headers)

    def pickup_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/pickup", payload or {}, headers)

    def log_intake(self, order_id, garment_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/garments/{garment_id}/log-intake", payload, headers)

    def start_processing(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/start-processing", payload or {}, headers)

    def finish_clean(self, order_id, garment_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/garments/{garment_id}/finish-clean", payload or {}, headers)

    def rewash(self, order_id, garment_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/garments/{garment_id}/rewash", payload or {}, headers)

    def mark_lost(self, order_id, garment_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/garments/{garment_id}/mark-lost", payload or {}, headers)

    def log_note(self, order_id, garment_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/garments/{garment_id}/notes", payload, headers)

    def list_garment_notes(self, headers, params=None):
        return self._request("GET", "/garment-notes", headers=headers, params=params)

    def get_garment_note(self, note_id, headers):
        return self._request("GET", f"/garment-notes/{note_id}", headers=headers)

    def qc_hold(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/qc-hold", payload or {}, headers)

    def reopen_processing(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/reopen-processing", payload or {}, headers)

    def qc_pass(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/qc-pass", payload or {}, headers)

    def dispatch_delivery(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/dispatch-delivery", payload or {}, headers)

    def confirm_delivery(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/confirm-delivery", payload or {}, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    def get_order_invoice(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/invoice", headers=headers, params=params)

    # ---------- LockerAssignment ----------
    def create_locker_assignment(self, payload, headers):
        return self._request("POST", "/locker-assignments", payload, headers)

    def list_locker_assignments(self, headers, params=None):
        return self._request("GET", "/locker-assignments", headers=headers, params=params)

    def get_locker_assignment(self, assignment_id, headers):
        return self._request("GET", f"/locker-assignments/{assignment_id}", headers=headers)

    def occupy_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/locker-assignments/{assignment_id}/occupy", payload or {}, headers)

    def release_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/locker-assignments/{assignment_id}/release", payload or {}, headers)

    def expire_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/locker-assignments/{assignment_id}/expire", payload or {}, headers)

    # ---------- Claim ----------
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def investigate_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/investigate", payload or {}, headers)

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/approve", payload or {}, headers)

    def reject_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/reject", payload or {}, headers)

    def appeal_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/appeal", payload or {}, headers)

    def finalize_denial(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/finalize-denial", payload or {}, headers)

    def settle_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/settle", payload or {}, headers)


api_client = ApiClient()
