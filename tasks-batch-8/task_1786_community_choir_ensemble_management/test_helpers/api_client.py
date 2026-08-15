"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/v1/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Seasons
    # ------------------------------------------------------------------
    def create_season(self, payload, headers):
        return self._request("POST", "/v1/seasons", payload, headers)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/v1/seasons/{season_id}", headers=headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/v1/seasons", headers=headers, params=params)

    def patch_season(self, season_id, payload, headers):
        return self._request("PATCH", f"/v1/seasons/{season_id}", payload, headers)

    def set_season_posture(self, season_id, posture, headers):
        return self._request("POST", f"/v1/seasons/{season_id}/posture",
                             {"posture": posture}, headers)

    def checkpoint_season(self, season_id, expected_season_version, headers):
        return self._request("POST", f"/v1/seasons/{season_id}/checkpoint",
                             {"expected_season_version": expected_season_version},
                             headers)

    # ------------------------------------------------------------------
    # Sections
    # ------------------------------------------------------------------
    def create_section(self, payload, headers):
        return self._request("POST", "/v1/sections", payload, headers)

    def get_section(self, section_id, headers):
        return self._request("GET", f"/v1/sections/{section_id}", headers=headers)

    def list_sections(self, headers, params=None):
        return self._request("GET", "/v1/sections", headers=headers, params=params)

    def patch_section(self, section_id, payload, headers):
        return self._request("PATCH", f"/v1/sections/{section_id}", payload, headers)

    # ------------------------------------------------------------------
    # Members
    # ------------------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/v1/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/v1/members", headers=headers, params=params)

    def set_member_status(self, member_id, action, headers):
        return self._request("POST", f"/v1/members/{member_id}/status",
                             {"action": action}, headers)

    def resign_member(self, member_id, headers):
        return self._request("POST", f"/v1/members/{member_id}/resign", {}, headers)

    # ------------------------------------------------------------------
    # Auditions
    # ------------------------------------------------------------------
    def create_audition(self, payload, headers):
        return self._request("POST", "/v1/auditions", payload, headers)

    def get_audition(self, audition_id, headers):
        return self._request("GET", f"/v1/auditions/{audition_id}", headers=headers)

    def list_auditions(self, headers, params=None):
        return self._request("GET", "/v1/auditions", headers=headers, params=params)

    def score_audition(self, audition_id, payload, headers):
        return self._request("POST", f"/v1/auditions/{audition_id}/score",
                             payload, headers)

    def cancel_audition(self, audition_id, headers):
        return self._request("POST", f"/v1/auditions/{audition_id}/cancel",
                             {}, headers)

    def decide_audition(self, audition_id, payload, headers):
        return self._request("POST", f"/v1/auditions/{audition_id}/decision",
                             payload, headers)

    # ------------------------------------------------------------------
    # Dues invoices and payments
    # ------------------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/v1/dues-invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/dues-invoices/{invoice_id}",
                             headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/v1/dues-invoices", headers=headers,
                             params=params)

    def create_payment(self, payload, headers):
        return self._request("POST", "/v1/dues-payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/v1/dues-payments/{payment_id}",
                             headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/v1/dues-payments", headers=headers,
                             params=params)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/v1/dues-payments/{payment_id}/refund",
                             {}, headers)

    # ------------------------------------------------------------------
    # Scholarship grants
    # ------------------------------------------------------------------
    def create_grant(self, payload, headers):
        return self._request("POST", "/v1/scholarship-grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/v1/scholarship-grants/{grant_id}",
                             headers=headers)

    def list_grants(self, headers, params=None):
        return self._request("GET", "/v1/scholarship-grants", headers=headers,
                             params=params)

    def decide_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/v1/scholarship-grants/{grant_id}/decision",
                             payload, headers)

    def apply_grant(self, grant_id, payload, headers):
        return self._request("POST", f"/v1/scholarship-grants/{grant_id}/apply",
                             payload, headers)

    def revoke_grant(self, grant_id, headers):
        return self._request("POST", f"/v1/scholarship-grants/{grant_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # Rehearsals and attendance
    # ------------------------------------------------------------------
    def create_rehearsal(self, payload, headers):
        return self._request("POST", "/v1/rehearsals", payload, headers)

    def get_rehearsal(self, rehearsal_id, headers):
        return self._request("GET", f"/v1/rehearsals/{rehearsal_id}",
                             headers=headers)

    def list_rehearsals(self, headers, params=None):
        return self._request("GET", "/v1/rehearsals", headers=headers,
                             params=params)

    def cancel_rehearsal(self, rehearsal_id, headers):
        return self._request("POST", f"/v1/rehearsals/{rehearsal_id}/cancel",
                             {}, headers)

    def record_attendance(self, rehearsal_id, records, headers):
        return self._request("POST", f"/v1/rehearsals/{rehearsal_id}/attendance",
                             {"records": records}, headers)

    def get_attendance_record(self, record_id, headers):
        return self._request("GET", f"/v1/attendance-records/{record_id}",
                             headers=headers)

    def list_attendance_records(self, headers, params=None):
        return self._request("GET", "/v1/attendance-records", headers=headers,
                             params=params)

    def excuse_attendance_record(self, record_id, headers):
        return self._request("POST",
                             f"/v1/attendance-records/{record_id}/excuse",
                             {}, headers)

    # ------------------------------------------------------------------
    # Music library
    # ------------------------------------------------------------------
    def create_score(self, payload, headers):
        return self._request("POST", "/v1/music-scores", payload, headers)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/v1/music-scores/{score_id}", headers=headers)

    def list_scores(self, headers, params=None):
        return self._request("GET", "/v1/music-scores", headers=headers,
                             params=params)

    def retire_score(self, score_id, headers):
        return self._request("POST", f"/v1/music-scores/{score_id}/retire",
                             {}, headers)

    def create_checkout(self, payload, headers):
        return self._request("POST", "/v1/score-checkouts", payload, headers)

    def get_checkout(self, checkout_id, headers):
        return self._request("GET", f"/v1/score-checkouts/{checkout_id}",
                             headers=headers)

    def list_checkouts(self, headers, params=None):
        return self._request("GET", "/v1/score-checkouts", headers=headers,
                             params=params)

    def return_checkout(self, checkout_id, headers):
        return self._request("POST", f"/v1/score-checkouts/{checkout_id}/return",
                             {}, headers)

    def mark_checkout_lost(self, checkout_id, headers):
        return self._request("POST",
                             f"/v1/score-checkouts/{checkout_id}/mark-lost",
                             {}, headers)

    # ------------------------------------------------------------------
    # Venues, concerts, bookings
    # ------------------------------------------------------------------
    def create_venue(self, payload, headers):
        return self._request("POST", "/v1/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/v1/venues/{venue_id}", headers=headers)

    def list_venues(self, headers, params=None):
        return self._request("GET", "/v1/venues", headers=headers, params=params)

    def archive_venue(self, venue_id, headers):
        return self._request("POST", f"/v1/venues/{venue_id}/archive", {}, headers)

    def create_concert(self, payload, headers):
        return self._request("POST", "/v1/concerts", payload, headers)

    def get_concert(self, concert_id, headers):
        return self._request("GET", f"/v1/concerts/{concert_id}", headers=headers)

    def list_concerts(self, headers, params=None):
        return self._request("GET", "/v1/concerts", headers=headers, params=params)

    def transition_concert(self, concert_id, action, headers):
        return self._request("POST", f"/v1/concerts/{concert_id}/transition",
                             {"action": action}, headers)

    def create_booking(self, payload, headers):
        return self._request("POST", "/v1/venue-bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/v1/venue-bookings/{booking_id}",
                             headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/v1/venue-bookings", headers=headers,
                             params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/venue-bookings/{booking_id}/confirm",
                             {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/venue-bookings/{booking_id}/decline",
                             {}, headers)

    def release_booking(self, booking_id, headers):
        return self._request("POST", f"/v1/venue-bookings/{booking_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Program pieces
    # ------------------------------------------------------------------
    def create_piece(self, payload, headers):
        return self._request("POST", "/v1/program-pieces", payload, headers)

    def get_piece(self, piece_id, headers):
        return self._request("GET", f"/v1/program-pieces/{piece_id}",
                             headers=headers)

    def list_pieces(self, headers, params=None):
        return self._request("GET", "/v1/program-pieces", headers=headers,
                             params=params)

    def patch_piece(self, piece_id, payload, headers):
        return self._request("PATCH", f"/v1/program-pieces/{piece_id}",
                             payload, headers)

    def confirm_piece(self, piece_id, headers):
        return self._request("POST", f"/v1/program-pieces/{piece_id}/confirm",
                             {}, headers)

    def void_piece(self, piece_id, headers):
        return self._request("POST", f"/v1/program-pieces/{piece_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Guest contracts
    # ------------------------------------------------------------------
    def create_contract(self, payload, headers):
        return self._request("POST", "/v1/guest-contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/v1/guest-contracts/{contract_id}",
                             headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/v1/guest-contracts", headers=headers,
                             params=params)

    def offer_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/v1/guest-contracts/{contract_id}/offer",
                             payload, headers)

    def counter_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/v1/guest-contracts/{contract_id}/counter",
                             payload, headers)

    def accept_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/guest-contracts/{contract_id}/accept",
                             {}, headers)

    def decline_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/guest-contracts/{contract_id}/decline",
                             {}, headers)

    def approve_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/guest-contracts/{contract_id}/approve",
                             {}, headers)

    def pay_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/guest-contracts/{contract_id}/pay",
                             {}, headers)

    def cancel_contract(self, contract_id, headers):
        return self._request("POST", f"/v1/guest-contracts/{contract_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Tours and registrations
    # ------------------------------------------------------------------
    def create_tour(self, payload, headers):
        return self._request("POST", "/v1/tours", payload, headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/v1/tours/{tour_id}", headers=headers)

    def list_tours(self, headers, params=None):
        return self._request("GET", "/v1/tours", headers=headers, params=params)

    def transition_tour(self, tour_id, action, headers):
        return self._request("POST", f"/v1/tours/{tour_id}/transition",
                             {"action": action}, headers)

    def create_registration(self, payload, headers):
        return self._request("POST", "/v1/tour-registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/v1/tour-registrations/{registration_id}",
                             headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/v1/tour-registrations", headers=headers,
                             params=params)

    def confirm_registration(self, registration_id, headers):
        return self._request("POST",
                             f"/v1/tour-registrations/{registration_id}/confirm",
                             {}, headers)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST",
                             f"/v1/tour-registrations/{registration_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Committees and pledges
    # ------------------------------------------------------------------
    def create_committee(self, payload, headers):
        return self._request("POST", "/v1/committees", payload, headers)

    def get_committee(self, committee_id, headers):
        return self._request("GET", f"/v1/committees/{committee_id}",
                             headers=headers)

    def list_committees(self, headers, params=None):
        return self._request("GET", "/v1/committees", headers=headers,
                             params=params)

    def transition_committee(self, committee_id, action, headers):
        return self._request("POST", f"/v1/committees/{committee_id}/transition",
                             {"action": action}, headers)

    def create_pledge(self, payload, headers):
        return self._request("POST", "/v1/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/v1/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/v1/pledges", headers=headers, params=params)

    def fulfill_pledge(self, pledge_id, headers):
        return self._request("POST", f"/v1/pledges/{pledge_id}/fulfill",
                             {}, headers)

    def cancel_pledge(self, pledge_id, headers):
        return self._request("POST", f"/v1/pledges/{pledge_id}/cancel",
                             {}, headers)

    def refund_pledge(self, pledge_id, headers):
        return self._request("POST", f"/v1/pledges/{pledge_id}/refund",
                             {}, headers)


api_client = ApiClient()
