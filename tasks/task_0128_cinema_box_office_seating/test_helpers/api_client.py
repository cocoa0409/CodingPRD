"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Auditoriums ----
    def create_auditorium(self, payload, headers):
        return self._request("POST", "/auditoriums", payload, headers)

    def get_auditorium(self, auditorium_id, headers):
        return self._request("GET", f"/auditoriums/{auditorium_id}", headers=headers)

    def list_auditoriums(self, headers, params=None):
        return self._request("GET", "/auditoriums", headers=headers, params=params)

    # ---- Distributors ----
    def create_distributor(self, payload, headers):
        return self._request("POST", "/distributors", payload, headers)

    def get_distributor(self, distributor_id, headers):
        return self._request("GET", f"/distributors/{distributor_id}", headers=headers)

    # ---- Films ----
    def create_film(self, payload, headers):
        return self._request("POST", "/films", payload, headers)

    def get_film(self, film_id, headers):
        return self._request("GET", f"/films/{film_id}", headers=headers)

    def list_films(self, headers, params=None):
        return self._request("GET", "/films", headers=headers, params=params)

    def end_film_run(self, film_id, headers):
        return self._request("POST", f"/films/{film_id}/end-run", {}, headers)

    # ---- Showtimes (nested under auditorium) ----
    def create_showtime(self, auditorium_id, payload, headers):
        return self._request("POST", f"/auditoriums/{auditorium_id}/showtimes", payload, headers)

    def list_auditorium_showtimes(self, auditorium_id, headers, params=None):
        return self._request("GET", f"/auditoriums/{auditorium_id}/showtimes", headers=headers, params=params)

    def get_showtime(self, showtime_id, headers):
        return self._request("GET", f"/showtimes/{showtime_id}", headers=headers)

    def list_showtimes(self, headers, params=None):
        return self._request("GET", "/showtimes", headers=headers, params=params)

    def open_showtime(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/open", {}, headers)

    def reprice_showtime(self, showtime_id, payload, headers):
        return self._request("PATCH", f"/showtimes/{showtime_id}/pricing", payload, headers)

    def cancel_showtime(self, showtime_id, payload, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/cancel", payload, headers)

    def close_showtime(self, showtime_id, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/close", {}, headers)

    def get_showtime_seats(self, showtime_id, headers, params=None):
        return self._request("GET", f"/showtimes/{showtime_id}/seats", headers=headers, params=params)

    def list_showtime_orders(self, showtime_id, headers, params=None):
        return self._request("GET", f"/showtimes/{showtime_id}/orders", headers=headers, params=params)

    def get_showtime_settlement(self, showtime_id, headers):
        return self._request("GET", f"/showtimes/{showtime_id}/settlement", headers=headers)

    # ---- Members ----
    def create_member(self, payload, headers=None):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    # ---- Concession combos ----
    def create_combo(self, payload, headers):
        return self._request("POST", "/combos", payload, headers)

    def get_combo(self, combo_id, headers):
        return self._request("GET", f"/combos/{combo_id}", headers=headers)

    def list_combos(self, headers, params=None):
        return self._request("GET", "/combos", headers=headers, params=params)

    # ---- Orders / tickets / payments ----
    def create_order(self, showtime_id, payload, headers):
        return self._request("POST", f"/showtimes/{showtime_id}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/pay", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def refund_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/refund", payload, headers)

    def exchange_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/exchange", payload, headers)

    def list_order_tickets(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/tickets", headers=headers, params=params)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/payments", headers=headers, params=params)

    # ---- cross-aggregate reverse-reachability ----
    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    # ---- test-driving clock ----
    def advance_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/advance", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
