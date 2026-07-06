"""API client: one method per endpoint defined in the Community Theater Subscription PRD.

All paths are mounted under the /box-office prefix (PRD §2).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- Logical clock (test-driving) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/box-office/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    def sweep_holds(self, headers):
        return self._request("POST", "/box-office/_clock/sweep_holds", {}, headers)

    # ---- Seasons ----
    def create_season(self, payload, headers):
        return self._request("POST", "/box-office/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/box-office/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/box-office/seasons", headers=headers, params=params)

    def open_renewal(self, season_id, headers):
        return self._request("POST", f"/box-office/seasons/{season_id}/open-renewal", {}, headers)

    def close_renewal(self, season_id, headers):
        return self._request("POST", f"/box-office/seasons/{season_id}/close-renewal", {}, headers)

    def close_season(self, season_id, headers):
        return self._request("POST", f"/box-office/seasons/{season_id}/close", {}, headers)

    # ---- Productions ----
    def create_production(self, payload, headers):
        return self._request("POST", "/box-office/productions", payload, headers)

    def get_production(self, production_id, headers):
        return self._request("GET", f"/box-office/productions/{production_id}", headers=headers)

    def list_productions(self, headers, params=None):
        return self._request("GET", "/box-office/productions", headers=headers, params=params)

    def announce_production(self, production_id, headers):
        return self._request("POST", f"/box-office/productions/{production_id}/announce", {}, headers)

    # ---- Venues & Seats ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/box-office/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/box-office/venues/{venue_id}", headers=headers)

    def create_seat(self, payload, headers):
        return self._request("POST", "/box-office/seats", payload, headers)

    def get_seat(self, seat_id, headers):
        return self._request("GET", f"/box-office/seats/{seat_id}", headers=headers)

    def list_seats(self, headers, params=None):
        return self._request("GET", "/box-office/seats", headers=headers, params=params)

    # ---- Performances ----
    def create_performance(self, payload, headers):
        return self._request("POST", "/box-office/performances", payload, headers)

    def get_performance(self, performance_id, headers):
        return self._request("GET", f"/box-office/performances/{performance_id}", headers=headers)

    def list_performances(self, headers, params=None):
        return self._request("GET", "/box-office/performances", headers=headers, params=params)

    def schedule_performance(self, performance_id, headers):
        return self._request("POST", f"/box-office/performances/{performance_id}/schedule", {}, headers)

    def open_sales(self, performance_id, headers):
        return self._request("POST", f"/box-office/performances/{performance_id}/open-sales", {}, headers)

    def suspend_sales(self, performance_id, headers):
        return self._request("POST", f"/box-office/performances/{performance_id}/suspend-sales", {}, headers)

    def settle_performance(self, performance_id, headers):
        return self._request("POST", f"/box-office/performances/{performance_id}/settle", {}, headers)

    def cancel_performance(self, performance_id, headers):
        return self._request("POST", f"/box-office/performances/{performance_id}/cancel", {}, headers)

    # ---- Patrons ----
    def create_patron(self, payload, headers):
        return self._request("POST", "/box-office/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"/box-office/patrons/{patron_id}", headers=headers)

    # ---- Subscriptions ----
    def create_subscription(self, payload, headers):
        return self._request("POST", "/box-office/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/box-office/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/box-office/subscriptions", headers=headers, params=params)

    def create_subscription_seat(self, payload, headers):
        return self._request("POST", "/box-office/subscription-seats", payload, headers)

    def get_subscription_seat(self, subscription_seat_id, headers):
        return self._request("GET", f"/box-office/subscription-seats/{subscription_seat_id}", headers=headers)

    def list_subscription_seats(self, headers, params=None):
        return self._request("GET", "/box-office/subscription-seats", headers=headers, params=params)

    def activate_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/box-office/subscriptions/{subscription_id}/activate", payload, headers)

    def offer_renewal(self, subscription_id, headers):
        return self._request("POST", f"/box-office/subscriptions/{subscription_id}/offer-renewal", {}, headers)

    def confirm_renewal(self, subscription_id, headers):
        return self._request("POST", f"/box-office/subscriptions/{subscription_id}/confirm-renewal", {}, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/box-office/subscriptions/{subscription_id}/cancel", {}, headers)

    # ---- Tickets ----
    def create_ticket(self, payload, headers):
        return self._request("POST", "/box-office/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/box-office/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/box-office/tickets", headers=headers, params=params)

    def pay_ticket(self, ticket_id, headers):
        return self._request("POST", f"/box-office/tickets/{ticket_id}/pay", {}, headers)

    def will_call_pickup(self, ticket_id, headers):
        return self._request("POST", f"/box-office/tickets/{ticket_id}/will-call-pickup", {}, headers)

    def release_ticket(self, ticket_id, headers):
        return self._request("POST", f"/box-office/tickets/{ticket_id}/release", {}, headers)

    # ---- Donations ----
    def create_donation(self, payload, headers):
        return self._request("POST", "/box-office/donations", payload, headers)

    def get_donation(self, donation_id, headers):
        return self._request("GET", f"/box-office/donations/{donation_id}", headers=headers)

    def list_donations(self, headers, params=None):
        return self._request("GET", "/box-office/donations", headers=headers, params=params)

    def fulfill_donation(self, donation_id, headers):
        return self._request("POST", f"/box-office/donations/{donation_id}/fulfill", {}, headers)

    def refund_donation(self, donation_id, headers):
        return self._request("POST", f"/box-office/donations/{donation_id}/refund", {}, headers)

    # ---- Exchanges / Flex-pass ----
    def create_exchange(self, payload, headers):
        return self._request("POST", "/box-office/exchanges", payload, headers)

    def get_exchange(self, exchange_id, headers):
        return self._request("GET", f"/box-office/exchanges/{exchange_id}", headers=headers)

    def list_exchanges(self, headers, params=None):
        return self._request("GET", "/box-office/exchanges", headers=headers, params=params)

    def complete_exchange(self, exchange_id, headers, payload=None):
        return self._request("POST", f"/box-office/exchanges/{exchange_id}/complete", payload or {}, headers)

    def deny_exchange(self, exchange_id, headers):
        return self._request("POST", f"/box-office/exchanges/{exchange_id}/deny", {}, headers)

    # ---- Auditions & Casting ----
    def create_audition(self, payload, headers):
        return self._request("POST", "/box-office/auditions", payload, headers)

    def get_audition(self, audition_id, headers):
        return self._request("GET", f"/box-office/auditions/{audition_id}", headers=headers)

    def list_auditions(self, headers, params=None):
        return self._request("GET", "/box-office/auditions", headers=headers, params=params)

    def record_audition(self, audition_id, headers):
        return self._request("POST", f"/box-office/auditions/{audition_id}/record", {}, headers)

    def callback_audition(self, audition_id, headers):
        return self._request("POST", f"/box-office/auditions/{audition_id}/callback", {}, headers)

    def cast_audition(self, audition_id, payload, headers):
        return self._request("POST", f"/box-office/auditions/{audition_id}/cast", payload, headers)

    def decline_audition(self, audition_id, headers):
        return self._request("POST", f"/box-office/auditions/{audition_id}/decline", {}, headers)


api_client = ApiClient()
