"""API client: one method per endpoint defined in the PRD (§4).

Subclasses GenericApiClient; the base _request() is inherited. All paths are
under the /clinic prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601: str, headers):
        return self._request("POST", "/clinic/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Children ----
    def create_child(self, payload, headers):
        return self._request("POST", "/clinic/children", payload, headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/clinic/children", headers=headers, params=params)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/clinic/children/{child_id}", headers=headers)

    def discharge_child(self, child_id, headers):
        return self._request("POST", f"/clinic/children/{child_id}/discharge", headers=headers)

    def list_child_authorizations(self, child_id, headers, params=None):
        return self._request("GET", f"/clinic/children/{child_id}/authorizations",
                             headers=headers, params=params)

    def list_child_coordination_plans(self, child_id, headers, params=None):
        return self._request("GET", f"/clinic/children/{child_id}/coordination-plans",
                             headers=headers, params=params)

    # ---- Therapists ----
    def create_therapist(self, payload, headers):
        return self._request("POST", "/clinic/therapists", payload, headers)

    def list_therapists(self, headers, params=None):
        return self._request("GET", "/clinic/therapists", headers=headers, params=params)

    def get_therapist(self, therapist_id, headers):
        return self._request("GET", f"/clinic/therapists/{therapist_id}", headers=headers)

    # ---- Evaluations ----
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/clinic/evaluations", payload, headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/clinic/evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/clinic/evaluations/{evaluation_id}", headers=headers)

    def finalize_evaluation(self, evaluation_id, headers):
        return self._request("POST", f"/clinic/evaluations/{evaluation_id}/finalize",
                             {}, headers)

    # ---- Plans of Care ----
    def create_plan_of_care(self, payload, headers):
        return self._request("POST", "/clinic/plans-of-care", payload, headers)

    def list_plans_of_care(self, headers, params=None):
        return self._request("GET", "/clinic/plans-of-care", headers=headers, params=params)

    def get_plan_of_care(self, plan_id, headers):
        return self._request("GET", f"/clinic/plans-of-care/{plan_id}", headers=headers)

    def activate_plan_of_care(self, plan_id, headers):
        return self._request("POST", f"/clinic/plans-of-care/{plan_id}/activate", {}, headers)

    def hold_plan_of_care(self, plan_id, headers):
        return self._request("POST", f"/clinic/plans-of-care/{plan_id}/hold", {}, headers)

    def discharge_plan_of_care(self, plan_id, headers):
        return self._request("POST", f"/clinic/plans-of-care/{plan_id}/discharge", {}, headers)

    # ---- Goals ----
    def list_goals(self, plan_id, headers, params=None):
        return self._request("GET", f"/clinic/plans-of-care/{plan_id}/goals",
                             headers=headers, params=params)

    def create_goal(self, plan_id, payload, headers):
        return self._request("POST", f"/clinic/plans-of-care/{plan_id}/goals", payload, headers)

    def get_goal(self, goal_id, headers):
        return self._request("GET", f"/clinic/goals/{goal_id}", headers=headers)

    def discontinue_goal(self, goal_id, headers):
        return self._request("POST", f"/clinic/goals/{goal_id}/discontinue", {}, headers)

    def list_goal_progress_entries(self, goal_id, headers, params=None):
        return self._request("GET", f"/clinic/goals/{goal_id}/progress-entries",
                             headers=headers, params=params)

    # ---- Authorizations ----
    def create_authorization(self, payload, headers):
        return self._request("POST", "/clinic/authorizations", payload, headers)

    def get_authorization(self, authorization_id, headers):
        return self._request("GET", f"/clinic/authorizations/{authorization_id}", headers=headers)

    def request_reauth(self, authorization_id, payload, headers):
        return self._request("POST", f"/clinic/authorizations/{authorization_id}/request-reauth",
                             payload, headers)

    def grant_reauth(self, authorization_id, payload, headers):
        return self._request("POST", f"/clinic/authorizations/{authorization_id}/grant-reauth",
                             payload, headers)

    def close_authorization(self, authorization_id, headers):
        return self._request("POST", f"/clinic/authorizations/{authorization_id}/close", {}, headers)

    # ---- Appointments ----
    def create_appointment(self, payload, headers):
        return self._request("POST", "/clinic/appointments", payload, headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/clinic/appointments", headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/clinic/appointments/{appointment_id}", headers=headers)

    def complete_appointment(self, appointment_id, payload, headers):
        return self._request("POST", f"/clinic/appointments/{appointment_id}/complete",
                             payload, headers)

    def cancel_appointment(self, appointment_id, headers):
        return self._request("POST", f"/clinic/appointments/{appointment_id}/cancel", {}, headers)

    def no_show_appointment(self, appointment_id, headers):
        return self._request("POST", f"/clinic/appointments/{appointment_id}/no-show", {}, headers)

    def list_session_notes(self, appointment_id, headers, params=None):
        return self._request("GET", f"/clinic/appointments/{appointment_id}/session-notes",
                             headers=headers, params=params)

    def get_session_note(self, session_note_id, headers):
        return self._request("GET", f"/clinic/session-notes/{session_note_id}", headers=headers)

    # ---- Coordination Plans ----
    def create_coordination_plan(self, payload, headers):
        return self._request("POST", "/clinic/coordination-plans", payload, headers)

    def get_coordination_plan(self, coordination_plan_id, headers):
        return self._request("GET", f"/clinic/coordination-plans/{coordination_plan_id}",
                             headers=headers)

    def activate_coordination_plan(self, coordination_plan_id, headers):
        return self._request("POST",
                             f"/clinic/coordination-plans/{coordination_plan_id}/activate",
                             {}, headers)

    def begin_transition_coordination_plan(self, coordination_plan_id, headers):
        return self._request("POST",
                             f"/clinic/coordination-plans/{coordination_plan_id}/begin-transition",
                             {}, headers)

    def close_coordination_plan(self, coordination_plan_id, headers):
        return self._request("POST",
                             f"/clinic/coordination-plans/{coordination_plan_id}/close",
                             {}, headers)

    # ---- Home Programs / Parent Training ----
    def create_home_program(self, plan_id, payload, headers):
        return self._request("POST", f"/clinic/plans-of-care/{plan_id}/home-programs",
                             payload, headers)

    def list_home_programs(self, headers, params=None):
        return self._request("GET", "/clinic/home-programs", headers=headers, params=params)

    def get_home_program(self, home_program_id, headers):
        return self._request("GET", f"/clinic/home-programs/{home_program_id}", headers=headers)

    def activate_home_program(self, home_program_id, headers, payload=None):
        return self._request("POST", f"/clinic/home-programs/{home_program_id}/activate",
                             payload if payload is not None else {}, headers)

    def complete_home_program(self, home_program_id, headers):
        return self._request("POST", f"/clinic/home-programs/{home_program_id}/complete",
                             {}, headers)

    def cancel_home_program(self, home_program_id, headers):
        return self._request("POST", f"/clinic/home-programs/{home_program_id}/cancel",
                             {}, headers)

    # ---- Waitlist ----
    def create_waitlist_entry(self, payload, headers):
        return self._request("POST", "/clinic/waitlist-entries", payload, headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/clinic/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("GET", f"/clinic/waitlist-entries/{waitlist_entry_id}",
                             headers=headers)

    def accept_waitlist_entry(self, waitlist_entry_id, payload, headers):
        return self._request("POST", f"/clinic/waitlist-entries/{waitlist_entry_id}/accept",
                             payload, headers)

    def decline_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/clinic/waitlist-entries/{waitlist_entry_id}/decline",
                             {}, headers)

    def withdraw_waitlist_entry(self, waitlist_entry_id, headers):
        return self._request("POST", f"/clinic/waitlist-entries/{waitlist_entry_id}/withdraw",
                             {}, headers)


api_client = ApiClient()
