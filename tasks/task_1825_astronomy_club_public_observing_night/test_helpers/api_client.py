"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/club/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Membership tiers
    # ------------------------------------------------------------------
    def create_membership_tier(self, payload, headers):
        return self._request("POST", "/club/membership-tiers", payload, headers)

    def get_membership_tier(self, tier_id, headers):
        return self._request("GET", f"/club/membership-tiers/{tier_id}",
                             headers=headers)

    def list_membership_tiers(self, headers, params=None):
        return self._request("GET", "/club/membership-tiers",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/club/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/club/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/club/members", headers=headers, params=params)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/club/members/{member_id}/reinstate",
                             {}, headers)

    def resign_member(self, member_id, headers):
        return self._request("POST", f"/club/members/{member_id}/resign",
                             {}, headers)

    # ------------------------------------------------------------------
    # Dues invoicing & payments
    # ------------------------------------------------------------------
    def create_dues_invoice(self, payload, headers):
        return self._request("POST", "/club/dues-invoices", payload, headers)

    def get_dues_invoice(self, invoice_id, headers):
        return self._request("GET", f"/club/dues-invoices/{invoice_id}",
                             headers=headers)

    def list_dues_invoices(self, headers, params=None):
        return self._request("GET", "/club/dues-invoices",
                             headers=headers, params=params)

    def void_dues_invoice(self, invoice_id, headers):
        return self._request("POST", f"/club/dues-invoices/{invoice_id}/void",
                             {}, headers)

    def create_dues_payment(self, payload, headers):
        return self._request("POST", "/club/dues-payments", payload, headers)

    def get_dues_payment(self, payment_id, headers):
        return self._request("GET", f"/club/dues-payments/{payment_id}",
                             headers=headers)

    def list_dues_payments(self, headers, params=None):
        return self._request("GET", "/club/dues-payments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Telescopes & maintenance
    # ------------------------------------------------------------------
    def create_telescope(self, payload, headers):
        return self._request("POST", "/club/telescopes", payload, headers)

    def get_telescope(self, telescope_id, headers):
        return self._request("GET", f"/club/telescopes/{telescope_id}",
                             headers=headers)

    def list_telescopes(self, headers, params=None):
        return self._request("GET", "/club/telescopes", headers=headers,
                             params=params)

    def update_telescope(self, telescope_id, payload, headers):
        return self._request("PUT", f"/club/telescopes/{telescope_id}",
                             payload, headers)

    def retire_telescope(self, telescope_id, headers):
        return self._request("POST", f"/club/telescopes/{telescope_id}/retire",
                             {}, headers)

    def create_maintenance_ticket(self, payload, headers):
        return self._request("POST", "/club/maintenance-tickets", payload, headers)

    def get_maintenance_ticket(self, ticket_id, headers):
        return self._request("GET", f"/club/maintenance-tickets/{ticket_id}",
                             headers=headers)

    def list_maintenance_tickets(self, headers, params=None):
        return self._request("GET", "/club/maintenance-tickets",
                             headers=headers, params=params)

    def start_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/club/maintenance-tickets/{ticket_id}/start", {}, headers)

    def submit_ticket_verification(self, ticket_id, headers):
        return self._request(
            "POST", f"/club/maintenance-tickets/{ticket_id}/submit-verification",
            {}, headers)

    def reopen_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/club/maintenance-tickets/{ticket_id}/reopen", {}, headers)

    def close_maintenance_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/club/maintenance-tickets/{ticket_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Training certifications
    # ------------------------------------------------------------------
    def create_training_certification(self, payload, headers):
        return self._request("POST", "/club/training-certifications",
                             payload, headers)

    def get_training_certification(self, cert_id, headers):
        return self._request("GET", f"/club/training-certifications/{cert_id}",
                             headers=headers)

    def list_training_certifications(self, headers, params=None):
        return self._request("GET", "/club/training-certifications",
                             headers=headers, params=params)

    def revoke_training_certification(self, cert_id, headers):
        return self._request(
            "POST", f"/club/training-certifications/{cert_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Loan reservations
    # ------------------------------------------------------------------
    def create_loan_reservation(self, payload, headers):
        return self._request("POST", "/club/loan-reservations", payload, headers)

    def get_loan_reservation(self, loan_id, headers):
        return self._request("GET", f"/club/loan-reservations/{loan_id}",
                             headers=headers)

    def list_loan_reservations(self, headers, params=None):
        return self._request("GET", "/club/loan-reservations",
                             headers=headers, params=params)

    def checkout_loan(self, loan_id, headers):
        return self._request(
            "POST", f"/club/loan-reservations/{loan_id}/checkout", {}, headers)

    def return_loan(self, loan_id, headers, damage_reported=None):
        payload = {} if damage_reported is None else {"damage_reported": damage_reported}
        return self._request(
            "POST", f"/club/loan-reservations/{loan_id}/return", payload, headers)

    def cancel_loan(self, loan_id, headers):
        return self._request(
            "POST", f"/club/loan-reservations/{loan_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Observing events
    # ------------------------------------------------------------------
    def create_observing_event(self, payload, headers):
        return self._request("POST", "/club/observing-events", payload, headers)

    def get_observing_event(self, event_id, headers):
        return self._request("GET", f"/club/observing-events/{event_id}",
                             headers=headers)

    def list_observing_events(self, headers, params=None):
        return self._request("GET", "/club/observing-events",
                             headers=headers, params=params)

    def schedule_event(self, event_id, headers):
        return self._request(
            "POST", f"/club/observing-events/{event_id}/schedule", {}, headers)

    def unschedule_event(self, event_id, headers):
        return self._request(
            "POST", f"/club/observing-events/{event_id}/unschedule", {}, headers)

    def weather_check_event(self, event_id, weather_cancellation_pct, headers):
        return self._request(
            "POST", f"/club/observing-events/{event_id}/weather-check",
            {"weather_cancellation_pct": weather_cancellation_pct}, headers)

    def confirm_event(self, event_id, expected_event_version, headers):
        return self._request(
            "POST", f"/club/observing-events/{event_id}/confirm",
            {"expected_event_version": expected_event_version}, headers)

    def cancel_event(self, event_id, cancellation_reason, headers):
        return self._request(
            "POST", f"/club/observing-events/{event_id}/cancel",
            {"cancellation_reason": cancellation_reason}, headers)

    def complete_event(self, event_id, headers):
        return self._request(
            "POST", f"/club/observing-events/{event_id}/complete", {}, headers)

    # ------------------------------------------------------------------
    # Operator assignments
    # ------------------------------------------------------------------
    def create_operator_assignment(self, payload, headers):
        return self._request("POST", "/club/event-operator-assignments",
                             payload, headers)

    def get_operator_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/club/event-operator-assignments/{assignment_id}",
            headers=headers)

    def list_operator_assignments(self, headers, params=None):
        return self._request("GET", "/club/event-operator-assignments",
                             headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/club/event-operator-assignments/{assignment_id}/accept",
            {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/club/event-operator-assignments/{assignment_id}/decline",
            {}, headers)

    def withdraw_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/club/event-operator-assignments/{assignment_id}/withdraw",
            {}, headers)

    def mark_assignment_no_show(self, assignment_id, headers):
        return self._request(
            "POST",
            f"/club/event-operator-assignments/{assignment_id}/mark-no-show",
            {}, headers)

    # ------------------------------------------------------------------
    # Group visit bookings
    # ------------------------------------------------------------------
    def create_group_visit_booking(self, payload, headers):
        return self._request("POST", "/club/group-visit-bookings", payload, headers)

    def get_group_visit_booking(self, booking_id, headers):
        return self._request("GET", f"/club/group-visit-bookings/{booking_id}",
                             headers=headers)

    def list_group_visit_bookings(self, headers, params=None):
        return self._request("GET", "/club/group-visit-bookings",
                             headers=headers, params=params)

    def confirm_group_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/club/group-visit-bookings/{booking_id}/confirm",
            {}, headers)

    def cancel_group_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/club/group-visit-bookings/{booking_id}/cancel",
            {}, headers)

    def mark_booking_no_show(self, booking_id, headers):
        return self._request(
            "POST", f"/club/group-visit-bookings/{booking_id}/mark-no-show",
            {}, headers)

    # ------------------------------------------------------------------
    # Sky quality readings & dark-sky reports
    # ------------------------------------------------------------------
    def create_sky_quality_reading(self, payload, headers):
        return self._request("POST", "/club/sky-quality-readings", payload, headers)

    def get_sky_quality_reading(self, reading_id, headers):
        return self._request("GET", f"/club/sky-quality-readings/{reading_id}",
                             headers=headers)

    def list_sky_quality_readings(self, headers, params=None):
        return self._request("GET", "/club/sky-quality-readings",
                             headers=headers, params=params)

    def create_dark_sky_report(self, payload, headers):
        return self._request("POST", "/club/dark-sky-reports", payload, headers)

    def get_dark_sky_report(self, report_id, headers):
        return self._request("GET", f"/club/dark-sky-reports/{report_id}",
                             headers=headers)

    def list_dark_sky_reports(self, headers, params=None):
        return self._request("GET", "/club/dark-sky-reports",
                             headers=headers, params=params)

    def finalize_dark_sky_report(self, report_id, headers):
        return self._request(
            "POST", f"/club/dark-sky-reports/{report_id}/finalize", {}, headers)


api_client = ApiClient()
