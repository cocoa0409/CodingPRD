"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers=headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers=headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def merge_client(self, master_id, payload, headers):
        return self._request("POST", f"/clients/{master_id}/merge", payload, headers=headers)

    def deactivate_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/deactivate", {}, headers=headers)

    # ---- Assessment ----
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers=headers)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def complete_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/complete", {}, headers=headers)

    # ---- ROIConsent ----
    def create_consent(self, payload, headers):
        return self._request("POST", "/consents", payload, headers=headers)

    def get_consent(self, consent_id, headers):
        return self._request("GET", f"/consents/{consent_id}", headers=headers)

    def list_consents(self, headers, params=None):
        return self._request("GET", "/consents", headers=headers, params=params)

    def activate_consent(self, consent_id, headers):
        return self._request("POST", f"/consents/{consent_id}/activate", {}, headers=headers)

    def revoke_consent(self, consent_id, headers):
        return self._request("POST", f"/consents/{consent_id}/revoke", {}, headers=headers)

    # ---- DiversionScreening ----
    def create_screening(self, payload, headers):
        return self._request("POST", "/screenings", payload, headers=headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"/screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", "/screenings", headers=headers, params=params)

    def resolve_screening(self, screening_id, headers):
        return self._request("POST", f"/screenings/{screening_id}/resolve", {}, headers=headers)

    # ---- Shelter ----
    def create_shelter(self, payload, headers):
        return self._request("POST", "/shelters", payload, headers=headers)

    def get_shelter(self, shelter_id, headers):
        return self._request("GET", f"/shelters/{shelter_id}", headers=headers)

    def list_shelters(self, headers, params=None):
        return self._request("GET", "/shelters", headers=headers, params=params)

    # ---- Bed ----
    def create_bed(self, payload, headers):
        return self._request("POST", "/beds", payload, headers=headers)

    def get_bed(self, bed_id, headers):
        return self._request("GET", f"/beds/{bed_id}", headers=headers)

    def list_beds(self, headers, params=None):
        return self._request("GET", "/beds", headers=headers, params=params)

    def offline_bed(self, bed_id, headers):
        return self._request("POST", f"/beds/{bed_id}/offline", {}, headers=headers)

    def online_bed(self, bed_id, headers):
        return self._request("POST", f"/beds/{bed_id}/online", {}, headers=headers)

    # ---- BedReservation ----
    def create_bed_reservation(self, payload, headers):
        return self._request("POST", "/bed-reservations", payload, headers=headers)

    def get_bed_reservation(self, reservation_id, headers):
        return self._request("GET", f"/bed-reservations/{reservation_id}", headers=headers)

    def list_bed_reservations(self, headers, params=None):
        return self._request("GET", "/bed-reservations", headers=headers, params=params)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/bed-reservations/{reservation_id}/check-in", {}, headers=headers)

    def check_out_reservation(self, reservation_id, headers):
        return self._request("POST", f"/bed-reservations/{reservation_id}/check-out", {}, headers=headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/bed-reservations/{reservation_id}/cancel", {}, headers=headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/bed-reservations/{reservation_id}/no-show", {}, headers=headers)

    # ---- WaitlistEntry ----
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/waitlist-entries", payload, headers=headers)

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def cancel_waitlist_entry(self, entry_id, headers):
        return self._request("POST", f"/waitlist-entries/{entry_id}/cancel", {}, headers=headers)

    # ---- PrioritizationEntry ----
    def create_prioritization_entry(self, payload, headers):
        return self._request("POST", "/prioritization-entries", payload, headers=headers)

    def get_prioritization_entry(self, entry_id, headers):
        return self._request("GET", f"/prioritization-entries/{entry_id}", headers=headers)

    def list_prioritization_entries(self, headers, params=None):
        return self._request("GET", "/prioritization-entries", headers=headers, params=params)

    def defer_prioritization_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/prioritization-entries/{entry_id}/defer", payload, headers=headers)

    def reactivate_prioritization_entry(self, entry_id, headers):
        return self._request("POST", f"/prioritization-entries/{entry_id}/reactivate", {}, headers=headers)

    # ---- HousingNavigator ----
    def create_housing_navigator(self, payload, headers):
        return self._request("POST", "/housing-navigators", payload, headers=headers)

    def get_housing_navigator(self, navigator_id, headers):
        return self._request("GET", f"/housing-navigators/{navigator_id}", headers=headers)

    def list_housing_navigators(self, headers, params=None):
        return self._request("GET", "/housing-navigators", headers=headers, params=params)

    # ---- Referral ----
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers=headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def accept_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/accept", {}, headers=headers)

    def decline_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/decline", {}, headers=headers)

    def enroll_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/enroll", {}, headers=headers)

    # ---- ExitRecord ----
    def create_exit_record(self, payload, headers):
        return self._request("POST", "/exit-records", payload, headers=headers)

    def get_exit_record(self, record_id, headers):
        return self._request("GET", f"/exit-records/{record_id}", headers=headers)

    def list_exit_records(self, headers, params=None):
        return self._request("GET", "/exit-records", headers=headers, params=params)

    # ---- Reports ----
    def get_apr(self, headers, params=None):
        return self._request("GET", "/reports/apr", headers=headers, params=params)


api_client = ApiClient()
