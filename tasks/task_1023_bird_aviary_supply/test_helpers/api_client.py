"""API client: one method per endpoint defined in the Bird & Aviary Supply PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def set_club_membership(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/club-membership", payload, headers)

    def adjust_wallet(self, customer_id, payload, headers):
        return self._request("POST", f"/customers/{customer_id}/wallet/adjustments", payload, headers)

    def suspend_customer(self, customer_id, headers):
        return self._request("POST", f"/customers/{customer_id}/suspend", {}, headers)

    # ---- Species ----
    def create_species(self, payload, headers):
        return self._request("POST", "/species", payload, headers)

    def list_species(self, headers, params=None):
        return self._request("GET", "/species", headers=headers, params=params)

    def get_species(self, species_id, headers):
        return self._request("GET", f"/species/{species_id}", headers=headers)

    def list_species_permits(self, species_id, headers, params=None):
        return self._request("GET", f"/species/{species_id}/permits", headers=headers, params=params)

    # ---- CitesPermit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/cites-permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/cites-permits/{permit_id}", headers=headers)

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/cites-permits/{permit_id}/submit", {}, headers)

    def return_permit_for_revision(self, permit_id, headers):
        return self._request("POST", f"/cites-permits/{permit_id}/return-for-revision", {}, headers)

    def approve_permit(self, permit_id, headers):
        return self._request("POST", f"/cites-permits/{permit_id}/approve", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/cites-permits/{permit_id}/revoke", {}, headers)

    # ---- Bird ----
    def create_bird(self, payload, headers):
        return self._request("POST", "/birds", payload, headers)

    def list_birds(self, headers, params=None):
        return self._request("GET", "/birds", headers=headers, params=params)

    def get_bird(self, bird_id, headers):
        return self._request("GET", f"/birds/{bird_id}", headers=headers)

    def list_bird_quarantine_records(self, bird_id, headers, params=None):
        return self._request("GET", f"/birds/{bird_id}/quarantine-records", headers=headers, params=params)

    def start_quarantine(self, bird_id, payload, headers):
        return self._request("POST", f"/birds/{bird_id}/start-quarantine", payload, headers)

    def list_bird_for_sale(self, bird_id, headers):
        return self._request("POST", f"/birds/{bird_id}/list-for-sale", {}, headers)

    def relist_bird(self, bird_id, headers):
        return self._request("POST", f"/birds/{bird_id}/relist", {}, headers)

    def sell_bird(self, bird_id, payload, headers):
        return self._request("POST", f"/birds/{bird_id}/sell", payload, headers)

    # ---- QuarantineRecord ----
    def get_quarantine_record(self, record_id, headers):
        return self._request("GET", f"/quarantine-records/{record_id}", headers=headers)

    def start_test(self, record_id, headers):
        return self._request("POST", f"/quarantine-records/{record_id}/start-test", {}, headers)

    def record_test_result(self, record_id, payload, headers):
        return self._request("POST", f"/quarantine-records/{record_id}/record-test-result", payload, headers)

    def clear_quarantine(self, record_id, headers):
        return self._request("POST", f"/quarantine-records/{record_id}/clear", {}, headers)

    def fail_quarantine(self, record_id, headers):
        return self._request("POST", f"/quarantine-records/{record_id}/fail", {}, headers)

    # ---- CageUnit ----
    def create_cage(self, payload, headers):
        return self._request("POST", "/cage-units", payload, headers)

    def list_cages(self, headers, params=None):
        return self._request("GET", "/cage-units", headers=headers, params=params)

    def get_cage(self, cage_id, headers):
        return self._request("GET", f"/cage-units/{cage_id}", headers=headers)

    def update_cage(self, cage_id, payload, headers):
        return self._request("PATCH", f"/cage-units/{cage_id}", payload, headers)

    # ---- BoardingReservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/boarding-reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/boarding-reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/boarding-reservations/{reservation_id}", headers=headers)

    def check_in(self, reservation_id, headers):
        return self._request("POST", f"/boarding-reservations/{reservation_id}/check-in", {}, headers)

    def check_out(self, reservation_id, headers):
        return self._request("POST", f"/boarding-reservations/{reservation_id}/check-out", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/boarding-reservations/{reservation_id}/cancel", {}, headers)

    # ---- GroomingStation ----
    def create_station(self, payload, headers):
        return self._request("POST", "/grooming-stations", payload, headers)

    def list_stations(self, headers, params=None):
        return self._request("GET", "/grooming-stations", headers=headers, params=params)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/grooming-stations/{station_id}", headers=headers)

    def close_station(self, station_id, headers):
        return self._request("POST", f"/grooming-stations/{station_id}/close", {}, headers)

    # ---- GroomingAppointment ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/grooming-appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/grooming-appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/grooming-appointments/{appointment_id}", headers=headers)

    def complete_appointment(self, appointment_id, headers):
        return self._request("POST", f"/grooming-appointments/{appointment_id}/complete", {}, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/grooming-appointments/{appointment_id}/cancel", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/grooming-appointments/{appointment_id}/no-show", {}, headers)

    # ---- FeedSubscription ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/feed-subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/feed-subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/feed-subscriptions/{subscription_id}", headers=headers)

    def pause_subscription(self, subscription_id, headers):
        return self._request("POST", f"/feed-subscriptions/{subscription_id}/pause", {}, headers)

    def resume_subscription(self, subscription_id, headers):
        return self._request("POST", f"/feed-subscriptions/{subscription_id}/resume", {}, headers)

    def cancel_subscription(self, subscription_id, headers, payload=None):
        return self._request("POST", f"/feed-subscriptions/{subscription_id}/cancel", payload or {}, headers)

    # ---- InventoryItem ----
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def restock_inventory_item(self, item_id, payload, headers):
        return self._request("POST", f"/inventory-items/{item_id}/restock", payload, headers)

    # ---- SpecialOrder ----
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/special-orders/{order_id}", headers=headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/pay", {}, headers)

    def refund_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/refund", {}, headers)

    def start_build(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/start-build", {}, headers)

    def mark_built(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/mark-built", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/deliver", {}, headers)

    def cancel_build(self, order_id, headers):
        return self._request("POST", f"/special-orders/{order_id}/cancel-build", {}, headers)


api_client = ApiClient()
