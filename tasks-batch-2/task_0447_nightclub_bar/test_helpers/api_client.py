"""API client: one method per endpoint defined in the PRD (Nightclub & Bar Service)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Venue ────────────────────────────────────────────────────────────────
    def create_venue(self, payload, headers):
        return self._request("POST", "/nightclub/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/nightclub/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/nightclub/venues", headers=headers, params=params)

    def close_venue(self, venue_id, headers):
        return self._request("POST", f"/nightclub/venues/{venue_id}/close", headers=headers)

    # ── Promoter ─────────────────────────────────────────────────────────────
    def create_promoter(self, payload, headers):
        return self._request("POST", "/nightclub/promoters", payload, headers)

    def list_promoters(self, headers, params=None):
        return self._request("GET", "/nightclub/promoters", headers=headers, params=params)

    def get_promoter(self, promoter_id, headers):
        return self._request("GET", f"/nightclub/promoters/{promoter_id}", headers=headers)

    # ── Guest list ───────────────────────────────────────────────────────────
    def create_guest_list_entry(self, payload, headers):
        return self._request("POST", "/nightclub/guest-list", payload, headers)

    def list_guest_list(self, headers, params=None):
        return self._request("GET", "/nightclub/guest-list", headers=headers, params=params)

    def get_guest_list_entry(self, gle_id, headers):
        return self._request("GET", f"/nightclub/guest-list/{gle_id}", headers=headers)

    def cancel_guest_list_entry(self, gle_id, headers):
        return self._request("POST", f"/nightclub/guest-list/{gle_id}/cancel", headers=headers)

    # ── ID checks ────────────────────────────────────────────────────────────
    def create_id_check(self, payload, headers):
        return self._request("POST", "/nightclub/id-checks", payload, headers)

    def list_id_checks(self, headers, params=None):
        return self._request("GET", "/nightclub/id-checks", headers=headers, params=params)

    def get_id_check(self, id_check_id, headers):
        return self._request("GET", f"/nightclub/id-checks/{id_check_id}", headers=headers)

    # ── Entries (occupancy) ──────────────────────────────────────────────────
    def create_entry(self, payload, headers):
        return self._request("POST", "/nightclub/entries", payload, headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/nightclub/entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/nightclub/entries/{entry_id}", headers=headers)

    def exit_entry(self, entry_id, headers):
        return self._request("POST", f"/nightclub/entries/{entry_id}/exit", headers=headers)

    # ── Reservations ─────────────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/nightclub/reservations", payload, headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/nightclub/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/nightclub/reservations/{reservation_id}", headers=headers)

    def seat_reservation(self, reservation_id, headers):
        return self._request("POST", f"/nightclub/reservations/{reservation_id}/seat", headers=headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/nightclub/reservations/{reservation_id}/no-show", headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/nightclub/reservations/{reservation_id}/cancel", headers=headers)

    def settle_reservation(self, reservation_id, headers):
        return self._request("POST", f"/nightclub/reservations/{reservation_id}/settle", headers=headers)

    # ── Tabs (bar POS) ───────────────────────────────────────────────────────
    def create_tab(self, payload, headers):
        return self._request("POST", "/nightclub/tabs", payload, headers)

    def list_tabs(self, headers, params=None):
        return self._request("GET", "/nightclub/tabs", headers=headers, params=params)

    def get_tab(self, tab_id, headers):
        return self._request("GET", f"/nightclub/tabs/{tab_id}", headers=headers)

    def add_tab_item(self, tab_id, payload, headers):
        return self._request("POST", f"/nightclub/tabs/{tab_id}/items", payload, headers)

    def list_tab_items(self, tab_id, headers, params=None):
        return self._request("GET", f"/nightclub/tabs/{tab_id}/items", headers=headers, params=params)

    def void_tab_item(self, tab_id, item_id, headers):
        return self._request("POST", f"/nightclub/tabs/{tab_id}/items/{item_id}/void", headers=headers)

    def settle_tab(self, tab_id, headers):
        return self._request("POST", f"/nightclub/tabs/{tab_id}/settle", headers=headers)

    def void_tab(self, tab_id, headers):
        return self._request("POST", f"/nightclub/tabs/{tab_id}/void", headers=headers)

    # ── Security incidents ───────────────────────────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/nightclub/incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/nightclub/incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/nightclub/incidents/{incident_id}", headers=headers)

    # ── Test-driving capabilities ────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def inject_occupancy(self, venue_id, target_inside, headers):
        return self._request(
            "POST",
            "/_inject/occupancy",
            {"venue_id": venue_id, "target_inside": target_inside},
            headers,
        )


api_client = ApiClient()
