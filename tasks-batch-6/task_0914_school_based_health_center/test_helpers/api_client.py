"""API client: one method per endpoint defined in the PRD.

Every path already carries the `/sbhc` service prefix, exactly as the PRD's
endpoint table spells it.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/sbhc"


class ApiClient(GenericApiClient):
    # ── Logical clock and the daily epoch advance ────────────────────────────

    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    def daily_sweep(self, headers, payload=None):
        return self._request("POST", f"{PREFIX}/operations/daily-sweep", payload or {}, headers)

    # ── Schools ─────────────────────────────────────────────────────────────

    def create_school(self, payload, headers):
        return self._request("POST", f"{PREFIX}/schools", payload, headers)

    def get_school(self, school_id, headers):
        return self._request("GET", f"{PREFIX}/schools/{school_id}", headers=headers)

    def set_school_program_status(self, school_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/schools/{school_id}/program-status", payload, headers
        )

    # ── Clinicians ──────────────────────────────────────────────────────────

    def create_clinician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clinicians", payload, headers)

    def get_clinician(self, clinician_id, headers):
        return self._request("GET", f"{PREFIX}/clinicians/{clinician_id}", headers=headers)

    # ── Students, financial profile, exemption, guardians ───────────────────

    def create_student(self, payload, headers):
        return self._request("POST", f"{PREFIX}/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"{PREFIX}/students/{student_id}", headers=headers)

    def update_financial_profile(self, student_id, payload, headers):
        return self._request(
            "PATCH", f"{PREFIX}/students/{student_id}/financial-profile", payload, headers
        )

    def set_immunization_exemption(self, student_id, payload, headers):
        return self._request(
            "PUT", f"{PREFIX}/students/{student_id}/immunization-exemption", payload, headers
        )

    def add_guardian(self, student_id, payload, headers):
        return self._request("POST", f"{PREFIX}/students/{student_id}/guardians", payload, headers)

    def list_guardians(self, student_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/students/{student_id}/guardians", headers=headers, params=params
        )

    def set_notification_preference(self, guardian_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/guardians/{guardian_id}/notification-preference", payload, headers
        )

    # ── Enrollments ─────────────────────────────────────────────────────────

    def create_enrollment(self, student_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/students/{student_id}/enrollments", payload, headers
        )

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"{PREFIX}/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/enrollments", headers=headers, params=params)

    def activate_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/activate", payload or {}, headers
        )

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/withdraw", payload, headers
        )

    def reinstate_enrollment(self, enrollment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/enrollments/{enrollment_id}/reinstate", payload or {}, headers
        )

    # ── Consents ────────────────────────────────────────────────────────────

    def create_consent(self, student_id, payload, headers):
        return self._request("POST", f"{PREFIX}/students/{student_id}/consents", payload, headers)

    def list_consents(self, student_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/students/{student_id}/consents", headers=headers, params=params
        )

    def revoke_consent(self, consent_id, payload, headers):
        return self._request("POST", f"{PREFIX}/consents/{consent_id}/revoke", payload, headers)

    # ── Encounters ──────────────────────────────────────────────────────────

    def create_visit(self, payload, headers):
        return self._request("POST", f"{PREFIX}/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/visits", headers=headers, params=params)

    def start_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"{PREFIX}/visits/{visit_id}/start", payload or {}, headers)

    def complete_visit(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/visits/{visit_id}/complete", payload, headers)

    def close_visit_unfulfilled(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/visits/{visit_id}/close-unfulfilled", payload, headers
        )

    # ── Sports-physical clearances ──────────────────────────────────────────

    def create_sports_clearance(self, visit_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/visits/{visit_id}/sports-clearances", payload, headers
        )

    def get_sports_clearance(self, clearance_id, headers):
        return self._request("GET", f"{PREFIX}/sports-clearances/{clearance_id}", headers=headers)

    def list_sports_clearances(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/sports-clearances", headers=headers, params=params)

    def reevaluate_sports_clearance(self, clearance_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/sports-clearances/{clearance_id}/re-evaluate", payload, headers
        )

    # ── Immunization doses ──────────────────────────────────────────────────

    def create_immunization_dose(self, student_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/students/{student_id}/immunization-doses", payload, headers
        )

    def get_immunization_dose(self, dose_id, headers):
        return self._request("GET", f"{PREFIX}/immunization-doses/{dose_id}", headers=headers)

    def list_immunization_doses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/immunization-doses", headers=headers, params=params)

    def void_immunization_dose(self, dose_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/immunization-doses/{dose_id}/void", payload, headers
        )

    # ── Screenings ──────────────────────────────────────────────────────────

    def create_screening(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/visits/{visit_id}/screenings", payload, headers)

    def get_screening(self, screening_id, headers):
        return self._request("GET", f"{PREFIX}/screenings/{screening_id}", headers=headers)

    def list_screenings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/screenings", headers=headers, params=params)

    # ── Referrals ───────────────────────────────────────────────────────────

    def create_referral(self, student_id, payload, headers):
        return self._request("POST", f"{PREFIX}/students/{student_id}/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"{PREFIX}/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/referrals", headers=headers, params=params)

    def log_outreach_attempt(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/outreach-attempts", payload, headers
        )

    def report_back_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/referrals/{referral_id}/report-back", payload, headers
        )

    def close_referral(self, referral_id, payload, headers):
        return self._request("POST", f"{PREFIX}/referrals/{referral_id}/close", payload, headers)

    # ── Billable charges ────────────────────────────────────────────────────

    def get_charge(self, charge_id, headers):
        return self._request("GET", f"{PREFIX}/charges/{charge_id}", headers=headers)

    def list_charges(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/charges", headers=headers, params=params)

    def submit_claim(self, charge_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/submit-claim", payload or {}, headers
        )

    def adjudicate_charge(self, charge_id, payload, headers):
        return self._request("POST", f"{PREFIX}/charges/{charge_id}/adjudicate", payload, headers)

    def appeal_charge(self, charge_id, payload, headers):
        return self._request("POST", f"{PREFIX}/charges/{charge_id}/appeal", payload, headers)

    def write_off_charge(self, charge_id, payload, headers):
        return self._request("POST", f"{PREFIX}/charges/{charge_id}/write-off", payload, headers)

    def record_patient_payment(self, charge_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/charges/{charge_id}/record-patient-payment", payload, headers
        )

    def reverse_charge(self, charge_id, payload, headers):
        return self._request("POST", f"{PREFIX}/charges/{charge_id}/reverse", payload, headers)

    # ── Parent notifications ────────────────────────────────────────────────

    def get_notification(self, notification_id, headers):
        return self._request("GET", f"{PREFIX}/notifications/{notification_id}", headers=headers)

    def list_notifications(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/notifications", headers=headers, params=params)

    def deliver_notification(self, notification_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/notifications/{notification_id}/deliver", payload, headers
        )

    def acknowledge_notification(self, notification_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/notifications/{notification_id}/acknowledge", payload or {}, headers
        )

    # ── Telehealth sessions ─────────────────────────────────────────────────

    def create_telehealth_session(self, payload, headers):
        return self._request("POST", f"{PREFIX}/telehealth-sessions", payload, headers)

    def get_telehealth_session(self, session_id, headers):
        return self._request("GET", f"{PREFIX}/telehealth-sessions/{session_id}", headers=headers)

    def list_telehealth_sessions(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/telehealth-sessions", headers=headers, params=params)

    def complete_telehealth_session(self, session_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/telehealth-sessions/{session_id}/complete", payload or {}, headers
        )

    def close_telehealth_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/telehealth-sessions/{session_id}/close", payload, headers
        )

    def reschedule_telehealth_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/telehealth-sessions/{session_id}/reschedule", payload, headers
        )

    # ── Aggregate reports ───────────────────────────────────────────────────

    def create_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reports", payload, headers)

    def get_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/reports/{report_id}", headers=headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reports", headers=headers, params=params)


api_client = ApiClient()
