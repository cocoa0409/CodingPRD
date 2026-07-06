"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers
        )

    # ---- Venues ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers=headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ---- Lots ----
    def create_lot(self, payload, headers):
        return self._request("POST", "/lots", payload, headers=headers)

    def get_lot(self, lot_id, headers):
        return self._request("GET", f"/lots/{lot_id}", headers=headers)

    def list_lots(self, headers, params=None):
        return self._request("GET", "/lots", headers=headers, params=params)

    # ---- Films ----
    def create_film(self, payload, headers):
        return self._request("POST", "/films", payload, headers=headers)

    def get_film(self, film_id, headers):
        return self._request("GET", f"/films/{film_id}", headers=headers)

    # ---- Concession items ----
    def create_concession_item(self, payload, headers):
        return self._request("POST", "/concession-items", payload, headers=headers)

    def get_concession_item(self, item_id, headers):
        return self._request("GET", f"/concession-items/{item_id}", headers=headers)

    def list_concession_items(self, headers, params=None):
        return self._request("GET", "/concession-items", headers=headers, params=params)

    # ---- Showtimes ----
    def create_showtime(self, payload, headers):
        return self._request("POST", "/showtimes", payload, headers=headers)

    def get_showtime(self, showtime_id, headers):
        return self._request("GET", f"/showtimes/{showtime_id}", headers=headers)

    def list_showtimes(self, headers, params=None):
        return self._request("GET", "/showtimes", headers=headers, params=params)

    def assign_fm_channel(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/fm-channel", {}, headers=headers)

    def list_fm_channels(self, showtime_id, headers):
        return self._request("GET", f"/showtimes/{showtime_id}/fm-channel", headers=headers)

    def create_weather_event(self, showtime_id, payload, headers):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/weather-events", payload, headers=headers
        )

    def list_weather_events(self, showtime_id, headers):
        return self._request("GET", f"/showtimes/{showtime_id}/weather-events", headers=headers)

    def clear_weather_hold(self, showtime_id, headers):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/clear-weather-hold", {}, headers=headers
        )

    def complete_showtime(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/complete", {}, headers=headers)

    def run_no_show_sweep(self, showtime_id, headers):
        return self._request(
            "POST", f"/showtimes/{showtime_id}/run-no-show-sweep", {}, headers=headers
        )

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers=headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def pay_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/pay", {}, headers=headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/check-in", {}, headers=headers
        )

    def scan_reservation(self, reservation_id, gate_code, headers):
        return self._request(
            "POST",
            f"/reservations/{reservation_id}/scan",
            {"gate_code": gate_code},
            headers=headers,
        )

    def cancel_reservation(self, reservation_id, expected_reservation_version, headers):
        return self._request(
            "POST",
            f"/reservations/{reservation_id}/cancel",
            {"expected_reservation_version": expected_reservation_version},
            headers=headers,
        )

    # ---- Concession orders ----
    def create_concession_order(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/concession-orders", payload, headers=headers
        )

    def list_concession_orders(self, reservation_id, headers, params=None):
        return self._request(
            "GET", f"/reservations/{reservation_id}/concession-orders", headers=headers, params=params
        )

    def pay_concession_order(self, order_id, headers):
        return self._request("POST", f"/concession-orders/{order_id}/pay", {}, headers=headers)

    def fulfill_concession_order(self, order_id, headers):
        return self._request("POST", f"/concession-orders/{order_id}/fulfill", {}, headers=headers)

    def cancel_concession_order(self, order_id, headers):
        return self._request("POST", f"/concession-orders/{order_id}/cancel", {}, headers=headers)

    # ---- Season passes ----
    def create_season_pass(self, payload, headers):
        return self._request("POST", "/season-passes", payload, headers=headers)

    def get_season_pass(self, pass_id, headers):
        return self._request("GET", f"/season-passes/{pass_id}", headers=headers)

    def list_season_passes(self, headers, params=None):
        return self._request("GET", "/season-passes", headers=headers, params=params)

    def revoke_season_pass(self, pass_id, headers):
        return self._request("POST", f"/season-passes/{pass_id}/revoke", {}, headers=headers)

    # ---- Private rentals ----
    def create_private_rental(self, payload, headers):
        return self._request("POST", "/private-rentals", payload, headers=headers)

    def get_private_rental(self, rental_id, headers):
        return self._request("GET", f"/private-rentals/{rental_id}", headers=headers)

    def list_private_rentals(self, headers, params=None):
        return self._request("GET", "/private-rentals", headers=headers, params=params)

    def approve_private_rental(self, rental_id, expected_private_rental_version, headers):
        return self._request(
            "POST",
            f"/private-rentals/{rental_id}/approve",
            {"expected_private_rental_version": expected_private_rental_version},
            headers=headers,
        )

    def reject_private_rental(self, rental_id, headers):
        return self._request("POST", f"/private-rentals/{rental_id}/reject", {}, headers=headers)

    def cancel_private_rental(self, rental_id, headers):
        return self._request("POST", f"/private-rentals/{rental_id}/cancel", {}, headers=headers)

    # ---- Refund records ----
    def get_refund_record(self, refund_id, headers):
        return self._request("GET", f"/refund-records/{refund_id}", headers=headers)

    def list_refund_records(self, headers, params=None):
        return self._request("GET", "/refund-records", headers=headers, params=params)


api_client = ApiClient()
