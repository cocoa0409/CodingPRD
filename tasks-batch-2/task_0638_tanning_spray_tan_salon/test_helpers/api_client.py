"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- MembershipPlan ----
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/activate", {}, headers)

    def freeze_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/freeze", payload, headers)

    def unfreeze_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/unfreeze", payload, headers)

    def upgrade_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/upgrade", payload, headers)

    def cancel_member(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/cancel", payload, headers)

    # ---- ConsentRecord ----
    def create_consent(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/consents", payload, headers)

    def list_consents(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/consents", headers=headers, params=params)

    # ---- Equipment ----
    def create_equipment(self, payload, headers):
        return self._request("POST", "/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/equipment/{equipment_id}", headers=headers)

    def service_equipment(self, equipment_id, payload, headers):
        return self._request("POST", f"/equipment/{equipment_id}/service", payload, headers)

    def retire_equipment(self, equipment_id, headers):
        return self._request("POST", f"/equipment/{equipment_id}/retire", {}, headers)

    def list_maintenance_logs(self, equipment_id, headers, params=None):
        return self._request("GET", f"/equipment/{equipment_id}/maintenance-logs", headers=headers, params=params)

    # ---- SprayRoom ----
    def create_spray_room(self, payload, headers):
        return self._request("POST", "/spray-rooms", payload, headers)

    def list_spray_rooms(self, headers, params=None):
        return self._request("GET", "/spray-rooms", headers=headers, params=params)

    def get_spray_room(self, room_id, headers):
        return self._request("GET", f"/spray-rooms/{room_id}", headers=headers)

    # ---- Session ----
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/start", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    def no_show_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/no-show", {}, headers)

    # ---- Product ----
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # ---- RetailOrder ----
    def create_retail_order(self, payload, headers):
        return self._request("POST", "/retail-orders", payload, headers)

    def list_retail_orders(self, headers, params=None):
        return self._request("GET", "/retail-orders", headers=headers, params=params)

    def get_retail_order(self, order_id, headers):
        return self._request("GET", f"/retail-orders/{order_id}", headers=headers)

    def refund_retail_order(self, order_id, headers):
        return self._request("POST", f"/retail-orders/{order_id}/refund", {}, headers)

    # ---- Payment ----
    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ---- SalonLedger ----
    def get_salon_ledger(self, headers):
        return self._request("GET", "/salon-ledger", headers=headers)

    # ---- Test-driving endpoints ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def charge_first_dues(self, payload, headers):
        return self._request("POST", "/_billing/charge-first-dues", payload, headers)

    def run_eft(self, payload, headers):
        return self._request("POST", "/_billing/run-eft", payload, headers)

    def set_upgrade_outcome(self, payload, headers):
        return self._request("POST", "/_billing/set-upgrade-outcome", payload, headers)


api_client = ApiClient()
