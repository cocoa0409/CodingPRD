"""API client: one method per endpoint defined in the PRD.

All paths are mounted under the ``/wm`` prefix. The base ``_request()`` is
inherited from the framework ``GenericApiClient``.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Programs + clock ─────────────────────────────
    def create_program(self, payload, headers):
        return self._request("POST", "/wm/programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/wm/programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/wm/programs/{program_id}", headers=headers)

    def clock_set(self, program_id, payload, headers):
        return self._request("POST", f"/wm/programs/{program_id}/clock-set", payload, headers)

    # ─── Plans ────────────────────────────────────────
    def create_plan(self, payload, headers):
        return self._request("POST", "/wm/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/wm/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/wm/plans/{plan_id}", headers=headers)

    def retire_plan(self, plan_id, headers):
        return self._request("POST", f"/wm/plans/{plan_id}/retire", {}, headers)

    # ─── Members ──────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/wm/members", payload, headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/wm/members", headers=headers, params=params)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/wm/members/{member_id}", headers=headers)

    # ─── Coaches ──────────────────────────────────────
    def create_coach(self, payload, headers):
        return self._request("POST", "/wm/coaches", payload, headers)

    def list_coaches(self, headers, params=None):
        return self._request("GET", "/wm/coaches", headers=headers, params=params)

    def get_coach(self, coach_id, headers):
        return self._request("GET", f"/wm/coaches/{coach_id}", headers=headers)

    def update_coach(self, coach_id, payload, headers):
        return self._request("PATCH", f"/wm/coaches/{coach_id}", payload, headers)

    # ─── Intake assessments ───────────────────────────
    def create_intake(self, payload, headers):
        return self._request("POST", "/wm/intake-assessments", payload, headers)

    def list_intakes(self, headers, params=None):
        return self._request("GET", "/wm/intake-assessments", headers=headers, params=params)

    def get_intake(self, assessment_id, headers):
        return self._request("GET", f"/wm/intake-assessments/{assessment_id}", headers=headers)

    def submit_intake(self, assessment_id, payload, headers):
        return self._request("POST", f"/wm/intake-assessments/{assessment_id}/submit", payload, headers)

    def start_review_intake(self, assessment_id, headers):
        return self._request("POST", f"/wm/intake-assessments/{assessment_id}/start-review", {}, headers)

    def request_revision_intake(self, assessment_id, payload, headers):
        return self._request("POST", f"/wm/intake-assessments/{assessment_id}/request-revision", payload, headers)

    def approve_intake(self, assessment_id, headers):
        return self._request("POST", f"/wm/intake-assessments/{assessment_id}/approve", {}, headers)

    def reject_intake(self, assessment_id, payload, headers):
        return self._request("POST", f"/wm/intake-assessments/{assessment_id}/reject", payload, headers)

    # ─── Enrollments ──────────────────────────────────
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/wm/enrollments", payload, headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/wm/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/wm/enrollments/{enrollment_id}", headers=headers)

    def activate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/wm/enrollments/{enrollment_id}/activate", {}, headers)

    def bill_next_cycle(self, enrollment_id, headers):
        return self._request("POST", f"/wm/enrollments/{enrollment_id}/bill-next-cycle", {}, headers)

    def graduate_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/wm/enrollments/{enrollment_id}/graduate", {}, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/wm/enrollments/{enrollment_id}/withdraw", {}, headers)

    # ─── Weigh-ins ────────────────────────────────────
    def create_weighin(self, payload, headers):
        return self._request("POST", "/wm/weigh-ins", payload, headers)

    def list_weighins(self, headers, params=None):
        return self._request("GET", "/wm/weigh-ins", headers=headers, params=params)

    def get_weighin(self, weighin_id, headers):
        return self._request("GET", f"/wm/weigh-ins/{weighin_id}", headers=headers)

    # ─── Goals + milestones ───────────────────────────
    def create_goal(self, payload, headers):
        return self._request("POST", "/wm/goals", payload, headers)

    def list_goals(self, headers, params=None):
        return self._request("GET", "/wm/goals", headers=headers, params=params)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/wm/goals/{goal_id}", headers=headers)

    def create_milestone(self, payload, headers):
        return self._request("POST", "/wm/milestones", payload, headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/wm/milestones", headers=headers, params=params)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/wm/milestones/{milestone_id}", headers=headers)

    # ─── Coach assignments ────────────────────────────
    def create_coach_assignment(self, payload, headers):
        return self._request("POST", "/wm/coach-assignments", payload, headers)

    def list_coach_assignments(self, headers, params=None):
        return self._request("GET", "/wm/coach-assignments", headers=headers, params=params)

    def get_coach_assignment(self, assignment_id, headers):
        return self._request("GET", f"/wm/coach-assignments/{assignment_id}", headers=headers)

    def end_coach_assignment(self, assignment_id, headers):
        return self._request("POST", f"/wm/coach-assignments/{assignment_id}/end", {}, headers)

    # ─── Messaging ────────────────────────────────────
    def create_message_thread(self, payload, headers):
        return self._request("POST", "/wm/message-threads", payload, headers)

    def list_message_threads(self, headers, params=None):
        return self._request("GET", "/wm/message-threads", headers=headers, params=params)

    def get_message_thread(self, thread_id, headers):
        return self._request("GET", f"/wm/message-threads/{thread_id}", headers=headers)

    def archive_message_thread(self, thread_id, headers):
        return self._request("POST", f"/wm/message-threads/{thread_id}/archive", {}, headers)

    def post_message(self, thread_id, payload, headers):
        return self._request("POST", f"/wm/message-threads/{thread_id}/messages", payload, headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", "/wm/messages", headers=headers, params=params)

    def get_message(self, message_id, headers):
        return self._request("GET", f"/wm/messages/{message_id}", headers=headers)

    # ─── Invoices ─────────────────────────────────────
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/wm/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/wm/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wm/invoices/{invoice_id}/pay", {}, headers)

    def mark_invoice_past_due(self, invoice_id, headers):
        return self._request("POST", f"/wm/invoices/{invoice_id}/mark-past-due", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/wm/invoices/{invoice_id}/void", {}, headers)

    # ─── Eligibility determinations ───────────────────
    def create_eligibility(self, payload, headers):
        return self._request("POST", "/wm/eligibility-determinations", payload, headers)

    def list_eligibility(self, headers, params=None):
        return self._request("GET", "/wm/eligibility-determinations", headers=headers, params=params)

    def get_eligibility(self, determination_id, headers):
        return self._request("GET", f"/wm/eligibility-determinations/{determination_id}", headers=headers)

    def approve_eligibility(self, determination_id, headers):
        return self._request("POST", f"/wm/eligibility-determinations/{determination_id}/approve", {}, headers)

    def deny_eligibility(self, determination_id, headers):
        return self._request("POST", f"/wm/eligibility-determinations/{determination_id}/deny", {}, headers)

    # ─── Rx authorizations ────────────────────────────
    def create_rx(self, payload, headers):
        return self._request("POST", "/wm/rx-authorizations", payload, headers)

    def list_rx(self, headers, params=None):
        return self._request("GET", "/wm/rx-authorizations", headers=headers, params=params)

    def get_rx(self, rx_id, headers):
        return self._request("GET", f"/wm/rx-authorizations/{rx_id}", headers=headers)

    def issue_rx(self, rx_id, payload, headers):
        return self._request("POST", f"/wm/rx-authorizations/{rx_id}/issue", payload, headers)

    def deny_rx(self, rx_id, headers):
        return self._request("POST", f"/wm/rx-authorizations/{rx_id}/deny", {}, headers)

    def revoke_rx(self, rx_id, headers):
        return self._request("POST", f"/wm/rx-authorizations/{rx_id}/revoke", {}, headers)


api_client = ApiClient()
