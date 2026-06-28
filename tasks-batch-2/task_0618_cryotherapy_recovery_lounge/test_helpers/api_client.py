"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test-driving: logical clock & billing ──────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_billing(self, headers):
        return self._request("POST", "/_billing/run", {}, headers)

    # ─── Locations ──────────────────────────────────────────────────────
    def create_location(self, payload, headers):
        return self._request("POST", "/locations", payload, headers)

    def list_locations(self, headers, params=None):
        return self._request("GET", "/locations", headers=headers, params=params)

    def get_location(self, location_id, headers):
        return self._request("GET", f"/locations/{location_id}", headers=headers)

    def close_location(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/close", {}, headers)

    def open_location(self, location_id, headers):
        return self._request("POST", f"/locations/{location_id}/open", {}, headers)

    # ─── Service types ──────────────────────────────────────────────────
    def create_service_type(self, payload, headers):
        return self._request("POST", "/service-types", payload, headers)

    def list_service_types(self, headers, params=None):
        return self._request("GET", "/service-types", headers=headers, params=params)

    def get_service_type(self, service_type_id, headers):
        return self._request("GET", f"/service-types/{service_type_id}", headers=headers)

    # ─── Rooms ──────────────────────────────────────────────────────────
    def create_room(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    # ─── Technicians ────────────────────────────────────────────────────
    def create_technician(self, location_id, payload, headers):
        return self._request("POST", f"/locations/{location_id}/technicians", payload, headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/technicians", headers=headers, params=params)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/technicians/{technician_id}", headers=headers)

    # ─── Technician shifts ──────────────────────────────────────────────
    def create_shift(self, technician_id, payload, headers):
        return self._request("POST", f"/technicians/{technician_id}/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/cancel", {}, headers)

    # ─── Membership plans ───────────────────────────────────────────────
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/membership-plans", payload, headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/membership-plans", headers=headers, params=params)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/membership-plans/{plan_id}", headers=headers)

    # ─── Members ────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # ─── Waivers ────────────────────────────────────────────────────────
    def create_waiver(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/waivers", payload, headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def revoke_waiver(self, member_id, waiver_id, headers):
        return self._request("POST", f"/members/{member_id}/waivers/{waiver_id}/revoke", {}, headers)

    # ─── Subscriptions ──────────────────────────────────────────────────
    def create_subscription(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/subscription", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def get_refund_quote(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}/refund-quote", headers=headers)

    def upgrade_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/upgrade", payload, headers)

    def freeze_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/freeze", payload, headers)

    def unfreeze_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/unfreeze", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/subscriptions/{subscription_id}/cancel", {}, headers)

    # ─── Invoices ───────────────────────────────────────────────────────
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    # ─── Credit packs ───────────────────────────────────────────────────
    def create_credit_pack(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/credit-packs", payload, headers)

    def list_credit_packs(self, headers, params=None):
        return self._request("GET", "/credit-packs", headers=headers, params=params)

    def get_credit_pack(self, pack_id, headers):
        return self._request("GET", f"/credit-packs/{pack_id}", headers=headers)

    def refund_credit_pack(self, member_id, pack_id, headers):
        return self._request("POST", f"/members/{member_id}/credit-packs/{pack_id}/refund", {}, headers)

    # ─── Bookings ───────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/no-show", {}, headers)


api_client = ApiClient()
