"""API client: one method per endpoint defined in the PRD (all under
/youth-ministry)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/youth-ministry"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set-current-utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/programs/{program_id}",
                             headers=headers)

    def put_scholarship_policy(self, program_id, payload, headers):
        return self._request("PUT",
                             f"{PREFIX}/programs/{program_id}/scholarship-policy",
                             payload, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/programs/{program_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Trips
    # ------------------------------------------------------------------
    def create_trip(self, payload, headers):
        return self._request("POST", f"{PREFIX}/trips", payload, headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/trips", headers=headers,
                             params=params)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"{PREFIX}/trips/{trip_id}", headers=headers)

    def patch_trip(self, trip_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/trips/{trip_id}", payload,
                             headers)

    def open_registration(self, trip_id, headers):
        return self._request("POST",
                             f"{PREFIX}/trips/{trip_id}/open-registration",
                             {}, headers)

    def close_registration(self, trip_id, headers):
        return self._request("POST",
                             f"{PREFIX}/trips/{trip_id}/close-registration",
                             {}, headers)

    def lock_roster(self, trip_id, headers):
        return self._request("POST", f"{PREFIX}/trips/{trip_id}/lock-roster",
                             {}, headers)

    def start_trip(self, trip_id, headers):
        return self._request("POST", f"{PREFIX}/trips/{trip_id}/start", {},
                             headers)

    def debrief_trip(self, trip_id, payload, headers):
        return self._request("POST", f"{PREFIX}/trips/{trip_id}/debrief",
                             payload, headers)

    def cancel_trip(self, trip_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/trips/{trip_id}/cancel",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------
    def create_participant(self, payload, headers):
        return self._request("POST", f"{PREFIX}/participants", payload, headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/participants", headers=headers,
                             params=params)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"{PREFIX}/participants/{participant_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Registrations
    # ------------------------------------------------------------------
    def create_registration(self, payload, headers):
        return self._request("POST", f"{PREFIX}/registrations", payload, headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/registrations", headers=headers,
                             params=params)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"{PREFIX}/registrations/{registration_id}",
                             headers=headers)

    def submit_registration(self, registration_id, headers):
        return self._request("POST",
                             f"{PREFIX}/registrations/{registration_id}/submit",
                             {}, headers)

    def review_registration(self, registration_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/registrations/{registration_id}/review",
                             payload, headers)

    def promote_registration(self, registration_id, headers):
        return self._request("POST",
                             f"{PREFIX}/registrations/{registration_id}/promote",
                             {}, headers)

    def confirm_registration(self, registration_id, headers):
        return self._request("POST",
                             f"{PREFIX}/registrations/{registration_id}/confirm",
                             {}, headers)

    def withdraw_registration(self, registration_id, headers, payload=None):
        return self._request("POST",
                             f"{PREFIX}/registrations/{registration_id}/withdraw",
                             payload or {}, headers)

    def dismiss_registration(self, registration_id, payload, headers):
        return self._request("POST",
                             f"{PREFIX}/registrations/{registration_id}/dismiss",
                             payload, headers)

    # ------------------------------------------------------------------
    # Consent forms
    # ------------------------------------------------------------------
    def create_consent_form(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/consent-forms",
            payload, headers)

    def list_consent_forms(self, registration_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/registrations/{registration_id}/consent-forms",
            headers=headers, params=params)

    def review_consent_form(self, consent_form_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consent-forms/{consent_form_id}/review",
            payload, headers)

    def resubmit_consent_form(self, consent_form_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consent-forms/{consent_form_id}/resubmit",
            payload, headers)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------
    def create_payment(self, registration_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/registrations/{registration_id}/payments",
            payload, headers)

    def list_payments(self, registration_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/registrations/{registration_id}/payments",
            headers=headers, params=params)

    def refund_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/payments/{payment_id}/refund",
                             payload or {}, headers)

    # ------------------------------------------------------------------
    # Fundraising accounts and donations
    # ------------------------------------------------------------------
    def get_registration_fundraising_account(self, registration_id, headers):
        return self._request(
            "GET",
            f"{PREFIX}/registrations/{registration_id}/fundraising-account",
            headers=headers)

    def get_fundraising_account(self, account_id, headers):
        return self._request(
            "GET", f"{PREFIX}/fundraising-accounts/{account_id}",
            headers=headers)

    def create_donation(self, account_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/fundraising-accounts/{account_id}/donations",
            payload, headers)

    def list_donations(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/fundraising-accounts/{account_id}/donations",
            headers=headers, params=params)

    def refund_donation(self, donation_id, headers, payload=None):
        return self._request("POST",
                             f"{PREFIX}/donations/{donation_id}/refund",
                             payload or {}, headers)

    def apply_credit(self, account_id, headers):
        return self._request(
            "POST", f"{PREFIX}/fundraising-accounts/{account_id}/apply-credit",
            {}, headers)

    # ------------------------------------------------------------------
    # Scholarship applications
    # ------------------------------------------------------------------
    def create_scholarship_application(self, payload, headers):
        return self._request("POST", f"{PREFIX}/scholarship-applications",
                             payload, headers)

    def list_scholarship_applications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/scholarship-applications",
                             headers=headers, params=params)

    def get_scholarship_application(self, application_id, headers):
        return self._request(
            "GET", f"{PREFIX}/scholarship-applications/{application_id}",
            headers=headers)

    def decide_scholarship_application(self, application_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/scholarship-applications/{application_id}/decide",
            payload, headers)

    def appeal_scholarship_application(self, application_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/scholarship-applications/{application_id}/appeal",
            {}, headers)

    def disburse_scholarship_application(self, application_id, headers):
        return self._request(
            "POST",
            f"{PREFIX}/scholarship-applications/{application_id}/disburse",
            {}, headers)

    def rescind_scholarship_application(self, application_id, headers,
                                        payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/scholarship-applications/{application_id}/rescind",
            payload or {}, headers)

    # ------------------------------------------------------------------
    # Chaperones and background checks
    # ------------------------------------------------------------------
    def create_chaperone(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chaperones", payload, headers)

    def list_chaperones(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/chaperones", headers=headers,
                             params=params)

    def get_chaperone(self, chaperone_id, headers):
        return self._request("GET", f"{PREFIX}/chaperones/{chaperone_id}",
                             headers=headers)

    def create_background_check(self, chaperone_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/chaperones/{chaperone_id}/background-checks",
            payload or {}, headers)

    def list_background_checks(self, chaperone_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/chaperones/{chaperone_id}/background-checks",
            headers=headers, params=params)

    def advance_background_check(self, check_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/background-checks/{check_id}/advance",
            payload, headers)

    # ------------------------------------------------------------------
    # Chaperone assignments
    # ------------------------------------------------------------------
    def create_chaperone_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/chaperone-assignments",
                             payload, headers)

    def list_chaperone_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/chaperone-assignments",
                             headers=headers, params=params)

    def get_chaperone_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/chaperone-assignments/{assignment_id}",
            headers=headers)

    def respond_chaperone_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/chaperone-assignments/{assignment_id}/respond",
            payload, headers)

    def remove_chaperone_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/chaperone-assignments/{assignment_id}/remove",
            payload or {}, headers)

    # ------------------------------------------------------------------
    # Itinerary items
    # ------------------------------------------------------------------
    def create_itinerary_item(self, trip_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trips/{trip_id}/itinerary-items", payload,
            headers)

    def list_itinerary_items(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/trips/{trip_id}/itinerary-items", headers=headers,
            params=params)

    # ------------------------------------------------------------------
    # Lodging reservations
    # ------------------------------------------------------------------
    def create_lodging_reservation(self, trip_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/trips/{trip_id}/lodging-reservations", payload,
            headers)

    def list_lodging_reservations(self, trip_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/trips/{trip_id}/lodging-reservations",
            headers=headers, params=params)

    def cancel_lodging_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/lodging-reservations/{reservation_id}/cancel",
            payload or {}, headers)


api_client = ApiClient()
