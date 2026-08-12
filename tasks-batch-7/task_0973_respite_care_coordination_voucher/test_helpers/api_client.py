"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Program & admin ---
    def create_program(self, payload, headers):
        return self._request("POST", "/respite/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/respite/programs/{program_id}", headers=headers)

    def set_program_posture(self, program_id, payload, headers):
        return self._request("POST", f"/respite/programs/{program_id}/posture", payload, headers)

    def create_budget_adjustment(self, program_id, payload, headers):
        return self._request("POST", f"/respite/programs/{program_id}/budget-adjustments", payload, headers)

    def list_budget_ledger(self, program_id, headers, params=None):
        return self._request("GET", f"/respite/programs/{program_id}/budget-ledger", headers=headers, params=params)

    def list_program_report_snapshots(self, program_id, headers, params=None):
        return self._request("GET", f"/respite/programs/{program_id}/report-snapshots", headers=headers, params=params)

    def list_program_allocations(self, program_id, headers, params=None):
        return self._request("GET", f"/respite/programs/{program_id}/allocations", headers=headers, params=params)

    def create_ops_run(self, program_id, payload, headers):
        return self._request("POST", f"/respite/programs/{program_id}/ops-runs", payload, headers)

    # --- Caregiver ---
    def create_caregiver(self, payload, headers):
        return self._request("POST", "/respite/caregivers", payload, headers)

    def get_caregiver(self, caregiver_id, headers):
        return self._request("GET", f"/respite/caregivers/{caregiver_id}", headers=headers)

    def transition_caregiver(self, caregiver_id, payload, headers):
        return self._request("POST", f"/respite/caregivers/{caregiver_id}/status-transitions", payload, headers)

    def list_caregiver_applications(self, caregiver_id, headers, params=None):
        return self._request("GET", f"/respite/caregivers/{caregiver_id}/eligibility-applications", headers=headers, params=params)

    def list_caregiver_allocations(self, caregiver_id, headers, params=None):
        return self._request("GET", f"/respite/caregivers/{caregiver_id}/allocations", headers=headers, params=params)

    def create_eligibility_application(self, caregiver_id, payload, headers):
        return self._request("POST", f"/respite/caregivers/{caregiver_id}/eligibility-applications", payload, headers)

    # --- Eligibility applications ---
    def get_eligibility_application(self, application_id, headers):
        return self._request("GET", f"/respite/eligibility-applications/{application_id}", headers=headers)

    def create_review_decision(self, application_id, payload, headers):
        return self._request("POST", f"/respite/eligibility-applications/{application_id}/review-decisions", payload, headers)

    def resubmit_application(self, application_id, payload, headers):
        return self._request("POST", f"/respite/eligibility-applications/{application_id}/resubmit", payload, headers)

    def appeal_application(self, application_id, payload, headers):
        return self._request("POST", f"/respite/eligibility-applications/{application_id}/appeal", payload, headers)

    # --- Allocations ---
    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/respite/allocations/{allocation_id}", headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/respite/allocations", headers=headers, params=params)

    def create_grant_adjustment(self, allocation_id, payload, headers):
        return self._request("POST", f"/respite/allocations/{allocation_id}/grant-adjustments", payload, headers)

    # --- Vouchers ---
    def create_voucher(self, payload, headers):
        return self._request("POST", "/respite/vouchers", payload, headers)

    def get_voucher(self, voucher_id, headers):
        return self._request("GET", f"/respite/vouchers/{voucher_id}", headers=headers)

    def list_vouchers(self, headers, params=None):
        return self._request("GET", "/respite/vouchers", headers=headers, params=params)

    def revoke_voucher(self, voucher_id, payload, headers):
        return self._request("POST", f"/respite/vouchers/{voucher_id}/revoke", payload, headers)

    # --- Providers & windows ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/respite/providers", payload, headers)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/respite/providers/{provider_id}", headers=headers)

    def transition_provider(self, provider_id, payload, headers):
        return self._request("POST", f"/respite/providers/{provider_id}/status-transitions", payload, headers)

    def create_availability_window(self, provider_id, payload, headers):
        return self._request("POST", f"/respite/providers/{provider_id}/availability-windows", payload, headers)

    def list_provider_windows(self, provider_id, headers, params=None):
        return self._request("GET", f"/respite/providers/{provider_id}/availability-windows", headers=headers, params=params)

    def close_availability_window(self, window_id, headers):
        return self._request("POST", f"/respite/availability-windows/{window_id}/close", {}, headers)

    # --- Bookings / scheduling ---
    def create_booking(self, payload, headers):
        return self._request("POST", "/respite/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/respite/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/respite/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/respite/bookings/{booking_id}/confirm", {}, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/respite/bookings/{booking_id}/cancel", payload, headers)

    def list_booking_visit_records(self, booking_id, headers):
        return self._request("GET", f"/respite/bookings/{booking_id}/visit-records", headers=headers)

    def check_in_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/respite/bookings/{booking_id}/check-in", payload, headers)

    def create_satisfaction_survey(self, booking_id, payload, headers):
        return self._request("POST", f"/respite/bookings/{booking_id}/satisfaction-surveys", payload, headers)

    # --- EVV ---
    def check_out_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/respite/visit-records/{visit_id}/check-out", payload, headers)

    def get_visit_record(self, visit_id, headers):
        return self._request("GET", f"/respite/visit-records/{visit_id}", headers=headers)

    def create_verification_decision(self, visit_id, payload, headers):
        return self._request("POST", f"/respite/visit-records/{visit_id}/verification-decisions", payload, headers)

    def resubmit_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/respite/visit-records/{visit_id}/resubmit", payload, headers)

    # --- Claims ---
    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/respite/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/respite/claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/respite/claims/{claim_id}/submit", {}, headers)

    def adjudicate_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/respite/claims/{claim_id}/adjudicate", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/respite/claims/{claim_id}/pay", {}, headers)

    def appeal_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/respite/claims/{claim_id}/appeal", payload, headers)

    # --- Emergency respite ---
    def create_emergency_request(self, payload, headers):
        return self._request("POST", "/respite/emergency-requests", payload, headers)

    def get_emergency_request(self, request_id, headers):
        return self._request("GET", f"/respite/emergency-requests/{request_id}", headers=headers)

    def list_emergency_requests(self, headers, params=None):
        return self._request("GET", "/respite/emergency-requests", headers=headers, params=params)

    def triage_emergency_request(self, request_id, payload, headers):
        return self._request("POST", f"/respite/emergency-requests/{request_id}/triage", payload, headers)

    def dispatch_emergency_request(self, request_id, headers):
        return self._request("POST", f"/respite/emergency-requests/{request_id}/dispatch", {}, headers)

    def cancel_emergency_request(self, request_id, payload, headers):
        return self._request("POST", f"/respite/emergency-requests/{request_id}/cancel", payload, headers)

    # --- Satisfaction ---
    def get_satisfaction_survey(self, survey_id, headers):
        return self._request("GET", f"/respite/satisfaction-surveys/{survey_id}", headers=headers)

    def list_satisfaction_surveys(self, headers, params=None):
        return self._request("GET", "/respite/satisfaction-surveys", headers=headers, params=params)

    # --- Funder reporting ---
    def get_report_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/respite/report-snapshots/{snapshot_id}", headers=headers)

    def transition_report_snapshot(self, snapshot_id, payload, headers):
        return self._request("POST", f"/respite/report-snapshots/{snapshot_id}/transitions", payload, headers)

    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
