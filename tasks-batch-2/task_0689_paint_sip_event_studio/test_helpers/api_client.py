"""API client: one method per endpoint defined in the Paint & Sip Event Studio PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Logical clock (test-driving) ──────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Studio ────────────────────────────────────────────────────────────
    def create_studio(self, payload, headers):
        return self._request("POST", "/studio-ops/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studio-ops/studios/{studio_id}", headers=headers)

    def list_studios(self, headers, params=None):
        return self._request("GET", "/studio-ops/studios", headers=headers, params=params)

    def close_studio(self, studio_id, headers):
        return self._request("POST", f"/studio-ops/studios/{studio_id}/close", headers=headers)

    # ─── Artist ────────────────────────────────────────────────────────────
    def create_artist(self, payload, headers):
        return self._request("POST", "/studio-ops/artists", payload, headers)

    def get_artist(self, artist_id, headers):
        return self._request("GET", f"/studio-ops/artists/{artist_id}", headers=headers)

    def deactivate_artist(self, artist_id, headers):
        return self._request("POST", f"/studio-ops/artists/{artist_id}/deactivate", headers=headers)

    # ─── Customer ──────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/studio-ops/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/studio-ops/customers/{customer_id}", headers=headers)

    def adjust_credit(self, customer_id, payload, headers):
        return self._request("POST", f"/studio-ops/customers/{customer_id}/credit-adjustments", payload, headers)

    # ─── Gift cards ────────────────────────────────────────────────────────
    def create_gift_card(self, payload, headers):
        return self._request("POST", "/studio-ops/gift-cards", payload, headers)

    def get_gift_card(self, gift_card_id, headers):
        return self._request("GET", f"/studio-ops/gift-cards/{gift_card_id}", headers=headers)

    # ─── Studio events ─────────────────────────────────────────────────────
    def create_event(self, payload, headers):
        return self._request("POST", "/studio-ops/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/studio-ops/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/studio-ops/events", headers=headers, params=params)

    def schedule_event(self, event_id, headers):
        return self._request("POST", f"/studio-ops/events/{event_id}/schedule", headers=headers)

    def open_event(self, event_id, headers):
        return self._request("POST", f"/studio-ops/events/{event_id}/open", headers=headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/studio-ops/events/{event_id}/close", headers=headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/studio-ops/events/{event_id}/cancel", headers=headers)

    # ─── Artist assignments ────────────────────────────────────────────────
    def create_assignment(self, payload, headers):
        return self._request("POST", "/studio-ops/assignments", payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/studio-ops/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/studio-ops/assignments", headers=headers, params=params)

    def release_assignment(self, assignment_id, headers):
        return self._request("POST", f"/studio-ops/assignments/{assignment_id}/release", headers=headers)

    # ─── Canvas kit batches ────────────────────────────────────────────────
    def create_kit_batch(self, payload, headers):
        return self._request("POST", "/studio-ops/kit-batches", payload, headers)

    def get_kit_batch(self, batch_id, headers):
        return self._request("GET", f"/studio-ops/kit-batches/{batch_id}", headers=headers)

    def list_kit_batches(self, headers, params=None):
        return self._request("GET", "/studio-ops/kit-batches", headers=headers, params=params)

    # ─── Reservations ──────────────────────────────────────────────────────
    def create_reservation(self, payload, headers):
        return self._request("POST", "/studio-ops/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/studio-ops/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/studio-ops/reservations", headers=headers, params=params)

    def cancellation_quote(self, reservation_id, headers):
        return self._request("GET", f"/studio-ops/reservations/{reservation_id}/cancellation-quote", headers=headers)

    def pay_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/studio-ops/reservations/{reservation_id}/pay", payload, headers)

    def confirm_reservation(self, reservation_id, headers):
        return self._request("POST", f"/studio-ops/reservations/{reservation_id}/confirm", headers=headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/studio-ops/reservations/{reservation_id}/check-in", headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/studio-ops/reservations/{reservation_id}/cancel", headers=headers)

    # ─── Attendees ─────────────────────────────────────────────────────────
    def create_attendee(self, payload, headers):
        return self._request("POST", "/studio-ops/attendees", payload, headers)

    def get_attendee(self, attendee_id, headers):
        return self._request("GET", f"/studio-ops/attendees/{attendee_id}", headers=headers)

    def list_attendees(self, headers, params=None):
        return self._request("GET", "/studio-ops/attendees", headers=headers, params=params)

    # ─── Payments ──────────────────────────────────────────────────────────
    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/studio-ops/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/studio-ops/payments", headers=headers, params=params)

    # ─── Walk-ins ──────────────────────────────────────────────────────────
    def create_walk_in(self, payload, headers):
        return self._request("POST", "/studio-ops/walk-ins", payload, headers)

    def get_walk_in(self, walk_in_id, headers):
        return self._request("GET", f"/studio-ops/walk-ins/{walk_in_id}", headers=headers)

    def list_walk_ins(self, headers, params=None):
        return self._request("GET", "/studio-ops/walk-ins", headers=headers, params=params)

    def cancel_walk_in(self, walk_in_id, headers):
        return self._request("POST", f"/studio-ops/walk-ins/{walk_in_id}/cancel", headers=headers)


api_client = ApiClient()
