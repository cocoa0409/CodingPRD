"""API client: one method per endpoint defined in the PRD (§4 routing summary)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/programs", headers=headers, params=params)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/activate", {}, headers)

    def close_program(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/close", {}, headers)

    def run_ops(self, program_id, headers):
        return self._request("POST", f"/programs/{program_id}/run-ops", {}, headers)

    def get_program_summary(self, program_id, headers):
        return self._request("GET", f"/programs/{program_id}/summary", headers=headers)

    # --- Funders ---
    def create_funder(self, payload, headers):
        return self._request("POST", "/funders", payload, headers)

    def get_funder(self, funder_id, headers):
        return self._request("GET", f"/funders/{funder_id}", headers=headers)

    def suspend_funder(self, funder_id, headers):
        return self._request("POST", f"/funders/{funder_id}/suspend", {}, headers)

    def reinstate_funder(self, funder_id, headers):
        return self._request("POST", f"/funders/{funder_id}/reinstate", {}, headers)

    # --- Funding pools ---
    def create_funding_pool(self, payload, headers):
        return self._request("POST", "/funding-pools", payload, headers)

    def get_funding_pool(self, pool_id, headers):
        return self._request("GET", f"/funding-pools/{pool_id}", headers=headers)

    def list_funding_pools(self, headers, params=None):
        return self._request("GET", "/funding-pools", headers=headers, params=params)

    def fund_pool(self, pool_id, headers):
        return self._request("POST", f"/funding-pools/{pool_id}/fund", {}, headers)

    def close_pool(self, pool_id, headers):
        return self._request("POST", f"/funding-pools/{pool_id}/close", {}, headers)

    # --- Clinics ---
    def create_clinic(self, payload, headers):
        return self._request("POST", "/clinics", payload, headers)

    def get_clinic(self, clinic_id, headers):
        return self._request("GET", f"/clinics/{clinic_id}", headers=headers)

    def suspend_clinic(self, clinic_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/suspend", {}, headers)

    def reinstate_clinic(self, clinic_id, headers):
        return self._request("POST", f"/clinics/{clinic_id}/reinstate", {}, headers)

    # --- Retailers ---
    def create_retailer(self, payload, headers):
        return self._request("POST", "/retailers", payload, headers)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"/retailers/{retailer_id}", headers=headers)

    def suspend_retailer(self, retailer_id, headers):
        return self._request("POST", f"/retailers/{retailer_id}/suspend", {}, headers)

    def reinstate_retailer(self, retailer_id, headers):
        return self._request("POST", f"/retailers/{retailer_id}/reinstate", {}, headers)

    # --- Patients ---
    def create_patient(self, payload, headers):
        return self._request("POST", "/patients", payload, headers)

    def get_patient(self, patient_id, headers):
        return self._request("GET", f"/patients/{patient_id}", headers=headers)

    def list_patients(self, headers, params=None):
        return self._request("GET", "/patients", headers=headers, params=params)

    def grant_consent(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/grant-consent", {}, headers)

    def revoke_consent(self, patient_id, headers):
        return self._request("POST", f"/patients/{patient_id}/revoke-consent", {}, headers)

    # --- Referrals ---
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", headers=headers, params=params)

    def start_review(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/start-review", {}, headers)

    def approve_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/approve", {}, headers)

    def decline_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/decline", payload, headers)

    def appeal_referral(self, referral_id, payload, headers):
        return self._request("POST", f"/referrals/{referral_id}/appeal", payload, headers)

    def withdraw_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/withdraw", {}, headers)

    # --- Enrollments ---
    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def suspend_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/suspend", {}, headers)

    def reinstate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/reinstate", {}, headers)

    def terminate_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/terminate", payload, headers)

    # --- Benefit cycles ---
    def create_cycle(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/cycles", headers=headers, params=params)

    def open_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/open", {}, headers)

    def issue_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/issue", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/close", {}, headers)

    # --- Vouchers ---
    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/vouchers", headers=headers, params=params)

    def void_voucher(self, voucher_id, payload, headers):
        return self._request("POST", f"/vouchers/{voucher_id}/void", payload, headers)

    # --- Redemptions ---
    def create_redemption(self, payload, headers):
        return self._request("POST", "/redemptions", payload, headers)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/redemptions/{redemption_id}", headers=headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/redemptions", headers=headers, params=params)

    def void_redemption(self, redemption_id, payload, headers):
        return self._request("POST", f"/redemptions/{redemption_id}/void", payload, headers)

    # --- Education sessions & completions ---
    def create_education_session(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/education-sessions", payload, headers)

    def get_education_session(self, session_id, headers):
        return self._request("GET", f"/education-sessions/{session_id}", headers=headers)

    def list_education_sessions(self, headers, params=None):
        return self._request("GET", "/education-sessions", headers=headers, params=params)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/education-sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/education-sessions/{session_id}/cancel", {}, headers)

    def record_completion(self, session_id, payload, headers):
        return self._request("POST", f"/education-sessions/{session_id}/completions", payload, headers)

    def get_completion(self, completion_id, headers):
        return self._request("GET", f"/education-completions/{completion_id}", headers=headers)

    def list_completions(self, headers, params=None):
        return self._request("GET", "/education-completions", headers=headers, params=params)

    # --- Biometric readings ---
    def create_biometric_reading(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/biometric-readings", payload, headers)

    def get_biometric_reading(self, reading_id, headers):
        return self._request("GET", f"/biometric-readings/{reading_id}", headers=headers)

    def list_biometric_readings(self, headers, params=None):
        return self._request("GET", "/biometric-readings", headers=headers, params=params)

    # --- Funder reports ---
    def create_funder_report(self, program_id, payload, headers):
        return self._request("POST", f"/programs/{program_id}/funder-reports", payload, headers)

    def get_funder_report(self, report_id, headers):
        return self._request("GET", f"/funder-reports/{report_id}", headers=headers)

    def list_funder_reports(self, headers, params=None):
        return self._request("GET", "/funder-reports", headers=headers, params=params)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/funder-reports/{report_id}/submit", {}, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/funder-reports/{report_id}/accept", {}, headers)

    def return_report(self, report_id, payload, headers):
        return self._request("POST", f"/funder-reports/{report_id}/return", payload, headers)

    # --- Renewals ---
    def create_renewal(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/renewals", payload, headers)

    def get_renewal(self, renewal_id, headers):
        return self._request("GET", f"/renewals/{renewal_id}", headers=headers)

    def list_renewals(self, headers, params=None):
        return self._request("GET", "/renewals", headers=headers, params=params)

    def submit_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/submit", {}, headers)

    def approve_renewal(self, renewal_id, headers):
        return self._request("POST", f"/renewals/{renewal_id}/approve", {}, headers)

    def deny_renewal(self, renewal_id, payload, headers):
        return self._request("POST", f"/renewals/{renewal_id}/deny", payload, headers)

    def resubmit_renewal(self, renewal_id, payload, headers):
        return self._request("POST", f"/renewals/{renewal_id}/resubmit", payload, headers)


api_client = ApiClient()
