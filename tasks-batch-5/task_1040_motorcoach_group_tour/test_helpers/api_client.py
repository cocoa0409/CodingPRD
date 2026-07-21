"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- TourProduct ----
    def create_tour_product(self, payload, headers):
        return self._request("POST", "/api/tour-products", payload, headers=headers)

    # ---- Coach ----
    def create_coach(self, payload, headers):
        return self._request("POST", "/api/coaches", payload, headers=headers)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/api/coaches/{coach_id}", headers=headers)

    # ---- Driver ----
    def create_driver(self, payload, headers):
        return self._request("POST", "/api/drivers", payload, headers=headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/api/drivers/{driver_id}", headers=headers)

    # ---- Guide ----
    def create_guide(self, payload, headers):
        return self._request("POST", "/api/guides", payload, headers=headers)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/api/guides/{guide_id}", headers=headers)

    # ---- Departure ----
    def create_departure(self, payload, headers):
        return self._request("POST", "/api/departures", payload, headers=headers)

    def get_departure(self, departure_id, headers):
        return self._request("GET", f"/api/departures/{departure_id}", headers=headers)

    def list_departures(self, headers, params=None):
        return self._request("GET", "/api/departures", headers=headers, params=params)

    def publish_departure(self, departure_id, headers):
        return self._request("POST", f"/api/departures/{departure_id}/publish", {}, headers=headers)

    def assign_departure(self, departure_id, payload, headers):
        return self._request("POST", f"/api/departures/{departure_id}/assign", payload, headers=headers)

    def depart_departure(self, departure_id, headers):
        return self._request("POST", f"/api/departures/{departure_id}/depart", {}, headers=headers)

    def cancel_departure(self, departure_id, payload, headers):
        return self._request("POST", f"/api/departures/{departure_id}/cancel", payload, headers=headers)

    def settle_departure(self, departure_id, headers):
        return self._request("POST", f"/api/departures/{departure_id}/settle", {}, headers=headers)

    def get_manifest(self, departure_id, headers):
        return self._request("GET", f"/api/departures/{departure_id}/manifest", headers=headers)

    def get_settlement(self, departure_id, headers):
        return self._request("GET", f"/api/departures/{departure_id}/settlement", headers=headers)

    # ---- HotelBlock ----
    def create_hotel_block(self, payload, headers):
        return self._request("POST", "/api/hotel-blocks", payload, headers=headers)

    def get_hotel_block(self, hotel_block_id, headers):
        return self._request("GET", f"/api/hotel-blocks/{hotel_block_id}", headers=headers)

    def list_hotel_blocks(self, headers, params=None):
        return self._request("GET", "/api/hotel-blocks", headers=headers, params=params)

    def confirm_hotel_block(self, hotel_block_id, headers):
        return self._request("POST", f"/api/hotel-blocks/{hotel_block_id}/confirm", {}, headers=headers)

    def release_hotel_block(self, hotel_block_id, headers):
        return self._request("POST", f"/api/hotel-blocks/{hotel_block_id}/release", {}, headers=headers)

    # ---- Booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/api/bookings", payload, headers=headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/api/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/api/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/api/bookings/{booking_id}/confirm", {}, headers=headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/api/bookings/{booking_id}/cancel", payload, headers=headers)

    # ---- Passenger ----
    def create_passenger(self, payload, headers):
        return self._request("POST", "/api/passengers", payload, headers=headers)

    def get_passenger(self, passenger_id, headers):
        return self._request("GET", f"/api/passengers/{passenger_id}", headers=headers)

    def list_passengers(self, headers, params=None):
        return self._request("GET", "/api/passengers", headers=headers, params=params)

    # ---- Payment ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/api/payments", payload, headers=headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/api/payments", headers=headers, params=params)

    # ---- Voucher ----
    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/api/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/api/vouchers", headers=headers, params=params)

    def redeem_voucher(self, voucher_id, headers):
        return self._request("POST", f"/api/vouchers/{voucher_id}/redeem", {}, headers=headers)

    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers=headers)


api_client = ApiClient()
