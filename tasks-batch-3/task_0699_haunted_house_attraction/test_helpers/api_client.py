"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Venue ───────────────────────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def set_weather(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/weather", payload, headers)

    # ─── Attraction ──────────────────────────────────────────────────────
    def create_attraction(self, payload, headers):
        return self._request("POST", "/attractions", payload, headers)

    def get_attraction(self, attraction_id, headers):
        return self._request("GET", f"/attractions/{attraction_id}", headers=headers)

    def list_attractions(self, headers, params=None):
        return self._request("GET", "/attractions", headers=headers, params=params)

    def close_for_season(self, attraction_id, payload, headers):
        return self._request(
            "POST", f"/attractions/{attraction_id}/close_for_season", payload, headers
        )

    # ─── PricingRule ─────────────────────────────────────────────────────
    def create_pricing_rule(self, attraction_id, payload, headers):
        return self._request(
            "POST", f"/attractions/{attraction_id}/pricing-rules", payload, headers
        )

    def get_pricing_rule(self, pricing_rule_id, headers):
        return self._request(
            "GET", f"/pricing-rules/{pricing_rule_id}", headers=headers
        )

    def list_pricing_rules(self, headers, params=None):
        return self._request("GET", "/pricing-rules", headers=headers, params=params)

    # ─── TimeSlot ────────────────────────────────────────────────────────
    def create_time_slot(self, attraction_id, payload, headers):
        return self._request(
            "POST", f"/attractions/{attraction_id}/time-slots", payload, headers
        )

    def get_time_slot(self, time_slot_id, headers):
        return self._request("GET", f"/time-slots/{time_slot_id}", headers=headers)

    def list_time_slots(self, headers, params=None):
        return self._request("GET", "/time-slots", headers=headers, params=params)

    # ─── Guest ───────────────────────────────────────────────────────────
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    # ─── Waiver ──────────────────────────────────────────────────────────
    def create_waiver(self, guest_id, payload, headers):
        return self._request("POST", f"/guests/{guest_id}/waivers", payload, headers)

    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"/waivers/{waiver_id}", headers=headers)

    def list_waivers(self, headers, params=None):
        return self._request("GET", "/waivers", headers=headers, params=params)

    def revoke_waiver(self, waiver_id, payload, headers):
        return self._request("POST", f"/waivers/{waiver_id}/revoke", payload, headers)

    # ─── PassProduct & Pass ──────────────────────────────────────────────
    def create_pass_product(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/pass-products", payload, headers
        )

    def get_pass_product(self, pass_product_id, headers):
        return self._request(
            "GET", f"/pass-products/{pass_product_id}", headers=headers
        )

    def list_pass_products(self, headers, params=None):
        return self._request("GET", "/pass-products", headers=headers, params=params)

    def create_pass(self, payload, headers):
        return self._request("POST", "/passes", payload, headers)

    def get_pass(self, pass_id, headers):
        return self._request("GET", f"/passes/{pass_id}", headers=headers)

    def list_passes(self, headers, params=None):
        return self._request("GET", "/passes", headers=headers, params=params)

    # ─── Reservation & Ticket ────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request(
            "GET", f"/reservations/{reservation_id}", headers=headers
        )

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def add_ticket(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/tickets", payload, headers
        )

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", "/tickets", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, payload, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/confirm", payload, headers
        )

    def pay_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/pay", {}, headers
        )

    def admit_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/admit", {}, headers
        )

    def mark_no_show(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/mark_no_show", {}, headers
        )

    def cancel_reservation(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/cancel", {}, headers
        )

    # ─── ScareZone & ActorShift ──────────────────────────────────────────
    def create_scare_zone(self, attraction_id, payload, headers):
        return self._request(
            "POST", f"/attractions/{attraction_id}/scare-zones", payload, headers
        )

    def get_scare_zone(self, scare_zone_id, headers):
        return self._request("GET", f"/scare-zones/{scare_zone_id}", headers=headers)

    def list_scare_zones(self, headers, params=None):
        return self._request("GET", "/scare-zones", headers=headers, params=params)

    def create_actor_shift(self, scare_zone_id, payload, headers):
        return self._request(
            "POST", f"/scare-zones/{scare_zone_id}/actor-shifts", payload, headers
        )

    def get_actor_shift(self, shift_id, headers):
        return self._request("GET", f"/actor-shifts/{shift_id}", headers=headers)

    def list_actor_shifts(self, headers, params=None):
        return self._request("GET", "/actor-shifts", headers=headers, params=params)

    def check_in_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/actor-shifts/{shift_id}/check_in", {}, headers
        )

    def check_out_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/actor-shifts/{shift_id}/check_out", {}, headers
        )

    def cancel_shift(self, shift_id, headers):
        return self._request(
            "POST", f"/actor-shifts/{shift_id}/cancel", {}, headers
        )

    # ─── Closure ─────────────────────────────────────────────────────────
    def create_closure(self, attraction_id, payload, headers):
        return self._request(
            "POST", f"/attractions/{attraction_id}/closures", payload, headers
        )

    def get_closure(self, closure_id, headers):
        return self._request("GET", f"/closures/{closure_id}", headers=headers)

    def list_closures(self, headers, params=None):
        return self._request("GET", "/closures", headers=headers, params=params)

    def lift_closure(self, closure_id, payload, headers):
        return self._request("POST", f"/closures/{closure_id}/lift", payload, headers)


api_client = ApiClient()
