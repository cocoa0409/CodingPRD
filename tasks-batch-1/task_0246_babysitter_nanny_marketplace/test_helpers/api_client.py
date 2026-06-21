"""API client: one method per endpoint defined in the PRD (Section 4).

Subclasses the framework's GenericApiClient; the base _request() handles the
HTTP envelope and is inherited.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Test clock ──────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/marketplace/_clock/set",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Family ──────────────────────────────────────────────────────────
    def create_family(self, payload, headers):
        return self._request("POST", "/marketplace/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/marketplace/families/{family_id}", headers=headers)

    def list_families(self, headers, params=None):
        return self._request("GET", "/marketplace/families", headers=headers, params=params)

    def deposit(self, family_id, payload, headers):
        return self._request("POST", f"/marketplace/families/{family_id}/deposit",
                             payload, headers)

    # ─── Caregiver ───────────────────────────────────────────────────────
    def create_caregiver(self, payload, headers):
        return self._request("POST", "/marketplace/caregivers", payload, headers)

    def get_caregiver(self, caregiver_id, headers):
        return self._request("GET", f"/marketplace/caregivers/{caregiver_id}", headers=headers)

    def list_caregivers(self, headers, params=None):
        return self._request("GET", "/marketplace/caregivers", headers=headers, params=params)

    def set_availability(self, caregiver_id, payload, headers):
        return self._request("POST", f"/marketplace/caregivers/{caregiver_id}/availability",
                             payload, headers)

    # ─── BackgroundCheck ─────────────────────────────────────────────────
    def create_background_check(self, payload, headers):
        return self._request("POST", "/marketplace/background-checks", payload, headers)

    def get_background_check(self, check_id, headers):
        return self._request("GET", f"/marketplace/background-checks/{check_id}", headers=headers)

    def list_background_checks(self, headers, params=None):
        return self._request("GET", "/marketplace/background-checks", headers=headers, params=params)

    def start_background_check(self, check_id, headers):
        return self._request("POST", f"/marketplace/background-checks/{check_id}/start",
                             {}, headers)

    def adjudicate_background_check(self, check_id, payload, headers):
        return self._request("POST", f"/marketplace/background-checks/{check_id}/adjudicate",
                             payload, headers)

    # ─── JobPosting ──────────────────────────────────────────────────────
    def create_job_posting(self, payload, headers):
        return self._request("POST", "/marketplace/job-postings", payload, headers)

    def get_job_posting(self, posting_id, headers):
        return self._request("GET", f"/marketplace/job-postings/{posting_id}", headers=headers)

    def list_job_postings(self, headers, params=None):
        return self._request("GET", "/marketplace/job-postings", headers=headers, params=params)

    # ─── Interview ───────────────────────────────────────────────────────
    def create_interview(self, payload, headers):
        return self._request("POST", "/marketplace/interviews", payload, headers)

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/marketplace/interviews/{interview_id}", headers=headers)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/marketplace/interviews", headers=headers, params=params)

    def decide_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/marketplace/interviews/{interview_id}/decide",
                             payload, headers)

    def cancel_interview(self, interview_id, headers):
        return self._request("POST", f"/marketplace/interviews/{interview_id}/cancel",
                             {}, headers)

    # ─── Booking ─────────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/marketplace/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/marketplace/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/marketplace/bookings", headers=headers, params=params)

    def counter_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/counter",
                             payload, headers)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/confirm",
                             {}, headers)

    def decline_booking(self, booking_id, headers):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/decline",
                             {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/marketplace/bookings/{booking_id}/cancel",
                             {}, headers)

    # ─── BookingSession ──────────────────────────────────────────────────
    def get_session(self, session_id, headers):
        return self._request("GET", f"/marketplace/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/marketplace/sessions", headers=headers, params=params)

    def clock_in(self, session_id, headers):
        return self._request("POST", f"/marketplace/sessions/{session_id}/clock-in",
                             {}, headers)

    def clock_out(self, session_id, headers):
        return self._request("POST", f"/marketplace/sessions/{session_id}/clock-out",
                             {}, headers)

    def no_show(self, session_id, headers):
        return self._request("POST", f"/marketplace/sessions/{session_id}/no-show",
                             {}, headers)

    # ─── BackupCareRequest ───────────────────────────────────────────────
    def create_backup_request(self, payload, headers):
        return self._request("POST", "/marketplace/backup-requests", payload, headers)

    def get_backup_request(self, request_id, headers):
        return self._request("GET", f"/marketplace/backup-requests/{request_id}", headers=headers)

    def list_backup_requests(self, headers, params=None):
        return self._request("GET", "/marketplace/backup-requests", headers=headers, params=params)

    def match_backup_request(self, request_id, payload, headers):
        return self._request("POST", f"/marketplace/backup-requests/{request_id}/match",
                             payload, headers)

    def fulfill_backup_request(self, request_id, headers):
        return self._request("POST", f"/marketplace/backup-requests/{request_id}/fulfill",
                             {}, headers)

    def expire_backup_request(self, request_id, headers):
        return self._request("POST", f"/marketplace/backup-requests/{request_id}/expire",
                             {}, headers)

    def cancel_backup_request(self, request_id, headers):
        return self._request("POST", f"/marketplace/backup-requests/{request_id}/cancel",
                             {}, headers)

    # ─── Payout ──────────────────────────────────────────────────────────
    def create_payout(self, payload, headers):
        return self._request("POST", "/marketplace/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/marketplace/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/marketplace/payouts", headers=headers, params=params)

    def pay_payout(self, payout_id, headers):
        return self._request("POST", f"/marketplace/payouts/{payout_id}/pay", {}, headers)

    def reverse_payout(self, payout_id, headers):
        return self._request("POST", f"/marketplace/payouts/{payout_id}/reverse", {}, headers)

    # ─── Review ──────────────────────────────────────────────────────────
    def create_review(self, payload, headers):
        return self._request("POST", "/marketplace/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/marketplace/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/marketplace/reviews", headers=headers, params=params)

    def moderate_review(self, review_id, payload, headers):
        return self._request("POST", f"/marketplace/reviews/{review_id}/moderate",
                             payload, headers)

    # ─── TaxStatement ────────────────────────────────────────────────────
    def create_tax_statement(self, payload, headers):
        return self._request("POST", "/marketplace/tax-statements", payload, headers)

    def get_tax_statement(self, statement_id, headers):
        return self._request("GET", f"/marketplace/tax-statements/{statement_id}", headers=headers)

    def list_tax_statements(self, headers, params=None):
        return self._request("GET", "/marketplace/tax-statements", headers=headers, params=params)


api_client = ApiClient()
