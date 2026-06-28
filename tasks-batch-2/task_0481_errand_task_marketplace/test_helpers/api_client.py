"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── TaskCategory ────────────────────────────────────────────────────
    def create_category(self, payload, headers):
        return self._request("POST", "/task-categories", payload, headers)

    def list_categories(self, headers, params=None):
        return self._request("GET", "/task-categories", headers=headers, params=params)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/task-categories/{category_id}", headers=headers)

    def retire_category(self, category_id, headers):
        return self._request("POST", f"/task-categories/{category_id}/retire", headers=headers)

    # ─── Tasker ──────────────────────────────────────────────────────────
    def create_tasker(self, payload, headers):
        return self._request("POST", "/taskers", payload, headers)

    def list_taskers(self, headers, params=None):
        return self._request("GET", "/taskers", headers=headers, params=params)

    def get_tasker(self, tasker_id, headers):
        return self._request("GET", f"/taskers/{tasker_id}", headers=headers)

    def list_tasker_skills_of(self, tasker_id, headers, params=None):
        return self._request("GET", f"/taskers/{tasker_id}/skills", headers=headers, params=params)

    # ─── TaskerSkill ─────────────────────────────────────────────────────
    def create_skill(self, payload, headers):
        return self._request("POST", "/tasker-skills", payload, headers)

    def list_skills(self, headers, params=None):
        return self._request("GET", "/tasker-skills", headers=headers, params=params)

    def get_skill(self, skill_id, headers):
        return self._request("GET", f"/tasker-skills/{skill_id}", headers=headers)

    def vet_skill(self, skill_id, headers):
        return self._request("POST", f"/tasker-skills/{skill_id}/vet", headers=headers)

    def reject_skill(self, skill_id, headers):
        return self._request("POST", f"/tasker-skills/{skill_id}/reject", headers=headers)

    # ─── AvailabilityWindow ──────────────────────────────────────────────
    def create_window(self, payload, headers):
        return self._request("POST", "/availability-windows", payload, headers)

    def list_windows(self, headers, params=None):
        return self._request("GET", "/availability-windows", headers=headers, params=params)

    def get_window(self, window_id, headers):
        return self._request("GET", f"/availability-windows/{window_id}", headers=headers)

    def close_window(self, window_id, headers):
        return self._request("POST", f"/availability-windows/{window_id}/close", headers=headers)

    # ─── Client ──────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ─── Booking ─────────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def offer_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/offer", headers=headers)

    def claim_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/claim", payload, headers)

    def depart_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/depart", headers=headers)

    def start_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/start", headers=headers)

    def complete_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    def propose_reschedule(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule/propose", payload, headers)

    def accept_reschedule(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule/accept", payload, headers)

    def decline_reschedule(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule/decline", headers=headers)

    def get_settlement(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/settlement", headers=headers)

    def get_cancellation(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}/cancellation", headers=headers)

    def rebook(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/rebook", payload, headers)

    # ─── ChatMessage ─────────────────────────────────────────────────────
    def post_message(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/messages", payload, headers)

    def list_messages(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/messages", headers=headers, params=params)

    # ─── RecurringSeries ─────────────────────────────────────────────────
    def create_series(self, payload, headers):
        return self._request("POST", "/recurring-series", payload, headers)

    def list_series(self, headers, params=None):
        return self._request("GET", "/recurring-series", headers=headers, params=params)

    def get_series(self, series_id, headers):
        return self._request("GET", f"/recurring-series/{series_id}", headers=headers)

    def end_series(self, series_id, headers):
        return self._request("POST", f"/recurring-series/{series_id}/end", headers=headers)

    # ─── Review ──────────────────────────────────────────────────────────
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def hide_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/hide", headers=headers)

    def restore_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/restore", headers=headers)

    def remove_review(self, review_id, headers):
        return self._request("POST", f"/reviews/{review_id}/remove", headers=headers)

    # ─── TrustIncident ───────────────────────────────────────────────────
    def create_incident(self, payload, headers):
        return self._request("POST", "/trust-incidents", payload, headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/trust-incidents", headers=headers, params=params)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/trust-incidents/{incident_id}", headers=headers)

    def uphold_incident(self, incident_id, headers):
        return self._request("POST", f"/trust-incidents/{incident_id}/uphold", headers=headers)

    def dismiss_incident(self, incident_id, headers):
        return self._request("POST", f"/trust-incidents/{incident_id}/dismiss", headers=headers)


api_client = ApiClient()
