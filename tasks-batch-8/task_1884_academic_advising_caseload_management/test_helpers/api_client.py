"""API client: one method per endpoint defined in the PRD (§4 endpoint table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -------------------------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Advisors ------------------------------------------------------------
    def create_advisor(self, payload, headers):
        return self._request("POST", "/advising/advisors", payload, headers)

    def list_advisors(self, headers, params=None):
        return self._request("GET", "/advising/advisors", headers=headers, params=params)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/advising/advisors/{advisor_id}", headers=headers)

    def update_advisor(self, advisor_id, payload, headers):
        return self._request("PATCH", f"/advising/advisors/{advisor_id}", payload, headers)

    # --- Students ------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/advising/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/advising/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/advising/students/{student_id}", headers=headers)

    def update_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/advising/students/{student_id}", payload, headers)

    # --- Advisor assignments ---------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/advising/advisor-assignments", payload, headers)

    def auto_assign(self, payload, headers):
        return self._request(
            "POST", "/advising/advisor-assignments/auto-assign", payload, headers
        )

    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", "/advising/advisor-assignments", headers=headers, params=params
        )

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/advising/advisor-assignments/{assignment_id}", headers=headers
        )

    def end_assignment(self, assignment_id, headers):
        return self._request(
            "POST",
            f"/advising/advisor-assignments/{assignment_id}/end",
            {},
            headers,
        )

    # --- Appointments ----------------------------------------------------------
    def create_appointment(self, payload, headers):
        return self._request("POST", "/advising/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/advising/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request(
            "GET", f"/advising/appointments/{appointment_id}", headers=headers
        )

    def check_in_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/advising/appointments/{appointment_id}/check-in", {}, headers
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/advising/appointments/{appointment_id}/cancel", {}, headers
        )

    def complete_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/advising/appointments/{appointment_id}/complete", {}, headers
        )

    # --- Drop-in queue ---------------------------------------------------------
    def create_drop_in_ticket(self, payload, headers):
        return self._request("POST", "/advising/dropin-tickets", payload, headers)

    def list_drop_in_tickets(self, headers, params=None):
        return self._request(
            "GET", "/advising/dropin-tickets", headers=headers, params=params
        )

    def get_drop_in_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/advising/dropin-tickets/{ticket_id}", headers=headers
        )

    def call_next_drop_in_ticket(self, headers):
        return self._request("POST", "/advising/dropin-tickets/call-next", {}, headers)

    def complete_drop_in_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/advising/dropin-tickets/{ticket_id}/complete", {}, headers
        )

    def leave_drop_in_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/advising/dropin-tickets/{ticket_id}/leave", {}, headers
        )

    # --- Early-alert referrals ---------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/advising/referrals", payload, headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/advising/referrals", headers=headers, params=params)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/advising/referrals/{referral_id}", headers=headers)

    def outreach_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/advising/referrals/{referral_id}/outreach", payload, headers
        )

    def escalate_referral(self, referral_id, payload, headers):
        return self._request(
            "POST", f"/advising/referrals/{referral_id}/escalate", payload, headers
        )

    def close_referral(self, referral_id, headers):
        return self._request(
            "POST", f"/advising/referrals/{referral_id}/close", {}, headers
        )

    # --- Interventions -----------------------------------------------------------
    def create_intervention(self, payload, headers):
        return self._request("POST", "/advising/interventions", payload, headers)

    def list_interventions(self, headers, params=None):
        return self._request("GET", "/advising/interventions", headers=headers, params=params)

    def get_intervention(self, intervention_id, headers):
        return self._request(
            "GET", f"/advising/interventions/{intervention_id}", headers=headers
        )

    def close_intervention(self, intervention_id, payload, headers):
        return self._request(
            "POST", f"/advising/interventions/{intervention_id}/close", payload, headers
        )

    # --- Registration holds (student sub-resource) -------------------------------
    def create_hold(self, student_id, payload, headers):
        return self._request(
            "POST", f"/advising/students/{student_id}/holds", payload, headers
        )

    def list_holds(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/advising/students/{student_id}/holds", headers=headers, params=params
        )

    def release_hold(self, student_id, hold_id, headers):
        return self._request(
            "POST",
            f"/advising/students/{student_id}/holds/{hold_id}/release",
            {},
            headers,
        )

    # --- Degree plans (student sub-resource) --------------------------------------
    def create_degree_plan(self, student_id, payload, headers):
        return self._request(
            "POST", f"/advising/students/{student_id}/degree-plans", payload, headers
        )

    def list_degree_plans(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"/advising/students/{student_id}/degree-plans",
            headers=headers,
            params=params,
        )

    def get_degree_plan(self, student_id, plan_id, headers):
        return self._request(
            "GET",
            f"/advising/students/{student_id}/degree-plans/{plan_id}",
            headers=headers,
        )

    def update_degree_plan(self, student_id, plan_id, payload, headers):
        return self._request(
            "PATCH",
            f"/advising/students/{student_id}/degree-plans/{plan_id}",
            payload,
            headers,
        )

    def submit_degree_plan(self, student_id, plan_id, headers):
        return self._request(
            "POST",
            f"/advising/students/{student_id}/degree-plans/{plan_id}/submit",
            {},
            headers,
        )

    def approve_degree_plan(self, student_id, plan_id, headers):
        return self._request(
            "POST",
            f"/advising/students/{student_id}/degree-plans/{plan_id}/approve",
            {},
            headers,
        )

    def return_degree_plan(self, student_id, plan_id, payload, headers):
        return self._request(
            "POST",
            f"/advising/students/{student_id}/degree-plans/{plan_id}/return",
            payload,
            headers,
        )

    # --- Advising notes (student sub-resource) ------------------------------------
    def create_note(self, student_id, payload, headers):
        return self._request(
            "POST", f"/advising/students/{student_id}/notes", payload, headers
        )

    def list_notes(self, student_id, headers, params=None):
        return self._request(
            "GET", f"/advising/students/{student_id}/notes", headers=headers, params=params
        )

    # --- Retention reporting --------------------------------------------------------
    def get_retention_report(self, headers, params=None):
        return self._request(
            "GET", "/advising/reports/retention", headers=headers, params=params
        )

    # --- Ops-run checkpoint ----------------------------------------------------------
    def daily_close(self, headers):
        return self._request("POST", "/advising/ops/daily-close", {}, headers)


api_client = ApiClient()
