"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/chair-massage"


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- Regions ---
    def create_region(self, payload, headers):
        return self._request("POST", f"{PREFIX}/regions", payload, headers)

    def list_regions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/regions", headers=headers, params=params)

    def get_region(self, region_id, headers):
        return self._request("GET", f"{PREFIX}/regions/{region_id}", headers=headers)

    # --- Corporate accounts ---
    def create_corporate_account(self, payload, headers):
        return self._request("POST", f"{PREFIX}/corporate-accounts", payload, headers)

    def list_corporate_accounts(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/corporate-accounts", headers=headers, params=params)

    def get_corporate_account(self, account_id, headers):
        return self._request("GET", f"{PREFIX}/corporate-accounts/{account_id}", headers=headers)

    def suspend_corporate_account(self, account_id, headers):
        return self._request("POST", f"{PREFIX}/corporate-accounts/{account_id}/suspend", {}, headers)

    def reactivate_corporate_account(self, account_id, headers):
        return self._request("POST", f"{PREFIX}/corporate-accounts/{account_id}/reactivate", {}, headers)

    def close_corporate_account(self, account_id, headers):
        return self._request("POST", f"{PREFIX}/corporate-accounts/{account_id}/close", {}, headers)

    def list_account_wellness_programs(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/corporate-accounts/{account_id}/wellness-programs",
            headers=headers, params=params,
        )

    def list_account_bookings(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/corporate-accounts/{account_id}/bookings",
            headers=headers, params=params,
        )

    def list_account_invoices(self, account_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/corporate-accounts/{account_id}/invoices",
            headers=headers, params=params,
        )

    # --- Wellness programs ---
    def create_wellness_program(self, payload, headers):
        return self._request("POST", f"{PREFIX}/wellness-programs", payload, headers)

    def list_wellness_programs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/wellness-programs", headers=headers, params=params)

    def get_wellness_program(self, program_id, headers):
        return self._request("GET", f"{PREFIX}/wellness-programs/{program_id}", headers=headers)

    def pause_wellness_program(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/wellness-programs/{program_id}/pause", {}, headers)

    def resume_wellness_program(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/wellness-programs/{program_id}/resume", {}, headers)

    def terminate_wellness_program(self, program_id, headers):
        return self._request("POST", f"{PREFIX}/wellness-programs/{program_id}/terminate", {}, headers)

    def list_program_bookings(self, program_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/wellness-programs/{program_id}/bookings",
            headers=headers, params=params,
        )

    def materialize_occurrence(self, program_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/wellness-programs/{program_id}/materialize-occurrence",
            payload, headers,
        )

    # --- Therapists ---
    def create_therapist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/therapists", payload, headers)

    def list_therapists(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/therapists", headers=headers, params=params)

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"{PREFIX}/therapists/{therapist_id}", headers=headers)

    def suspend_therapist(self, therapist_id, headers):
        return self._request("POST", f"{PREFIX}/therapists/{therapist_id}/suspend", {}, headers)

    def reactivate_therapist(self, therapist_id, headers):
        return self._request("POST", f"{PREFIX}/therapists/{therapist_id}/reactivate", {}, headers)

    def deactivate_therapist(self, therapist_id, headers):
        return self._request("POST", f"{PREFIX}/therapists/{therapist_id}/deactivate", {}, headers)

    def list_therapist_licenses(self, therapist_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/therapists/{therapist_id}/licenses",
            headers=headers, params=params,
        )

    def list_therapist_chair_slots(self, therapist_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/therapists/{therapist_id}/chair-slots",
            headers=headers, params=params,
        )

    def list_therapist_travel_legs(self, therapist_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/therapists/{therapist_id}/travel-legs",
            headers=headers, params=params,
        )

    def list_therapist_payout_ledger_entries(self, therapist_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/therapists/{therapist_id}/payout-ledger-entries",
            headers=headers, params=params,
        )

    # --- Therapist licenses ---
    def create_therapist_license(self, payload, headers):
        return self._request("POST", f"{PREFIX}/therapist-licenses", payload, headers)

    def list_therapist_licenses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/therapist-licenses", headers=headers, params=params)

    def get_therapist_license(self, license_id, headers):
        return self._request("GET", f"{PREFIX}/therapist-licenses/{license_id}", headers=headers)

    def suspend_therapist_license(self, license_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/therapist-licenses/{license_id}/suspend", payload, headers,
        )

    def reinstate_therapist_license(self, license_id, headers):
        return self._request(
            "POST", f"{PREFIX}/therapist-licenses/{license_id}/reinstate", {}, headers,
        )

    def revoke_therapist_license(self, license_id, headers):
        return self._request(
            "POST", f"{PREFIX}/therapist-licenses/{license_id}/revoke", {}, headers,
        )

    # --- Bookings ---
    def create_booking(self, payload, headers):
        return self._request("POST", f"{PREFIX}/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"{PREFIX}/bookings/{booking_id}", headers=headers)

    def open_scheduling(self, booking_id, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/open-scheduling", {}, headers,
        )

    def confirm_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/confirm", payload, headers,
        )

    def start_service(self, booking_id, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/start-service", {}, headers,
        )

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"{PREFIX}/bookings/{booking_id}/cancel", {}, headers)

    def list_booking_chair_slots(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bookings/{booking_id}/chair-slots",
            headers=headers, params=params,
        )

    def list_booking_slot_claims(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bookings/{booking_id}/slot-claims",
            headers=headers, params=params,
        )

    def list_booking_travel_legs(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bookings/{booking_id}/travel-legs",
            headers=headers, params=params,
        )

    def list_booking_payout_ledger_entries(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bookings/{booking_id}/payout-ledger-entries",
            headers=headers, params=params,
        )

    def list_booking_invoices(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bookings/{booking_id}/invoices",
            headers=headers, params=params,
        )

    def create_booking_invoice(self, booking_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/bookings/{booking_id}/invoices", payload, headers,
        )

    def list_booking_waivers(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/bookings/{booking_id}/waivers",
            headers=headers, params=params,
        )

    # --- Chair slots ---
    def list_chair_slots(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/chair-slots", headers=headers, params=params)

    def get_chair_slot(self, chair_slot_id, headers):
        return self._request("GET", f"{PREFIX}/chair-slots/{chair_slot_id}", headers=headers)

    def assign_chair_slot(self, chair_slot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chair-slots/{chair_slot_id}/assign", payload, headers,
        )

    def depart_chair_slot(self, chair_slot_id, headers):
        return self._request(
            "POST", f"{PREFIX}/chair-slots/{chair_slot_id}/depart", {}, headers,
        )

    def arrive_chair_slot(self, chair_slot_id, headers):
        return self._request(
            "POST", f"{PREFIX}/chair-slots/{chair_slot_id}/arrive", {}, headers,
        )

    def release_chair_slot(self, chair_slot_id, headers):
        return self._request(
            "POST", f"{PREFIX}/chair-slots/{chair_slot_id}/release", {}, headers,
        )

    def mark_chair_slot_no_show(self, chair_slot_id, headers):
        return self._request(
            "POST", f"{PREFIX}/chair-slots/{chair_slot_id}/mark-no-show", {}, headers,
        )

    def create_slot_claim(self, chair_slot_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/chair-slots/{chair_slot_id}/claims", payload, headers,
        )

    def list_chair_slot_claims(self, chair_slot_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/chair-slots/{chair_slot_id}/claims",
            headers=headers, params=params,
        )

    # --- Slot claims ---
    def get_slot_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/slot-claims/{claim_id}", headers=headers)

    def list_slot_claim_waivers(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/slot-claims/{claim_id}/waivers",
            headers=headers, params=params,
        )

    def list_slot_claim_satisfaction_surveys(self, claim_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/slot-claims/{claim_id}/satisfaction-surveys",
            headers=headers, params=params,
        )

    def check_in_slot_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/slot-claims/{claim_id}/check-in", {}, headers,
        )

    def complete_slot_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/slot-claims/{claim_id}/complete", {}, headers,
        )

    def cancel_slot_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/slot-claims/{claim_id}/cancel", {}, headers)

    def mark_slot_claim_no_show(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/slot-claims/{claim_id}/mark-no-show", {}, headers,
        )

    def sign_waiver(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/slot-claims/{claim_id}/waiver", payload, headers,
        )

    def submit_satisfaction_survey(self, claim_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/slot-claims/{claim_id}/satisfaction-surveys",
            payload, headers,
        )

    # --- Travel legs ---
    def get_travel_leg(self, leg_id, headers):
        return self._request("GET", f"{PREFIX}/travel-legs/{leg_id}", headers=headers)

    # --- Waivers ---
    def get_waiver(self, waiver_id, headers):
        return self._request("GET", f"{PREFIX}/waivers/{waiver_id}", headers=headers)

    def list_waiver_slot_claims(self, waiver_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/waivers/{waiver_id}/slot-claims",
            headers=headers, params=params,
        )

    def revoke_waiver(self, waiver_id, headers):
        return self._request("POST", f"{PREFIX}/waivers/{waiver_id}/revoke", {}, headers)

    # --- Invoices ---
    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/issue", {}, headers)

    def record_payment(self, invoice_id, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/record-payment", {}, headers,
        )

    def dispute_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/dispute", payload, headers,
        )

    def resolve_dispute(self, invoice_id, headers):
        return self._request(
            "POST", f"{PREFIX}/invoices/{invoice_id}/resolve-dispute", {}, headers,
        )

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/void", {}, headers)


api_client = ApiClient()
