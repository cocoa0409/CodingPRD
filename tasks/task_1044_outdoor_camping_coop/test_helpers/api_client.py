"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # ---- Members ----
    def register_member(self, payload, headers=None):
        return self._request("POST", "/coop/members", payload, headers or {})

    def list_members(self, headers, params=None):
        return self._request("GET", "/coop/members", params, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}", None, headers)

    def get_member_summary(self, member_id, headers):
        return self._request("GET", f"/coop/members/{member_id}/summary", None, headers)

    def get_member_loyalty_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/coop/members/{member_id}/loyalty-ledger", params, headers)

    def activate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/activate", {}, headers)

    def lapse_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/lapse", {}, headers)

    def reactivate_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/reactivate", {}, headers)

    def close_member(self, member_id, headers):
        return self._request("POST", f"/coop/members/{member_id}/close", {}, headers)

    def adjust_wallet(self, member_id, payload, headers):
        return self._request("POST", f"/coop/members/{member_id}/wallet/adjustments", payload, headers)

    # ---- Products ----
    def create_product(self, payload, headers):
        return self._request("POST", "/coop/products", payload, headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/coop/products", params, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/coop/products/{product_id}", None, headers)

    # ---- Rental units ----
    def create_rental_unit(self, payload, headers):
        return self._request("POST", "/coop/rental-units", payload, headers)

    def list_rental_units(self, headers, params=None):
        return self._request("GET", "/coop/rental-units", params, headers)

    def get_rental_unit(self, unit_id, headers):
        return self._request("GET", f"/coop/rental-units/{unit_id}", None, headers)

    def service_rental_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/coop/rental-units/{unit_id}/service", payload, headers)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/coop/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/coop/reservations", params, headers)

    def get_reservation(self, res_id, headers):
        return self._request("GET", f"/coop/reservations/{res_id}", None, headers)

    def pickup_reservation(self, res_id, headers):
        return self._request("POST", f"/coop/reservations/{res_id}/pickup", {}, headers)

    def return_reservation(self, res_id, payload, headers):
        return self._request("POST", f"/coop/reservations/{res_id}/return", payload, headers)

    def cancel_reservation(self, res_id, headers):
        return self._request("POST", f"/coop/reservations/{res_id}/cancel", {}, headers)

    # ---- Guides ----
    def create_guide(self, payload, headers):
        return self._request("POST", "/coop/guides", payload, headers)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/coop/guides/{guide_id}", None, headers)

    # ---- Trips ----
    def create_trip(self, payload, headers):
        return self._request("POST", "/coop/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/coop/trips", params, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/coop/trips/{trip_id}", None, headers)

    def assign_guide(self, trip_id, payload, headers):
        return self._request("POST", f"/coop/trips/{trip_id}/assign-guide", payload, headers)

    def open_trip(self, trip_id, headers):
        return self._request("POST", f"/coop/trips/{trip_id}/open", {}, headers)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/coop/trips/{trip_id}/depart", {}, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/coop/trips/{trip_id}/complete", {}, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/coop/trips/{trip_id}/cancel", {}, headers)

    def create_booking(self, trip_id, payload, headers):
        return self._request("POST", f"/coop/trips/{trip_id}/bookings", payload, headers)

    # ---- Trip bookings ----
    def list_bookings(self, headers, params=None):
        return self._request("GET", "/coop/trip-bookings", params, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/coop/trip-bookings/{booking_id}", None, headers)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/coop/trip-bookings/{booking_id}/check-in", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/coop/trip-bookings/{booking_id}/cancel", {}, headers)

    # ---- Trade-ins ----
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/coop/trade-ins", payload, headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/coop/trade-ins", params, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/coop/trade-ins/{trade_in_id}", None, headers)

    def offer_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/coop/trade-ins/{trade_in_id}/offer", {}, headers)

    def counter_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/coop/trade-ins/{trade_in_id}/counter", payload, headers)

    def accept_trade_in(self, trade_in_id, payload, headers):
        return self._request("POST", f"/coop/trade-ins/{trade_in_id}/accept", payload, headers)

    def reject_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/coop/trade-ins/{trade_in_id}/reject", {}, headers)

    # ---- Repair orders ----
    def create_repair_order(self, payload, headers):
        return self._request("POST", "/coop/repair-orders", payload, headers)

    def list_repair_orders(self, headers, params=None):
        return self._request("GET", "/coop/repair-orders", params, headers)

    def get_repair_order(self, ro_id, headers):
        return self._request("GET", f"/coop/repair-orders/{ro_id}", None, headers)

    def diagnose_repair_order(self, ro_id, payload, headers):
        return self._request("POST", f"/coop/repair-orders/{ro_id}/diagnose", payload, headers)

    def start_repair_order(self, ro_id, headers):
        return self._request("POST", f"/coop/repair-orders/{ro_id}/start", {}, headers)

    def ready_repair_order(self, ro_id, headers):
        return self._request("POST", f"/coop/repair-orders/{ro_id}/ready", {}, headers)

    def settle_repair_order(self, ro_id, headers):
        return self._request("POST", f"/coop/repair-orders/{ro_id}/settle", {}, headers)

    def pickup_repair_order(self, ro_id, headers):
        return self._request("POST", f"/coop/repair-orders/{ro_id}/pickup", {}, headers)

    # ---- Passes ----
    def create_pass(self, payload, headers):
        return self._request("POST", "/coop/passes", payload, headers)

    def list_passes(self, headers, params=None):
        return self._request("GET", "/coop/passes", params, headers)

    def get_pass(self, pass_id, headers):
        return self._request("GET", f"/coop/passes/{pass_id}", None, headers)

    def void_pass(self, pass_id, headers):
        return self._request("POST", f"/coop/passes/{pass_id}/void", {}, headers)

    # ---- Special orders ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/coop/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/coop/special-orders", params, headers)

    def get_special_order(self, so_id, headers):
        return self._request("GET", f"/coop/special-orders/{so_id}", None, headers)

    def quote_special_order(self, so_id, payload, headers):
        return self._request("POST", f"/coop/special-orders/{so_id}/quotes", payload, headers)

    def confirm_special_order(self, so_id, headers):
        return self._request("POST", f"/coop/special-orders/{so_id}/confirm", {}, headers)

    def fulfill_special_order(self, so_id, headers):
        return self._request("POST", f"/coop/special-orders/{so_id}/fulfill", {}, headers)

    def cancel_special_order(self, so_id, headers):
        return self._request("POST", f"/coop/special-orders/{so_id}/cancel", {}, headers)

    # ---- Purchases ----
    def create_purchase(self, payload, headers):
        return self._request("POST", "/coop/purchases", payload, headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/coop/purchases", params, headers)

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/coop/purchases/{purchase_id}", None, headers)

    def refund_purchase(self, purchase_id, headers):
        return self._request("POST", f"/coop/purchases/{purchase_id}/refund", {}, headers)

    # ---- Dividends ----
    def create_declaration(self, payload, headers):
        return self._request("POST", "/coop/dividend-declarations", payload, headers)

    def get_declaration(self, decl_id, headers):
        return self._request("GET", f"/coop/dividend-declarations/{decl_id}", None, headers)

    def finalize_declaration(self, decl_id, headers):
        return self._request("POST", f"/coop/dividend-declarations/{decl_id}/finalize", {}, headers)


api_client = ApiClient()
