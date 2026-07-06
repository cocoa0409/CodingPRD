"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def refill_helium_tank(self, tank_id, headers):
        return self._request("POST", f"/api/_helium-tanks/{tank_id}/refill",
                             {}, headers)

    # ---- Sku ----
    def create_sku(self, payload, headers):
        return self._request("POST", "/api/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/api/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/api/skus", headers=headers, params=params)

    def clearance_sku(self, sku_id, payload, headers):
        return self._request("POST", f"/api/skus/{sku_id}/clearance", payload, headers)

    def unclear_sku(self, sku_id, headers):
        return self._request("POST", f"/api/skus/{sku_id}/unclear", {}, headers)

    def restock_sku(self, sku_id, delta, headers):
        return self._request("POST", f"/api/skus/{sku_id}/restock",
                             {"delta": delta}, headers)

    # ---- Bundle ----
    def create_bundle(self, payload, headers):
        return self._request("POST", "/api/bundles", payload, headers)

    def get_bundle(self, bundle_id, headers):
        return self._request("GET", f"/api/bundles/{bundle_id}", headers=headers)

    def list_bundle_lines_for_bundle(self, bundle_id, headers):
        return self._request("GET", f"/api/bundles/{bundle_id}/lines", headers=headers)

    def list_bundle_lines(self, headers, params=None):
        return self._request("GET", "/api/bundle-lines", headers=headers, params=params)

    def get_bundle_line(self, bundle_line_id, headers):
        return self._request("GET", f"/api/bundle-lines/{bundle_line_id}", headers=headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/api/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/api/customers/{customer_id}", headers=headers)

    # ---- Order ----
    def create_order(self, payload, headers):
        return self._request("POST", "/api/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/orders", headers=headers, params=params)

    def list_order_lines_for_order(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/lines", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/api/order-lines", headers=headers, params=params)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/api/order-lines/{order_line_id}", headers=headers)

    def reserve_order(self, order_id, expected_order_version, headers):
        return self._request("POST", f"/api/orders/{order_id}/reserve",
                             {"expected_order_version": expected_order_version}, headers)

    def pay_order(self, order_id, mode, headers):
        return self._request("POST", f"/api/orders/{order_id}/pay",
                             {"mode": mode}, headers)

    def start_picking_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/start-picking",
                             {}, headers)

    def mark_ready_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/mark-ready",
                             {}, headers)

    def pickup_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/pickup",
                             {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/deliver",
                             {}, headers)

    def return_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/return",
                             {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/orders/{order_id}/cancel",
                             {}, headers)

    # ---- HeliumOrder ----
    def attach_helium(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/helium",
                             payload, headers)

    def get_helium(self, order_id, headers):
        return self._request("GET", f"/api/orders/{order_id}/helium",
                             headers=headers)

    # ---- HeliumTank ----
    def create_helium_tank(self, payload, headers):
        return self._request("POST", "/api/helium-tanks", payload, headers)

    def get_helium_tank(self, tank_id, headers):
        return self._request("GET", f"/api/helium-tanks/{tank_id}",
                             headers=headers)

    def list_helium_tanks(self, headers, params=None):
        return self._request("GET", "/api/helium-tanks",
                             headers=headers, params=params)

    # ---- DeliverySlot ----
    def create_delivery_slot(self, payload, headers):
        return self._request("POST", "/api/delivery-slots", payload, headers)

    def get_delivery_slot(self, slot_id, headers):
        return self._request("GET", f"/api/delivery-slots/{slot_id}",
                             headers=headers)

    def list_delivery_slots(self, headers, params=None):
        return self._request("GET", "/api/delivery-slots",
                             headers=headers, params=params)

    # ---- RentalContract ----
    def create_rental_contract(self, payload, headers):
        return self._request("POST", "/api/rental-contracts", payload, headers)

    def get_rental_contract(self, rental_id, headers):
        return self._request("GET", f"/api/rental-contracts/{rental_id}",
                             headers=headers)

    def list_rental_contracts(self, headers, params=None):
        return self._request("GET", "/api/rental-contracts",
                             headers=headers, params=params)

    def return_rental(self, rental_id, headers):
        return self._request("POST", f"/api/rental-contracts/{rental_id}/return",
                             {}, headers)

    def mark_damaged_rental(self, rental_id, headers):
        return self._request("POST",
                             f"/api/rental-contracts/{rental_id}/mark-damaged",
                             {}, headers)

    # ---- CustomPrintOrder ----
    def attach_custom_print(self, order_id, payload, headers):
        return self._request("POST", f"/api/orders/{order_id}/custom-print",
                             payload, headers)

    def get_custom_print(self, cpo_id, headers):
        return self._request("GET", f"/api/custom-print-orders/{cpo_id}",
                             headers=headers)

    def list_custom_prints(self, headers, params=None):
        return self._request("GET", "/api/custom-print-orders",
                             headers=headers, params=params)

    def send_proof(self, cpo_id, headers):
        return self._request("POST",
                             f"/api/custom-print-orders/{cpo_id}/send-proof",
                             {}, headers)

    def request_revision(self, cpo_id, headers):
        return self._request("POST",
                             f"/api/custom-print-orders/{cpo_id}/request-revision",
                             {}, headers)

    def approve_proof(self, cpo_id, headers):
        return self._request("POST",
                             f"/api/custom-print-orders/{cpo_id}/approve",
                             {}, headers)

    def start_print(self, cpo_id, headers):
        return self._request("POST",
                             f"/api/custom-print-orders/{cpo_id}/start-print",
                             {}, headers)

    def mark_ready_print(self, cpo_id, headers):
        return self._request("POST",
                             f"/api/custom-print-orders/{cpo_id}/mark-ready",
                             {}, headers)

    def cancel_custom_print(self, cpo_id, headers):
        return self._request("POST",
                             f"/api/custom-print-orders/{cpo_id}/cancel",
                             {}, headers)

    # ---- EventPackage / EventBooking ----
    def create_event_package(self, payload, headers):
        return self._request("POST", "/api/event-packages", payload, headers)

    def get_event_package(self, pkg_id, headers):
        return self._request("GET", f"/api/event-packages/{pkg_id}",
                             headers=headers)

    def list_event_packages(self, headers, params=None):
        return self._request("GET", "/api/event-packages",
                             headers=headers, params=params)

    def create_event_booking(self, payload, headers):
        return self._request("POST", "/api/event-bookings", payload, headers)

    def get_event_booking(self, booking_id, headers):
        return self._request("GET", f"/api/event-bookings/{booking_id}",
                             headers=headers)

    def list_event_bookings(self, headers, params=None):
        return self._request("GET", "/api/event-bookings",
                             headers=headers, params=params)

    def confirm_event_booking(self, booking_id, headers):
        return self._request("POST",
                             f"/api/event-bookings/{booking_id}/confirm",
                             {}, headers)

    def complete_event_booking(self, booking_id, headers):
        return self._request("POST",
                             f"/api/event-bookings/{booking_id}/complete",
                             {}, headers)

    def cancel_event_booking(self, booking_id, headers):
        return self._request("POST",
                             f"/api/event-bookings/{booking_id}/cancel",
                             {}, headers)


api_client = ApiClient()
