"""API client: one method per endpoint defined in the Newborn Screening PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Facility ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/nbs/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request("GET", f"/nbs/facilities/{facility_id}", headers=headers)

    # --- Infant ---
    def create_infant(self, payload, headers):
        return self._request("POST", "/nbs/infants", payload, headers)

    def get_infant(self, infant_id, headers):
        return self._request("GET", f"/nbs/infants/{infant_id}", headers=headers)

    def list_infants(self, headers, params=None):
        return self._request("GET", "/nbs/infants", headers=headers, params=params)

    def record_consent(self, infant_id, payload, headers):
        return self._request(
            "POST", f"/nbs/infants/{infant_id}/consent", payload, headers
        )

    # --- Specimen ---
    def create_specimen(self, payload, headers):
        return self._request("POST", "/nbs/specimens", payload, headers)

    def get_specimen(self, specimen_id, headers):
        return self._request("GET", f"/nbs/specimens/{specimen_id}", headers=headers)

    def list_specimens(self, headers, params=None):
        return self._request("GET", "/nbs/specimens", headers=headers, params=params)

    def receive_specimen(self, specimen_id, payload, headers):
        return self._request(
            "POST", f"/nbs/specimens/{specimen_id}/receive", payload, headers
        )

    def list_recollection_orders(self, specimen_id, headers, params=None):
        return self._request(
            "GET",
            f"/nbs/specimens/{specimen_id}/recollection-orders",
            headers=headers,
            params=params,
        )

    # --- Screen ---
    def create_screen(self, payload, headers):
        return self._request("POST", "/nbs/screens", payload, headers)

    def get_screen(self, screen_id, headers):
        return self._request("GET", f"/nbs/screens/{screen_id}", headers=headers)

    def list_screens(self, headers, params=None):
        return self._request("GET", "/nbs/screens", headers=headers, params=params)

    def report_metabolic(self, screen_id, payload, headers):
        return self._request(
            "POST", f"/nbs/screens/{screen_id}/report-metabolic", payload, headers
        )

    def report_point_of_care(self, screen_id, payload, headers):
        return self._request(
            "POST", f"/nbs/screens/{screen_id}/point-of-care", payload, headers
        )

    # --- FollowUpCase ---
    def get_follow_up_case(self, case_id, headers):
        return self._request(
            "GET", f"/nbs/follow-up-cases/{case_id}", headers=headers
        )

    def list_follow_up_cases(self, headers, params=None):
        return self._request(
            "GET", "/nbs/follow-up-cases", headers=headers, params=params
        )

    def request_repeat(self, case_id, payload, headers):
        return self._request(
            "POST", f"/nbs/follow-up-cases/{case_id}/request-repeat", payload, headers
        )

    def resolve_case(self, case_id, payload, headers):
        return self._request(
            "POST", f"/nbs/follow-up-cases/{case_id}/resolve", payload, headers
        )

    # --- Referral ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/nbs/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/nbs/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/nbs/referrals", headers=headers, params=params)

    def resolve_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/nbs/referrals/{referral_id}/resolve", payload, headers
        )

    def list_confirmatory_appointments(self, referral_id, headers, params=None):
        return self._request(
            "GET",
            f"/nbs/referrals/{referral_id}/confirmatory-appointments",
            headers=headers,
            params=params,
        )

    # --- SpecialtyClinic ---
    def create_specialty_clinic(self, payload, headers):
        return self._request("POST", "/nbs/specialty-clinics", payload, headers)

    # --- ConfirmatoryAppointment ---
    def create_confirmatory_appointment(self, payload, headers):
        return self._request(
            "POST", "/nbs/confirmatory-appointments", payload, headers
        )

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST",
            f"/nbs/confirmatory-appointments/{appointment_id}/complete",
            payload,
            headers,
        )

    # --- AssayRun ---
    def create_assay_run(self, payload, headers):
        return self._request("POST", "/nbs/assay-runs", payload, headers)

    def get_assay_run(self, assay_run_id, headers):
        return self._request("GET", f"/nbs/assay-runs/{assay_run_id}", headers=headers)

    def list_assay_runs(self, headers, params=None):
        return self._request("GET", "/nbs/assay-runs", headers=headers, params=params)

    def cancel_assay_run(self, assay_run_id, payload, headers):
        return self._request(
            "POST", f"/nbs/assay-runs/{assay_run_id}/cancel", payload, headers
        )

    # --- Program ---
    def get_timeliness_summary(self, headers, params=None):
        return self._request(
            "GET", "/nbs/program/timeliness-summary", headers=headers, params=params
        )


api_client = ApiClient()
