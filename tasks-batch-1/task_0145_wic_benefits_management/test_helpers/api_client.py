"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
envelope, headers, and base URL. Every entity is a top-level collection (flat
topology) and relationships are carried as foreign keys in request bodies.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------- test-driving clock -----------------------
    def set_current_utc(self, agency_id, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"agency_id": agency_id, "to_iso8601": to_iso8601}, headers,
        )

    def advance_expirations(self, agency_id, headers):
        return self._request(
            "POST", "/_clock/advance-expirations", {"agency_id": agency_id}, headers,
        )

    # ----------------------- Agency -----------------------
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    # ----------------------- Clinic -----------------------
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def list_clinics(self, headers, params=None):
        return self._request("GET", "/clinics", headers=headers, params=params)

    # ----------------------- Vendor -----------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def authorize_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/authorize", headers=headers)

    def record_vendor_violation(self, vendor_id, points, headers):
        return self._request(
            "POST", f"/vendors/{vendor_id}/record-violation", {"points": points}, headers,
        )

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reinstate", headers=headers)

    def terminate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/terminate", headers=headers)

    # ----------------------- Household -----------------------
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def list_households(self, headers, params=None):
        return self._request("GET", "/households", headers=headers, params=params)

    # ----------------------- Participant -----------------------
    def create_participant(self, payload, headers):
        return self._request("POST", "/participants", payload, headers)

    def get_participant(self, participant_id, headers):
        return self._request("GET", f"/participants/{participant_id}", headers=headers)

    def list_participants(self, headers, params=None):
        return self._request("GET", "/participants", headers=headers, params=params)

    # ----------------------- Application -----------------------
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}", headers=headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers, params=params)

    def determine_income(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/determine-income", headers=headers,
        )

    def assess_risk(self, application_id, risk_factor_codes, headers):
        return self._request(
            "POST", f"/applications/{application_id}/assess-risk",
            {"risk_factor_codes": risk_factor_codes}, headers,
        )

    def approve_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/approve", headers=headers,
        )

    def deny_application(self, application_id, headers):
        return self._request(
            "POST", f"/applications/{application_id}/deny", headers=headers,
        )

    # ----------------------- IncomeRecord -----------------------
    def create_income_record(self, payload, headers):
        return self._request("POST", "/income-records", payload, headers)

    def get_income_record(self, income_record_id, headers):
        return self._request("GET", f"/income-records/{income_record_id}", headers=headers)

    def list_income_records(self, headers, params=None):
        return self._request("GET", "/income-records", headers=headers, params=params)

    # ----------------------- Certification -----------------------
    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/certifications", headers=headers, params=params)

    def suspend_certification(self, certification_id, headers):
        return self._request(
            "POST", f"/certifications/{certification_id}/suspend", headers=headers,
        )

    def reinstate_certification(self, certification_id, headers):
        return self._request(
            "POST", f"/certifications/{certification_id}/reinstate", headers=headers,
        )

    def terminate_certification(self, certification_id, headers):
        return self._request(
            "POST", f"/certifications/{certification_id}/terminate", headers=headers,
        )

    # ----------------------- FoodPrescription -----------------------
    def create_food_prescription(self, payload, headers):
        return self._request("POST", "/food-prescriptions", payload, headers)

    def get_food_prescription(self, prescription_id, headers):
        return self._request(
            "GET", f"/food-prescriptions/{prescription_id}", headers=headers,
        )

    def list_food_prescriptions(self, headers, params=None):
        return self._request("GET", "/food-prescriptions", headers=headers, params=params)

    # ----------------------- EbtAccount -----------------------
    def get_ebt_account(self, ebt_account_id, headers):
        return self._request("GET", f"/ebt-accounts/{ebt_account_id}", headers=headers)

    def list_ebt_accounts(self, headers, params=None):
        return self._request("GET", "/ebt-accounts", headers=headers, params=params)

    # ----------------------- Redemption -----------------------
    def create_redemption(self, payload, headers):
        return self._request("POST", "/redemptions", payload, headers)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/redemptions/{redemption_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/redemptions", headers=headers, params=params)

    # ----------------------- ClinicAppointment -----------------------
    def create_clinic_appointment(self, payload, headers):
        return self._request("POST", "/clinic-appointments", payload, headers)

    def get_clinic_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/clinic-appointments/{appointment_id}", headers=headers,
        )

    def list_clinic_appointments(self, headers, params=None):
        return self._request("GET", "/clinic-appointments", headers=headers, params=params)

    def reschedule_clinic_appointment(self, appointment_id, start_utc, end_utc, headers):
        return self._request(
            "PATCH", f"/clinic-appointments/{appointment_id}",
            {"start_utc": start_utc, "end_utc": end_utc}, headers,
        )

    def confirm_clinic_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appointment_id}/confirm", headers=headers,
        )

    def complete_clinic_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appointment_id}/complete", headers=headers,
        )

    def no_show_clinic_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appointment_id}/no-show", headers=headers,
        )

    def cancel_clinic_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/clinic-appointments/{appointment_id}/cancel", headers=headers,
        )

    # ----------------------- PeerSupportSession -----------------------
    def create_peer_session(self, payload, headers):
        return self._request("POST", "/peer-sessions", payload, headers)

    def get_peer_session(self, session_id, headers):
        return self._request("GET", f"/peer-sessions/{session_id}", headers=headers)

    def list_peer_sessions(self, headers, params=None):
        return self._request("GET", "/peer-sessions", headers=headers, params=params)

    def complete_peer_session(self, session_id, headers):
        return self._request(
            "POST", f"/peer-sessions/{session_id}/complete", headers=headers,
        )

    def cancel_peer_session(self, session_id, headers):
        return self._request(
            "POST", f"/peer-sessions/{session_id}/cancel", headers=headers,
        )


api_client = ApiClient()
