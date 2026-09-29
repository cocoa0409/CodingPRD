"""API client: one method per endpoint defined in the PRD.

Every business path is mounted under `/orchestra`; the logical clock endpoint is
the single exception and sits outside that prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/orchestra"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Season
    # ------------------------------------------------------------------
    def create_season(self, payload, headers):
        return self._request("POST", f"{PREFIX}/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"{PREFIX}/seasons/{season_id}", headers=headers)

    def advance_season(self, season_id, target_status, headers):
        return self._request(
            "POST",
            f"{PREFIX}/seasons/{season_id}/advance",
            {"target_status": target_status},
            headers,
        )

    def run_ops(self, season_id, headers):
        return self._request(
            "POST", f"{PREFIX}/seasons/{season_id}/run-ops", {}, headers
        )

    # ------------------------------------------------------------------
    # Venue / SeatSection
    # ------------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", f"{PREFIX}/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"{PREFIX}/venues/{venue_id}", headers=headers)

    def create_section(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"{PREFIX}/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sections", headers=headers, params=params)

    # ------------------------------------------------------------------
    # UnionAgreement
    # ------------------------------------------------------------------
    def create_union_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/union-agreements", payload, headers)

    def get_union_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/union-agreements/{agreement_id}", headers=headers
        )

    def list_union_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/union-agreements", headers=headers, params=params
        )

    # ------------------------------------------------------------------
    # Concert
    # ------------------------------------------------------------------
    def create_concert(self, payload, headers):
        return self._request("POST", f"{PREFIX}/concerts", payload, headers)

    def get_concert(self, concert_id, headers):
        return self._request("GET", f"{PREFIX}/concerts/{concert_id}", headers=headers)

    def list_concerts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/concerts", headers=headers, params=params)

    def program_concert(self, concert_id, headers):
        return self._request(
            "POST", f"{PREFIX}/concerts/{concert_id}/program", {}, headers
        )

    def cancel_concert(self, concert_id, reason, headers):
        return self._request(
            "POST", f"{PREFIX}/concerts/{concert_id}/cancel", {"reason": reason}, headers
        )

    def substitute_guest_artist(self, concert_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/concerts/{concert_id}/substitute", payload, headers
        )

    def settle_concert(self, concert_id, headers):
        return self._request(
            "POST", f"{PREFIX}/concerts/{concert_id}/settle", {}, headers
        )

    def get_price_quote(self, concert_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/concerts/{concert_id}/price-quote",
            headers=headers, params=params,
        )

    # ------------------------------------------------------------------
    # GuestArtistContract
    # ------------------------------------------------------------------
    def create_guest_contract(self, payload, headers):
        return self._request("POST", f"{PREFIX}/guest-contracts", payload, headers)

    def get_guest_contract(self, contract_id, headers):
        return self._request(
            "GET", f"{PREFIX}/guest-contracts/{contract_id}", headers=headers
        )

    def list_guest_contracts(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/guest-contracts", headers=headers, params=params
        )

    def counter_guest_contract(self, contract_id, countered_fee_cents, headers):
        return self._request(
            "POST",
            f"{PREFIX}/guest-contracts/{contract_id}/counter",
            {"countered_fee_cents": countered_fee_cents},
            headers,
        )

    def revise_guest_contract_offer(self, contract_id, offered_fee_cents, headers):
        return self._request(
            "POST",
            f"{PREFIX}/guest-contracts/{contract_id}/revise-offer",
            {"offered_fee_cents": offered_fee_cents},
            headers,
        )

    def sign_guest_contract(self, contract_id, headers):
        return self._request(
            "POST", f"{PREFIX}/guest-contracts/{contract_id}/sign", {}, headers
        )

    # ------------------------------------------------------------------
    # Musician
    # ------------------------------------------------------------------
    def create_musician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/musicians", payload, headers)

    def get_musician(self, musician_id, headers):
        return self._request("GET", f"{PREFIX}/musicians/{musician_id}", headers=headers)

    # ------------------------------------------------------------------
    # RehearsalService
    # ------------------------------------------------------------------
    def create_rehearsal(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rehearsals", payload, headers)

    def get_rehearsal(self, service_id, headers):
        return self._request("GET", f"{PREFIX}/rehearsals/{service_id}", headers=headers)

    def list_rehearsals(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rehearsals", headers=headers, params=params
        )

    def publish_rehearsal(self, service_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rehearsals/{service_id}/publish", {}, headers
        )

    def clock_rehearsal(self, service_id, actual_start_utc, actual_end_utc, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rehearsals/{service_id}/clock",
            {"actual_start_utc": actual_start_utc, "actual_end_utc": actual_end_utc},
            headers,
        )

    def create_engagement(self, service_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rehearsals/{service_id}/engagements", payload, headers
        )

    # ------------------------------------------------------------------
    # MusicianEngagement
    # ------------------------------------------------------------------
    def get_engagement(self, engagement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/engagements/{engagement_id}", headers=headers
        )

    def list_engagements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/engagements", headers=headers, params=params
        )

    def decline_engagement(self, engagement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/engagements/{engagement_id}/decline", {}, headers
        )

    # ------------------------------------------------------------------
    # Patron
    # ------------------------------------------------------------------
    def create_patron(self, payload, headers):
        return self._request("POST", f"{PREFIX}/patrons", payload, headers)

    def get_patron(self, patron_id, headers):
        return self._request("GET", f"{PREFIX}/patrons/{patron_id}", headers=headers)

    def record_donation(self, patron_id, amount_cents, headers):
        return self._request(
            "POST",
            f"{PREFIX}/patrons/{patron_id}/donations",
            {"amount_cents": amount_cents},
            headers,
        )

    # ------------------------------------------------------------------
    # SubscriptionPackage
    # ------------------------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", f"{PREFIX}/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request(
            "GET", f"{PREFIX}/subscriptions/{subscription_id}", headers=headers
        )

    def list_subscriptions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/subscriptions", headers=headers, params=params
        )

    def pay_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/pay", {}, headers
        )

    def renew_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/subscriptions/{subscription_id}/renew", payload, headers
        )

    # ------------------------------------------------------------------
    # TicketOrder
    # ------------------------------------------------------------------
    def create_ticket_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ticket-orders", payload, headers)

    def get_ticket_order(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ticket-orders/{order_id}", headers=headers
        )

    def list_ticket_orders(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ticket-orders", headers=headers, params=params
        )

    def pay_ticket_order(self, order_id, headers, use_credit=None):
        payload = {} if use_credit is None else {"use_credit": use_credit}
        return self._request(
            "POST", f"{PREFIX}/ticket-orders/{order_id}/pay", payload, headers
        )

    # ------------------------------------------------------------------
    # AdBooking
    # ------------------------------------------------------------------
    def create_ad_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/ad-bookings", payload, headers)

    def get_ad_booking(self, booking_id, headers):
        return self._request(
            "GET", f"{PREFIX}/ad-bookings/{booking_id}", headers=headers
        )

    def list_ad_bookings(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/ad-bookings", headers=headers, params=params
        )

    def decide_ad_booking(self, booking_id, decision, headers):
        return self._request(
            "POST",
            f"{PREFIX}/ad-bookings/{booking_id}/decide",
            {"decision": decision},
            headers,
        )


api_client = ApiClient()
