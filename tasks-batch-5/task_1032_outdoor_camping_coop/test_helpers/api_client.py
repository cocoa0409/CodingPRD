"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Members ───────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/coop/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", headers=headers)

    def adjust_store_credit(self, member_id, payload, headers):
        return self._request("POST", f"/coop/members/{member_id}/store-credit", payload, headers)

    # ─── Gear SKUs ─────────────────────────────────────────────────
    def create_gear_sku(self, payload, headers):
        return self._request("POST", "/coop/gear-skus", payload, headers)

    def get_gear_sku(self, sku_id, headers):
        return self._request("GET", f"/coop/gear-skus/{sku_id}", headers=headers)

    # ─── Gear Units ────────────────────────────────────────────────
    def create_gear_unit(self, payload, headers):
        return self._request("POST", "/coop/gear-units", payload, headers)

    def get_gear_unit(self, unit_id, headers):
        return self._request("GET", f"/coop/gear-units/{unit_id}", headers=headers)

    def list_gear_units(self, headers, params=None):
        return self._request("GET", "/coop/gear-units", headers=headers, params=params)

    # ─── Rental Agreements ─────────────────────────────────────────
    def create_rental(self, payload, headers):
        return self._request("POST", "/coop/rental-agreements", payload, headers)

    def get_rental(self, rental_id, headers):
        return self._request("GET", f"/coop/rental-agreements/{rental_id}", headers=headers)

    def list_rentals(self, headers, params=None):
        return self._request("GET", "/coop/rental-agreements", headers=headers, params=params)

    def pickup_rental(self, rental_id, headers):
        return self._request("POST", f"/coop/rental-agreements/{rental_id}/pickup", {}, headers)

    def return_rental(self, rental_id, headers):
        return self._request("POST", f"/coop/rental-agreements/{rental_id}/return", {}, headers)

    def cancel_rental(self, rental_id, headers):
        return self._request("POST", f"/coop/rental-agreements/{rental_id}/cancel", {}, headers)

    # ─── Sales Orders ──────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/coop/sales-orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/coop/sales-orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/coop/sales-orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/coop/sales-orders/{order_id}/pay", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/coop/sales-orders/{order_id}/fulfill", {}, headers)

    def return_order(self, order_id, headers):
        return self._request("POST", f"/coop/sales-orders/{order_id}/return", {}, headers)

    # ─── Trade-Ins ─────────────────────────────────────────────────
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/coop/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/coop/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/coop/trade-ins", headers=headers, params=params)

    def appraise_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/coop/trade-ins/{trade_in_id}/appraise", payload, headers)

    def respond_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/coop/trade-ins/{trade_in_id}/respond", payload, headers)

    def sell_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/coop/trade-ins/{trade_in_id}/sell", payload, headers)

    # ─── Class / Trips ─────────────────────────────────────────────
    def create_class_trip(self, payload, headers):
        return self._request("POST", "/coop/class-trips", payload, headers)

    def get_class_trip(self, class_trip_id, headers):
        return self._request("GET", f"/coop/class-trips/{class_trip_id}", headers=headers)

    def cancel_class_trip(self, class_trip_id, headers):
        return self._request("POST", f"/coop/class-trips/{class_trip_id}/cancel", {}, headers)

    def complete_class_trip(self, class_trip_id, headers):
        return self._request("POST", f"/coop/class-trips/{class_trip_id}/complete", {}, headers)

    # ─── Bookings ──────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/coop/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/coop/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/coop/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/coop/bookings/{booking_id}/cancel", {}, headers)

    def checkin_booking(self, booking_id, headers):
        return self._request("POST", f"/coop/bookings/{booking_id}/check-in", {}, headers)

    # ─── Permit Allocations & Passes ───────────────────────────────
    def create_permit_allocation(self, payload, headers):
        return self._request("POST", "/coop/permit-allocations", payload, headers)

    def get_permit_allocation(self, allocation_id, headers):
        return self._request("GET", f"/coop/permit-allocations/{allocation_id}", headers=headers)

    def create_permit_pass(self, payload, headers):
        return self._request("POST", "/coop/permit-passes", payload, headers)

    def get_permit_pass(self, pass_id, headers):
        return self._request("GET", f"/coop/permit-passes/{pass_id}", headers=headers)

    def list_permit_passes(self, headers, params=None):
        return self._request("GET", "/coop/permit-passes", headers=headers, params=params)

    # ─── Test-driving clock ────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
