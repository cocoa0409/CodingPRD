"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Wedding ─────────────────────────────────────────────────────
    def create_wedding(self, payload, headers):
        return self._request("POST", "/weddings", payload, headers)

    def get_wedding(self, wedding_id, headers):
        return self._request("GET", f"/weddings/{wedding_id}", headers=headers)

    def list_weddings(self, headers, params=None):
        return self._request("GET", "/weddings", headers=headers, params=params)

    def open_rsvp(self, wedding_id, headers):
        return self._request("POST", f"/weddings/{wedding_id}/open-rsvp", {}, headers)

    def close_rsvp(self, wedding_id, headers):
        return self._request("POST", f"/weddings/{wedding_id}/close-rsvp", {}, headers)

    def finalize_seating(self, wedding_id, expected_wedding_version, headers):
        return self._request(
            "POST", f"/weddings/{wedding_id}/finalize-seating",
            {"expected_wedding_version": expected_wedding_version}, headers,
        )

    def archive_wedding(self, wedding_id, headers):
        return self._request("POST", f"/weddings/{wedding_id}/archive", {}, headers)

    def get_meal_summary(self, wedding_id, headers):
        return self._request("GET", f"/weddings/{wedding_id}/meal-summary", headers=headers)

    def auto_seat_dry_run(self, wedding_id, headers):
        return self._request("GET", f"/weddings/{wedding_id}/auto-seat", headers=headers)

    def auto_seat_commit(self, wedding_id, headers):
        return self._request("POST", f"/weddings/{wedding_id}/auto-seat", {}, headers)

    def get_thank_you_report(self, wedding_id, headers):
        return self._request("GET", f"/weddings/{wedding_id}/thank-you-report", headers=headers)

    # ── MealOption ──────────────────────────────────────────────────
    def create_meal_option(self, wedding_id, payload, headers):
        return self._request(
            "POST", f"/weddings/{wedding_id}/meal-options", payload, headers,
        )

    def list_meal_options(self, wedding_id, headers, params=None):
        return self._request(
            "GET", f"/weddings/{wedding_id}/meal-options",
            headers=headers, params=params,
        )

    def get_meal_option(self, meal_option_id, headers):
        return self._request(
            "GET", f"/meal-options/{meal_option_id}", headers=headers,
        )

    # ── Table ───────────────────────────────────────────────────────
    def create_table(self, wedding_id, payload, headers):
        return self._request(
            "POST", f"/weddings/{wedding_id}/tables", payload, headers,
        )

    def list_tables(self, wedding_id, headers, params=None):
        return self._request(
            "GET", f"/weddings/{wedding_id}/tables", headers=headers, params=params,
        )

    def get_table(self, table_id, headers):
        return self._request("GET", f"/tables/{table_id}", headers=headers)

    # ── Guest ───────────────────────────────────────────────────────
    def create_guest(self, wedding_id, payload, headers):
        return self._request(
            "POST", f"/weddings/{wedding_id}/guests", payload, headers,
        )

    def list_wedding_guests(self, wedding_id, headers, params=None):
        return self._request(
            "GET", f"/weddings/{wedding_id}/guests", headers=headers, params=params,
        )

    def list_guests(self, headers, params=None):
        return self._request("GET", "/guests", headers=headers, params=params)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def guest_rsvp(self, guest_id, payload, headers):
        return self._request(
            "POST", f"/guests/{guest_id}/rsvp", payload, headers,
        )

    def revoke_guest_rsvp(self, guest_id, headers):
        return self._request(
            "POST", f"/guests/{guest_id}/revoke-rsvp", {}, headers,
        )

    # ── PlusOne ─────────────────────────────────────────────────────
    def create_plus_one(self, guest_id, payload, headers):
        return self._request(
            "POST", f"/guests/{guest_id}/plus-ones", payload, headers,
        )

    def list_guest_plus_ones(self, guest_id, headers, params=None):
        return self._request(
            "GET", f"/guests/{guest_id}/plus-ones",
            headers=headers, params=params,
        )

    def list_plus_ones(self, headers, params=None):
        return self._request("GET", "/plus-ones", headers=headers, params=params)

    def get_plus_one(self, plus_one_id, headers):
        return self._request("GET", f"/plus-ones/{plus_one_id}", headers=headers)

    def plus_one_rsvp(self, plus_one_id, payload, headers):
        return self._request(
            "POST", f"/plus-ones/{plus_one_id}/rsvp", payload, headers,
        )

    def delete_plus_one(self, plus_one_id, headers):
        return self._request("DELETE", f"/plus-ones/{plus_one_id}", headers=headers)

    # ── SeatingAssignment ───────────────────────────────────────────
    def create_seating_assignment(self, payload, headers):
        return self._request("POST", "/seating-assignments", payload, headers)

    def list_seating_assignments(self, headers, params=None):
        return self._request(
            "GET", "/seating-assignments", headers=headers, params=params,
        )

    def get_seating_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/seating-assignments/{assignment_id}", headers=headers,
        )

    def delete_seating_assignment(self, assignment_id, headers):
        return self._request(
            "DELETE", f"/seating-assignments/{assignment_id}", headers=headers,
        )

    # ── RegistryItem ────────────────────────────────────────────────
    def create_registry_item(self, wedding_id, payload, headers):
        return self._request(
            "POST", f"/weddings/{wedding_id}/registry-items", payload, headers,
        )

    def list_registry_items(self, wedding_id, headers, params=None):
        return self._request(
            "GET", f"/weddings/{wedding_id}/registry-items",
            headers=headers, params=params,
        )

    def get_registry_item(self, registry_item_id, headers):
        return self._request(
            "GET", f"/registry-items/{registry_item_id}", headers=headers,
        )

    # ── Purchase ────────────────────────────────────────────────────
    def create_purchase(self, registry_item_id, payload, headers):
        return self._request(
            "POST", f"/registry-items/{registry_item_id}/purchases",
            payload, headers,
        )

    def list_registry_item_purchases(self, registry_item_id, headers, params=None):
        return self._request(
            "GET", f"/registry-items/{registry_item_id}/purchases",
            headers=headers, params=params,
        )

    def get_purchase(self, purchase_id, headers):
        return self._request("GET", f"/purchases/{purchase_id}", headers=headers)

    def list_purchases(self, headers, params=None):
        return self._request("GET", "/purchases", headers=headers, params=params)

    def cancel_purchase(self, purchase_id, expected_registry_item_version, headers):
        return self._request(
            "POST", f"/purchases/{purchase_id}/cancel-duplicate",
            {"expected_registry_item_version": expected_registry_item_version},
            headers,
        )

    def promote_purchase(self, purchase_id, expected_registry_item_version, headers):
        return self._request(
            "POST", f"/purchases/{purchase_id}/promote",
            {"expected_registry_item_version": expected_registry_item_version},
            headers,
        )

    # ── ThankYouNote ────────────────────────────────────────────────
    def list_thank_you_notes(self, headers, params=None):
        return self._request(
            "GET", "/thank-you-notes", headers=headers, params=params,
        )

    def get_thank_you_note(self, note_id, headers):
        return self._request(
            "GET", f"/thank-you-notes/{note_id}", headers=headers,
        )

    def draft_thank_you_note(self, note_id, drafted_body, headers):
        return self._request(
            "POST", f"/thank-you-notes/{note_id}/draft",
            {"drafted_body": drafted_body}, headers,
        )

    def send_thank_you_note(self, note_id, headers):
        return self._request(
            "POST", f"/thank-you-notes/{note_id}/send", {}, headers,
        )

    # ── Clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
