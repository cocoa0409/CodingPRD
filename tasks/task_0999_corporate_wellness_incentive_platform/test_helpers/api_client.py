"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Employer ---
    def create_employer(self, payload, headers):
        return self._request("POST", "/wellness/employers", payload, headers)

    def get_employer(self, employer_id, headers):
        return self._request("GET", f"/wellness/employers/{employer_id}", headers=headers)

    def list_employer_employees(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/wellness/employers/{employer_id}/employees", headers=headers, params=params
        )

    def list_employer_programs(self, employer_id, headers, params=None):
        return self._request(
            "GET", f"/wellness/employers/{employer_id}/programs", headers=headers, params=params
        )

    # --- Employee ---
    def create_employee(self, payload, headers):
        return self._request("POST", "/wellness/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/wellness/employees/{employee_id}", headers=headers)

    def list_employee_enrollments(self, employee_id, headers, params=None):
        return self._request(
            "GET", f"/wellness/employees/{employee_id}/enrollments", headers=headers, params=params
        )

    # --- WellnessProgram ---
    def create_program(self, payload, headers):
        return self._request("POST", "/wellness/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/wellness/programs/{program_id}", headers=headers)

    def activate_program(self, program_id, headers):
        return self._request(
            "POST", f"/wellness/programs/{program_id}/activate", {}, headers
        )

    def close_program(self, program_id, headers):
        return self._request("POST", f"/wellness/programs/{program_id}/close", {}, headers)

    def settle_program(self, program_id, headers):
        return self._request("POST", f"/wellness/programs/{program_id}/settle", {}, headers)

    def finalize_program_points(self, program_id, headers):
        return self._request(
            "POST", f"/wellness/programs/{program_id}/finalize-points", {}, headers
        )

    def list_program_enrollments(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/wellness/programs/{program_id}/enrollments", headers=headers, params=params
        )

    def list_program_challenges(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/wellness/programs/{program_id}/challenges", headers=headers, params=params
        )

    def list_program_incentive_awards(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/programs/{program_id}/incentive-awards",
            headers=headers,
            params=params,
        )

    def list_program_vendor_invoices(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/programs/{program_id}/vendor-invoices",
            headers=headers,
            params=params,
        )

    def list_program_aggregate_reports(self, program_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/programs/{program_id}/aggregate-reports",
            headers=headers,
            params=params,
        )

    # --- Enrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/wellness/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/wellness/enrollments/{enrollment_id}", headers=headers)

    def accept_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/wellness/enrollments/{enrollment_id}/accept", {}, headers
        )

    def suspend_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/wellness/enrollments/{enrollment_id}/suspend", {}, headers
        )

    def reinstate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/wellness/enrollments/{enrollment_id}/reinstate", {}, headers
        )

    def terminate_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/wellness/enrollments/{enrollment_id}/terminate", {}, headers
        )

    def create_enrollment_adjustment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/wellness/enrollments/{enrollment_id}/adjustments", payload, headers
        )

    def list_enrollment_hras(self, enrollment_id, headers, params=None):
        return self._request(
            "GET", f"/wellness/enrollments/{enrollment_id}/hras", headers=headers, params=params
        )

    def list_enrollment_biometric_screenings(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/enrollments/{enrollment_id}/biometric-screenings",
            headers=headers,
            params=params,
        )

    def list_enrollment_challenge_participations(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/enrollments/{enrollment_id}/challenge-participations",
            headers=headers,
            params=params,
        )

    def list_enrollment_activity_events(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/enrollments/{enrollment_id}/activity-events",
            headers=headers,
            params=params,
        )

    def list_enrollment_points_ledger_entries(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/enrollments/{enrollment_id}/points-ledger-entries",
            headers=headers,
            params=params,
        )

    def list_enrollment_incentive_awards(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/enrollments/{enrollment_id}/incentive-awards",
            headers=headers,
            params=params,
        )

    def list_enrollment_coaching_referrals(self, enrollment_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/enrollments/{enrollment_id}/coaching-referrals",
            headers=headers,
            params=params,
        )

    # --- HealthAssessment ---
    def create_hra(self, payload, headers):
        return self._request("POST", "/wellness/hras", payload, headers)

    # --- BiometricScreening ---
    def create_biometric_screening(self, payload, headers):
        return self._request("POST", "/wellness/biometric-screenings", payload, headers)

    def result_biometric_screening(self, screening_id, payload, headers):
        return self._request(
            "POST", f"/wellness/biometric-screenings/{screening_id}/result", payload, headers
        )

    # --- Challenge ---
    def create_challenge(self, payload, headers):
        return self._request("POST", "/wellness/challenges", payload, headers)

    def get_challenge(self, challenge_id, headers):
        return self._request("GET", f"/wellness/challenges/{challenge_id}", headers=headers)

    def patch_challenge(self, challenge_id, payload, headers):
        return self._request("PATCH", f"/wellness/challenges/{challenge_id}", payload, headers)

    def publish_challenge(self, challenge_id, headers):
        return self._request(
            "POST", f"/wellness/challenges/{challenge_id}/publish", {}, headers
        )

    def list_challenge_participations(self, challenge_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/challenges/{challenge_id}/participations",
            headers=headers,
            params=params,
        )

    # --- ChallengeParticipation ---
    def create_challenge_participation(self, payload, headers):
        return self._request("POST", "/wellness/challenge-participations", payload, headers)

    # --- ActivityEvent ---
    def create_activity_event(self, payload, headers):
        return self._request("POST", "/wellness/activity-events", payload, headers)

    def get_activity_event(self, event_id, headers):
        return self._request("GET", f"/wellness/activity-events/{event_id}", headers=headers)

    def list_activity_event_points_ledger_entries(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/wellness/activity-events/{event_id}/points-ledger-entries",
            headers=headers,
            params=params,
        )

    # --- IncentiveAward ---
    def compute_incentive_awards(self, payload, headers):
        return self._request("POST", "/wellness/incentive-awards/compute", payload, headers)

    def confirm_incentive_award(self, award_id, headers):
        return self._request(
            "POST", f"/wellness/incentive-awards/{award_id}/confirm", {}, headers
        )

    def apply_incentive_award(self, award_id, headers):
        return self._request(
            "POST", f"/wellness/incentive-awards/{award_id}/apply", {}, headers
        )

    def dispute_incentive_award(self, award_id, payload, headers):
        return self._request(
            "POST", f"/wellness/incentive-awards/{award_id}/dispute", payload, headers
        )

    def resolve_incentive_award(self, award_id, payload, headers):
        return self._request(
            "POST", f"/wellness/incentive-awards/{award_id}/resolve", payload, headers
        )

    # --- CoachingReferral ---
    def create_coaching_referral(self, payload, headers):
        return self._request("POST", "/wellness/coaching-referrals", payload, headers)

    def engage_coaching_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/wellness/coaching-referrals/{referral_id}/engage", {}, headers
        )

    def log_coaching_session(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/wellness/coaching-referrals/{referral_id}/sessions", payload, headers
        )

    def discharge_coaching_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/wellness/coaching-referrals/{referral_id}/discharge", payload, headers
        )

    def decline_coaching_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/wellness/coaching-referrals/{referral_id}/decline", {}, headers
        )

    def rerefer_coaching_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/wellness/coaching-referrals/{referral_id}/rerefer", {}, headers
        )

    # --- VendorInvoice ---
    def create_vendor_invoice(self, payload, headers):
        return self._request("POST", "/wellness/vendor-invoices", payload, headers)

    def create_invoice_adjustment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/wellness/vendor-invoices/{invoice_id}/adjustments", payload, headers
        )

    def submit_vendor_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/wellness/vendor-invoices/{invoice_id}/submit", {}, headers
        )

    def approve_vendor_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/wellness/vendor-invoices/{invoice_id}/approve", payload, headers
        )

    def pay_vendor_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wellness/vendor-invoices/{invoice_id}/pay", {}, headers)

    def dispute_vendor_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/wellness/vendor-invoices/{invoice_id}/dispute", payload, headers
        )

    def revise_vendor_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/wellness/vendor-invoices/{invoice_id}/revise", {}, headers
        )

    # --- AggregateReport ---
    def create_aggregate_report(self, payload, headers):
        return self._request("POST", "/wellness/aggregate-reports", payload, headers)

    def publish_aggregate_report(self, report_id, headers):
        return self._request(
            "POST", f"/wellness/aggregate-reports/{report_id}/publish", {}, headers
        )


api_client = ApiClient()
