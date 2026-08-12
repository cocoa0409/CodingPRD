"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/campus-recruiting/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- RecruitingSeason ----
    def create_season(self, payload, headers):
        return self._request("POST", "/campus-recruiting/seasons", payload, headers)

    def list_seasons(self, headers, params=None):
        return self._request("GET", "/campus-recruiting/seasons", headers=headers, params=params)

    def get_season(self, season_id, headers):
        return self._request("GET", f"/campus-recruiting/seasons/{season_id}", headers=headers)

    def advance_season(self, season_id, headers):
        return self._request("POST", f"/campus-recruiting/seasons/{season_id}/advance", {}, headers)

    def close_season(self, season_id, headers):
        return self._request("POST", f"/campus-recruiting/seasons/{season_id}/close", {}, headers)

    def get_conversion_summary(self, season_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/seasons/{season_id}/conversion-summary",
            headers=headers,
        )

    # ---- SchoolTarget ----
    def create_school_target(self, season_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/seasons/{season_id}/school-targets",
            payload, headers,
        )

    def list_school_targets(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/seasons/{season_id}/school-targets",
            headers=headers, params=params,
        )

    def get_school_target(self, school_target_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/school-targets/{school_target_id}", headers=headers,
        )

    def patch_school_target(self, school_target_id, payload, headers):
        return self._request(
            "PATCH", f"/campus-recruiting/school-targets/{school_target_id}",
            payload, headers,
        )

    def drop_school_target(self, school_target_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/school-targets/{school_target_id}/drop",
            {}, headers,
        )

    # ---- CampusEvent ----
    def create_campus_event(self, season_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/seasons/{season_id}/campus-events",
            payload, headers,
        )

    def get_campus_event(self, event_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/campus-events/{event_id}", headers=headers,
        )

    def list_season_campus_events(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/seasons/{season_id}/campus-events",
            headers=headers, params=params,
        )

    def list_school_target_campus_events(self, school_target_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/school-targets/{school_target_id}/campus-events",
            headers=headers, params=params,
        )

    def complete_campus_event(self, event_id, resume_count, headers):
        return self._request(
            "POST", f"/campus-recruiting/campus-events/{event_id}/complete",
            {"resume_count": resume_count}, headers,
        )

    def cancel_campus_event(self, event_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/campus-events/{event_id}/cancel", {}, headers,
        )

    # ---- Candidate ----
    def create_candidate(self, payload, headers=None):
        return self._request("POST", "/campus-recruiting/candidates", payload, headers)

    def get_candidate(self, candidate_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/candidates/{candidate_id}", headers=headers,
        )

    def list_candidate_applications(self, candidate_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/candidates/{candidate_id}/applications",
            headers=headers, params=params,
        )

    # ---- Application ----
    def create_application(self, season_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/seasons/{season_id}/applications",
            payload, headers,
        )

    def get_application(self, application_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/applications/{application_id}", headers=headers,
        )

    def list_season_applications(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/seasons/{season_id}/applications",
            headers=headers, params=params,
        )

    def list_school_target_applications(self, school_target_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/school-targets/{school_target_id}/applications",
            headers=headers, params=params,
        )

    def screen_application(self, application_id, decision, headers):
        return self._request(
            "POST", f"/campus-recruiting/applications/{application_id}/screen",
            {"decision": decision}, headers,
        )

    def reject_application(self, application_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/applications/{application_id}/reject",
            {}, headers,
        )

    def withdraw_application(self, application_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/applications/{application_id}/withdraw",
            {}, headers,
        )

    # ---- Employee ----
    def create_employee(self, season_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/seasons/{season_id}/employees",
            payload, headers,
        )

    def list_employees(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/seasons/{season_id}/employees",
            headers=headers, params=params,
        )

    def get_employee(self, employee_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/employees/{employee_id}", headers=headers,
        )

    def list_employee_interview_slots(self, employee_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/employees/{employee_id}/interview-slots",
            headers=headers, params=params,
        )

    def list_employee_project_assignments(self, employee_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/employees/{employee_id}/project-assignments",
            headers=headers, params=params,
        )

    def list_employee_evaluations(self, employee_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/employees/{employee_id}/evaluations",
            headers=headers, params=params,
        )

    # ---- InterviewDay ----
    def create_interview_day(self, season_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/seasons/{season_id}/interview-days",
            payload, headers,
        )

    def get_interview_day(self, day_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/interview-days/{day_id}", headers=headers,
        )

    def list_interview_days(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/seasons/{season_id}/interview-days",
            headers=headers, params=params,
        )

    def lock_interview_day(self, day_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/interview-days/{day_id}/lock", {}, headers,
        )

    def complete_interview_day(self, day_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/interview-days/{day_id}/complete", {}, headers,
        )

    def list_interview_day_slots(self, day_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/interview-days/{day_id}/interview-slots",
            headers=headers, params=params,
        )

    # ---- InterviewSlot ----
    def book_interview_slot(self, day_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/interview-days/{day_id}/interview-slots",
            payload, headers,
        )

    def get_interview_slot(self, slot_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/interview-slots/{slot_id}", headers=headers,
        )

    def cancel_interview_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/interview-slots/{slot_id}/cancel", {}, headers,
        )

    def no_show_interview_slot(self, slot_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/interview-slots/{slot_id}/no-show", {}, headers,
        )

    def list_application_slots(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/applications/{application_id}/interview-slots",
            headers=headers, params=params,
        )

    # ---- Evaluation ----
    def submit_evaluation(self, slot_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/interview-slots/{slot_id}/evaluations",
            payload, headers,
        )

    def revise_evaluation(self, evaluation_id, payload, headers):
        return self._request(
            "PUT", f"/campus-recruiting/evaluations/{evaluation_id}", payload, headers,
        )

    def get_evaluation(self, evaluation_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/evaluations/{evaluation_id}", headers=headers,
        )

    def list_slot_evaluations(self, slot_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/interview-slots/{slot_id}/evaluations",
            headers=headers, params=params,
        )

    # ---- Offer ----
    def create_offer(self, application_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/applications/{application_id}/offers",
            payload, headers,
        )

    def get_offer(self, offer_id, headers):
        return self._request("GET", f"/campus-recruiting/offers/{offer_id}", headers=headers)

    def list_application_offers(self, application_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/applications/{application_id}/offers",
            headers=headers, params=params,
        )

    def revise_offer(self, offer_id, payload, headers):
        return self._request(
            "PUT", f"/campus-recruiting/offers/{offer_id}", payload, headers,
        )

    def extend_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/offers/{offer_id}/extend", {}, headers,
        )

    def accept_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/offers/{offer_id}/accept", {}, headers,
        )

    def decline_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/offers/{offer_id}/decline", {}, headers,
        )

    def rescind_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/offers/{offer_id}/rescind", {}, headers,
        )

    def expire_offer(self, offer_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/offers/{offer_id}/expire", {}, headers,
        )

    def extend_offer_deadline(self, offer_id, additional_hours, headers):
        return self._request(
            "POST", f"/campus-recruiting/offers/{offer_id}/extend-deadline",
            {"additional_hours": additional_hours}, headers,
        )

    # ---- StipendDisbursement ----
    def list_offer_disbursements(self, offer_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/offers/{offer_id}/stipend-disbursements",
            headers=headers, params=params,
        )

    def get_disbursement(self, disbursement_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/stipend-disbursements/{disbursement_id}",
            headers=headers,
        )

    def disburse_stipend(self, disbursement_id, headers):
        return self._request(
            "POST",
            f"/campus-recruiting/stipend-disbursements/{disbursement_id}/disburse",
            {}, headers,
        )

    # ---- InternProject ----
    def create_intern_project(self, season_id, payload, headers):
        return self._request(
            "POST", f"/campus-recruiting/seasons/{season_id}/intern-projects",
            payload, headers,
        )

    def list_intern_projects(self, season_id, headers, params=None):
        return self._request(
            "GET", f"/campus-recruiting/seasons/{season_id}/intern-projects",
            headers=headers, params=params,
        )

    def get_intern_project(self, project_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/intern-projects/{project_id}", headers=headers,
        )

    def close_intern_project(self, project_id, headers):
        return self._request(
            "POST", f"/campus-recruiting/intern-projects/{project_id}/close", {}, headers,
        )

    def list_project_assignments(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/campus-recruiting/intern-projects/{project_id}/project-assignments",
            headers=headers, params=params,
        )

    # ---- ProjectAssignment ----
    def create_project_assignment(self, project_id, payload, headers):
        return self._request(
            "POST",
            f"/campus-recruiting/intern-projects/{project_id}/project-assignments",
            payload, headers,
        )

    def get_project_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/project-assignments/{assignment_id}",
            headers=headers,
        )

    def list_application_assignments(self, application_id, headers, params=None):
        return self._request(
            "GET",
            f"/campus-recruiting/applications/{application_id}/project-assignments",
            headers=headers, params=params,
        )

    def unassign_project_assignment(self, assignment_id, headers):
        return self._request(
            "POST",
            f"/campus-recruiting/project-assignments/{assignment_id}/unassign",
            {}, headers,
        )

    def complete_project_assignment(self, assignment_id, headers):
        return self._request(
            "POST",
            f"/campus-recruiting/project-assignments/{assignment_id}/complete",
            {}, headers,
        )

    def submit_intern_evaluation(self, assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/campus-recruiting/project-assignments/{assignment_id}/intern-evaluations",
            payload, headers,
        )

    def list_intern_evaluations(self, assignment_id, headers, params=None):
        return self._request(
            "GET",
            f"/campus-recruiting/project-assignments/{assignment_id}/intern-evaluations",
            headers=headers, params=params,
        )

    def get_intern_evaluation(self, intern_evaluation_id, headers):
        return self._request(
            "GET", f"/campus-recruiting/intern-evaluations/{intern_evaluation_id}",
            headers=headers,
        )

    def record_return_offer_outcome(self, assignment_id, outcome, headers):
        return self._request(
            "POST",
            f"/campus-recruiting/project-assignments/{assignment_id}/record-return-offer-outcome",
            {"outcome": outcome}, headers,
        )


api_client = ApiClient()
# The harness restarts the server before every test; never reuse a pooled
# keep-alive connection across a restart (it surfaces as ECONNRESET).
api_client.session.headers["Connection"] = "close"
