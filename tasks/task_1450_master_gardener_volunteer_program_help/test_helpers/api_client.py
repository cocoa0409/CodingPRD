"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def _request(self, method, path, payload=None, headers=None, params=None):
        # The runner restarts the server (SIGKILL + fresh boot on the same
        # port) before every test. The session-scoped client would otherwise
        # reuse a pooled keep-alive connection whose peer was just killed,
        # intermittently surfacing as "Connection reset by peer" on a test's
        # first request. Sending Connection: close makes every request open
        # a fresh TCP connection, eliminating the stale-connection race.
        headers = {**(headers or {}), "Connection": "close"}
        return super()._request(method, path, payload=payload,
                                headers=headers, params=params)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- ProgramCycle ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/program-cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/program-cycles", headers=headers,
                             params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/program-cycles/{cycle_id}",
                             headers=headers)

    def update_cycle(self, cycle_id, payload, headers):
        return self._request("PUT", f"/program-cycles/{cycle_id}", payload,
                             headers)

    def open_cycle(self, cycle_id, headers):
        return self._request("POST", f"/program-cycles/{cycle_id}/open",
                             headers=headers)

    def begin_recertification(self, cycle_id, headers):
        return self._request(
            "POST", f"/program-cycles/{cycle_id}/begin-recertification",
            headers=headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/program-cycles/{cycle_id}/close",
                             headers=headers)

    def promote_waitlisted(self, cycle_id, headers):
        return self._request(
            "POST", f"/program-cycles/{cycle_id}/promote-waitlisted",
            headers=headers)

    # --- Application ---
    def create_application(self, payload, headers):
        return self._request("POST", "/applications", payload, headers)

    def list_applications(self, headers, params=None):
        return self._request("GET", "/applications", headers=headers,
                             params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/applications/{application_id}",
                             headers=headers)

    def score_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/score",
                             payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/applications/{application_id}/decide",
                             payload, headers)

    # --- Volunteer ---
    def list_volunteers(self, headers, params=None):
        return self._request("GET", "/volunteers", headers=headers,
                             params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"/volunteers/{volunteer_id}",
                             headers=headers)

    def withdraw_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/volunteers/{volunteer_id}/withdraw",
                             headers=headers)

    def reactivate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"/volunteers/{volunteer_id}/reactivate",
                             headers=headers)

    # --- TrainingEnrollment ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/training-enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/training-enrollments", headers=headers,
                             params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/training-enrollments/{enrollment_id}",
                             headers=headers)

    def record_progress(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/progress", payload,
            headers)

    def complete_enrollment(self, enrollment_id, headers):
        return self._request(
            "POST", f"/training-enrollments/{enrollment_id}/complete",
            headers=headers)

    # --- CreditEntry ---
    def create_credit_entry(self, volunteer_id, payload, headers):
        return self._request("POST", f"/volunteers/{volunteer_id}/credit-entries",
                             payload, headers)

    def list_credit_entries(self, headers, params=None):
        return self._request("GET", "/credit-entries", headers=headers,
                             params=params)

    def get_credit_entry(self, entry_id, headers):
        return self._request("GET", f"/credit-entries/{entry_id}",
                             headers=headers)

    def approve_credit_entry(self, entry_id, headers):
        return self._request("POST", f"/credit-entries/{entry_id}/approve",
                             headers=headers)

    def reject_credit_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/credit-entries/{entry_id}/reject",
                             payload, headers)

    def revoke_credit_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/credit-entries/{entry_id}/revoke",
                             payload, headers)

    # --- RecertificationRecord ---
    def list_recertification_records(self, headers, params=None):
        return self._request("GET", "/recertification-records", headers=headers,
                             params=params)

    def get_recertification_record(self, record_id, headers):
        return self._request("GET", f"/recertification-records/{record_id}",
                             headers=headers)

    def evaluate_record(self, record_id, headers):
        return self._request(
            "POST", f"/recertification-records/{record_id}/evaluate",
            headers=headers)

    def grant_exemption(self, record_id, payload, headers):
        return self._request(
            "POST", f"/recertification-records/{record_id}/grant-exemption",
            payload, headers)

    # --- Shift ---
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def cancel_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/cancel",
                             headers=headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/complete",
                             headers=headers)

    # --- ShiftSignup ---
    def create_signup(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/signups", payload,
                             headers)

    def list_signups(self, headers, params=None):
        return self._request("GET", "/shift-signups", headers=headers,
                             params=params)

    def get_signup(self, signup_id, headers):
        return self._request("GET", f"/shift-signups/{signup_id}",
                             headers=headers)

    def cancel_signup(self, signup_id, headers):
        return self._request("POST", f"/shift-signups/{signup_id}/cancel",
                             headers=headers)

    def complete_signup(self, signup_id, headers):
        return self._request("POST", f"/shift-signups/{signup_id}/complete",
                             headers=headers)

    def mark_no_show(self, signup_id, headers):
        return self._request("POST", f"/shift-signups/{signup_id}/mark-no-show",
                             headers=headers)

    # --- Inquiry ---
    def create_inquiry(self, shift_id, payload, headers):
        return self._request("POST", f"/shifts/{shift_id}/inquiries", payload,
                             headers)

    def list_inquiries(self, headers, params=None):
        return self._request("GET", "/inquiries", headers=headers,
                             params=params)

    def get_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/inquiries/{inquiry_id}", headers=headers)

    def triage_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/triage", payload,
                             headers)

    def answer_inquiry(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/answer", payload,
                             headers)

    # --- DiagnosisReferral ---
    def create_referral(self, inquiry_id, payload, headers):
        return self._request("POST", f"/inquiries/{inquiry_id}/referrals",
                             payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/diagnosis-referrals", headers=headers,
                             params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/diagnosis-referrals/{referral_id}",
                             headers=headers)

    def start_review(self, referral_id, headers):
        return self._request(
            "POST", f"/diagnosis-referrals/{referral_id}/start-review",
            headers=headers)

    def answer_referral(self, referral_id, payload, headers):
        return self._request("POST",
                             f"/diagnosis-referrals/{referral_id}/answer",
                             payload, headers)

    def return_referral(self, referral_id, payload, headers):
        return self._request("POST",
                             f"/diagnosis-referrals/{referral_id}/return",
                             payload, headers)

    def reassign_referral(self, referral_id, payload, headers):
        return self._request("POST",
                             f"/diagnosis-referrals/{referral_id}/reassign",
                             payload, headers)

    # --- Specialist ---
    def create_specialist(self, payload, headers):
        return self._request("POST", "/specialists", payload, headers)

    def list_specialists(self, headers, params=None):
        return self._request("GET", "/specialists", headers=headers,
                             params=params)

    def get_specialist(self, specialist_id, headers):
        return self._request("GET", f"/specialists/{specialist_id}",
                             headers=headers)

    def update_specialist(self, specialist_id, payload, headers):
        return self._request("PATCH", f"/specialists/{specialist_id}", payload,
                             headers)

    # --- CommunityProject ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def amend_project(self, project_id, payload, headers):
        return self._request("PUT", f"/projects/{project_id}", payload, headers)

    def submit_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/submit",
                             headers=headers)

    def approve_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/approve",
                             headers=headers)

    def request_revision(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/request-revision",
                             payload, headers)

    def reject_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/reject", payload,
                             headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close",
                             headers=headers)

    # --- RotationAssignment ---
    def create_rotation_assignment(self, payload, headers):
        return self._request("POST", "/rotation-assignments", payload, headers)

    def list_rotation_assignments(self, headers, params=None):
        return self._request("GET", "/rotation-assignments", headers=headers,
                             params=params)

    def get_rotation_assignment(self, assignment_id, headers):
        return self._request("GET", f"/rotation-assignments/{assignment_id}",
                             headers=headers)

    def complete_rotation_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/rotation-assignments/{assignment_id}/complete", payload,
            headers)

    def mark_rotation_missed(self, assignment_id, headers):
        return self._request(
            "POST", f"/rotation-assignments/{assignment_id}/mark-missed",
            headers=headers)

    def swap_rotation_assignment(self, assignment_id, payload, headers):
        return self._request("POST",
                             f"/rotation-assignments/{assignment_id}/swap",
                             payload, headers)


api_client = ApiClient()
