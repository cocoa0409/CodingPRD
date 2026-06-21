"""API client: one method per endpoint defined in the PRD (§4).

Subclasses GenericApiClient; the base `_request(method, path, payload=None,
headers=...)` is inherited. The whole API is mounted under `/culinary`; the
test-driving clock lives at `/_clock`.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Instructor ──────────────────────────────────────────────────
    def create_instructor(self, payload, headers):
        return self._request("POST", "/culinary/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/culinary/instructors/{instructor_id}", headers=headers)

    # ── Member ──────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/culinary/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/culinary/members/{member_id}", headers=headers)

    def list_member_no_show_records(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/culinary/members/{member_id}/no-show-records",
            headers=headers, params=params,
        )

    def adjust_wallet(self, member_id, payload, headers):
        return self._request(
            "POST", f"/culinary/members/{member_id}/wallet/adjustments", payload, headers,
        )

    # ── ClassTemplate ───────────────────────────────────────────────
    def create_template(self, payload, headers):
        return self._request("POST", "/culinary/templates", payload, headers)

    def publish_template(self, template_id, headers):
        return self._request("POST", f"/culinary/templates/{template_id}/publish", {}, headers)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/culinary/templates/{template_id}", headers=headers)

    # ── RecurringSeries ─────────────────────────────────────────────
    def create_series(self, payload, headers):
        return self._request("POST", "/culinary/series", payload, headers)

    def publish_series(self, series_id, headers):
        return self._request("POST", f"/culinary/series/{series_id}/publish", {}, headers)

    def cancel_series(self, series_id, headers):
        return self._request("POST", f"/culinary/series/{series_id}/cancel", {}, headers)

    def get_series(self, series_id, headers):
        return self._request("GET", f"/culinary/series/{series_id}", headers=headers)

    def list_series(self, headers, params=None):
        return self._request("GET", "/culinary/series", headers=headers, params=params)

    def list_series_sessions(self, series_id, headers, params=None):
        return self._request(
            "GET", f"/culinary/series/{series_id}/sessions", headers=headers, params=params,
        )

    # ── ClassSession ────────────────────────────────────────────────
    def create_session(self, payload, headers):
        return self._request("POST", "/culinary/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/culinary/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/culinary/sessions", headers=headers, params=params)

    def open_session(self, session_id, headers):
        return self._request("POST", f"/culinary/sessions/{session_id}/open", {}, headers)

    def lock_session(self, session_id, headers):
        return self._request("POST", f"/culinary/sessions/{session_id}/lock", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/culinary/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/culinary/sessions/{session_id}/cancel", {}, headers)

    # ── IngredientLine ──────────────────────────────────────────────
    def create_ingredient_line(self, session_id, payload, headers):
        return self._request(
            "POST", f"/culinary/sessions/{session_id}/ingredient-lines", payload, headers,
        )

    def list_ingredient_lines(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/culinary/sessions/{session_id}/ingredient-lines",
            headers=headers, params=params,
        )

    # ── Booking ─────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/culinary/bookings", payload, headers)

    def confirm_booking(self, booking_id, expected_session_version, headers):
        return self._request(
            "POST", f"/culinary/bookings/{booking_id}/confirm",
            {"expected_session_version": expected_session_version}, headers,
        )

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/culinary/bookings/{booking_id}/cancel", {}, headers)

    def mark_no_show(self, booking_id, headers):
        return self._request("POST", f"/culinary/bookings/{booking_id}/mark-no-show", {}, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/culinary/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/culinary/bookings", headers=headers, params=params)

    # ── WaitlistEntry ───────────────────────────────────────────────
    def join_waitlist(self, session_id, payload, headers):
        return self._request(
            "POST", f"/culinary/sessions/{session_id}/waitlist", payload, headers,
        )

    def withdraw_waitlist_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/culinary/waitlist-entries/{entry_id}/withdraw", {}, headers,
        )

    def list_session_waitlist(self, session_id, headers, params=None):
        return self._request(
            "GET", f"/culinary/sessions/{session_id}/waitlist", headers=headers, params=params,
        )

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/culinary/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/culinary/waitlist-entries", headers=headers, params=params)

    # ── SubstitutionRequest ─────────────────────────────────────────
    def create_substitution(self, payload, headers):
        return self._request("POST", "/culinary/substitutions", payload, headers)

    def approve_substitution(self, sub_id, headers):
        return self._request("POST", f"/culinary/substitutions/{sub_id}/approve", {}, headers)

    def reject_substitution(self, sub_id, headers):
        return self._request("POST", f"/culinary/substitutions/{sub_id}/reject", {}, headers)

    def revert_substitution(self, sub_id, headers):
        return self._request("POST", f"/culinary/substitutions/{sub_id}/revert", {}, headers)

    def get_substitution(self, sub_id, headers):
        return self._request("GET", f"/culinary/substitutions/{sub_id}", headers=headers)

    def list_substitutions(self, headers, params=None):
        return self._request("GET", "/culinary/substitutions", headers=headers, params=params)

    # ── GiftCard ────────────────────────────────────────────────────
    def create_gift_card(self, payload, headers):
        return self._request("POST", "/culinary/gift-cards", payload, headers)

    def reload_gift_card(self, gift_card_id, amount_cents, expected_gift_card_version, headers):
        return self._request(
            "POST", f"/culinary/gift-cards/{gift_card_id}/reload",
            {"amount_cents": amount_cents,
             "expected_gift_card_version": expected_gift_card_version}, headers,
        )

    def void_gift_card(self, gift_card_id, headers):
        return self._request("POST", f"/culinary/gift-cards/{gift_card_id}/void", {}, headers)

    def get_gift_card(self, gift_card_id, headers):
        return self._request("GET", f"/culinary/gift-cards/{gift_card_id}", headers=headers)

    def list_gift_cards(self, headers, params=None):
        return self._request("GET", "/culinary/gift-cards", headers=headers, params=params)

    def list_gift_card_transactions(self, gift_card_id, headers, params=None):
        return self._request(
            "GET", f"/culinary/gift-cards/{gift_card_id}/transactions",
            headers=headers, params=params,
        )

    def get_gift_card_transaction(self, txn_id, headers):
        return self._request(
            "GET", f"/culinary/gift-card-transactions/{txn_id}", headers=headers,
        )

    def list_all_gift_card_transactions(self, headers, params=None):
        return self._request(
            "GET", "/culinary/gift-card-transactions", headers=headers, params=params,
        )

    # ── NoShowRecord ────────────────────────────────────────────────
    def get_no_show_record(self, record_id, headers):
        return self._request("GET", f"/culinary/no-show-records/{record_id}", headers=headers)

    def list_no_show_records(self, headers, params=None):
        return self._request("GET", "/culinary/no-show-records", headers=headers, params=params)

    # ── Test-driving clock ──────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
