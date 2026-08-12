"""API client: one method per endpoint defined in the PRD (§4 routing table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Typed endpoint methods for the College Career Readiness API."""

    # --- logical clock (PRD §2.5) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- advisors ---
    def create_advisor(self, payload, headers):
        return self._request("POST", "/ccr/advisors", payload, headers)

    def get_advisor(self, advisor_id, headers):
        return self._request("GET", f"/ccr/advisors/{advisor_id}", headers=headers)

    def list_advisor_students(self, advisor_id, headers, params=None):
        return self._request("GET", f"/ccr/advisors/{advisor_id}/students",
                             headers=headers, params=params)

    def list_advisor_senior_audits(self, advisor_id, headers):
        return self._request("GET", f"/ccr/advisors/{advisor_id}/senior-audits",
                             headers=headers)

    def deactivate_advisor(self, advisor_id, payload, headers):
        return self._request("POST", f"/ccr/advisors/{advisor_id}/deactivate",
                             payload, headers)

    def create_reassignment(self, advisor_id, payload, headers):
        return self._request("POST", f"/ccr/advisors/{advisor_id}/reassignments",
                             payload, headers)

    def get_equity_report(self, advisor_id, headers):
        return self._request("GET", f"/ccr/advisors/{advisor_id}/equity-report",
                             headers=headers)

    # --- teachers ---
    def create_teacher(self, payload, headers):
        return self._request("POST", "/ccr/teachers", payload, headers)

    def get_teacher(self, teacher_id, headers):
        return self._request("GET", f"/ccr/teachers/{teacher_id}", headers=headers)

    def patch_teacher(self, teacher_id, payload, headers):
        return self._request("PATCH", f"/ccr/teachers/{teacher_id}", payload, headers)

    def list_teacher_recommendation_requests(self, teacher_id, headers, params=None):
        return self._request("GET",
                             f"/ccr/teachers/{teacher_id}/recommendation-requests",
                             headers=headers, params=params)

    # --- pathways ---
    def create_pathway(self, payload, headers):
        return self._request("POST", "/ccr/pathways", payload, headers)

    def get_pathway(self, pathway_id, headers):
        return self._request("GET", f"/ccr/pathways/{pathway_id}", headers=headers)

    def patch_pathway(self, pathway_id, payload, headers):
        return self._request("PATCH", f"/ccr/pathways/{pathway_id}", payload, headers)

    def list_pathway_plans(self, pathway_id, headers):
        return self._request("GET", f"/ccr/pathways/{pathway_id}/plans",
                             headers=headers)

    # --- students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/ccr/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/ccr/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/ccr/students/{student_id}", headers=headers)

    def graduate_student(self, student_id, headers):
        return self._request("POST", f"/ccr/students/{student_id}/graduate",
                             None, headers)

    def withdraw_student(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/withdraw",
                             payload, headers)

    # --- plans ---
    def create_plan(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/plans",
                             payload, headers)

    def list_student_plans(self, student_id, headers, params=None):
        return self._request("GET", f"/ccr/students/{student_id}/plans",
                             headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/ccr/plans/{plan_id}", headers=headers)

    def patch_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/ccr/plans/{plan_id}", payload, headers)

    def activate_plan(self, plan_id, headers):
        return self._request("POST", f"/ccr/plans/{plan_id}/activate", None, headers)

    def revise_plan(self, plan_id, headers):
        return self._request("POST", f"/ccr/plans/{plan_id}/revise", None, headers)

    def list_plan_enrollments(self, plan_id, headers):
        return self._request("GET", f"/ccr/plans/{plan_id}/enrollments",
                             headers=headers)

    # --- enrollments ---
    def create_enrollment(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/enrollments",
                             payload, headers)

    def list_student_enrollments(self, student_id, headers, params=None):
        return self._request("GET", f"/ccr/students/{student_id}/enrollments",
                             headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/ccr/enrollments/{enrollment_id}",
                             headers=headers)

    def transition_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/ccr/enrollments/{enrollment_id}/transition",
                             payload, headers)

    # --- applications ---
    def create_application(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/applications",
                             payload, headers)

    def list_student_applications(self, student_id, headers, params=None):
        return self._request("GET", f"/ccr/students/{student_id}/applications",
                             headers=headers, params=params)

    def get_application(self, application_id, headers):
        return self._request("GET", f"/ccr/applications/{application_id}",
                             headers=headers)

    def transition_application(self, application_id, payload, headers):
        return self._request("POST",
                             f"/ccr/applications/{application_id}/transition",
                             payload, headers)

    def decide_application(self, application_id, payload, headers):
        return self._request("POST", f"/ccr/applications/{application_id}/decision",
                             payload, headers)

    # --- milestones ---
    def create_milestone(self, application_id, payload, headers):
        return self._request("POST", f"/ccr/applications/{application_id}/milestones",
                             payload, headers)

    def list_application_milestones(self, application_id, headers):
        return self._request("GET", f"/ccr/applications/{application_id}/milestones",
                             headers=headers)

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/ccr/milestones/{milestone_id}", headers=headers)

    def transition_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/ccr/milestones/{milestone_id}/transition",
                             payload, headers)

    def list_milestone_dependents(self, milestone_id, headers):
        return self._request("GET", f"/ccr/milestones/{milestone_id}/dependents",
                             headers=headers)

    # --- recommendation requests ---
    def create_recommendation_request(self, student_id, payload, headers):
        return self._request("POST",
                             f"/ccr/students/{student_id}/recommendation-requests",
                             payload, headers)

    def list_student_recommendation_requests(self, student_id, headers, params=None):
        return self._request("GET",
                             f"/ccr/students/{student_id}/recommendation-requests",
                             headers=headers, params=params)

    def get_recommendation_request(self, request_id, headers):
        return self._request("GET", f"/ccr/recommendation-requests/{request_id}",
                             headers=headers)

    def transition_recommendation_request(self, request_id, payload, headers):
        return self._request("POST",
                             f"/ccr/recommendation-requests/{request_id}/transition",
                             payload, headers)

    def list_application_recommendation_requests(self, application_id, headers):
        return self._request("GET",
                             f"/ccr/applications/{application_id}/recommendation-requests",
                             headers=headers)

    # --- certifications ---
    def create_certification(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/certifications",
                             payload, headers)

    def list_student_certifications(self, student_id, headers, params=None):
        return self._request("GET", f"/ccr/students/{student_id}/certifications",
                             headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/ccr/certifications/{certification_id}",
                             headers=headers)

    def transition_certification(self, certification_id, payload, headers):
        return self._request("POST",
                             f"/ccr/certifications/{certification_id}/transition",
                             payload, headers)

    # --- placement sites ---
    def create_placement_site(self, payload, headers):
        return self._request("POST", "/ccr/placement-sites", payload, headers)

    def get_placement_site(self, site_id, headers):
        return self._request("GET", f"/ccr/placement-sites/{site_id}", headers=headers)

    def patch_placement_site(self, site_id, payload, headers):
        return self._request("PATCH", f"/ccr/placement-sites/{site_id}",
                             payload, headers)

    def list_site_placements(self, site_id, headers, params=None):
        return self._request("GET", f"/ccr/placement-sites/{site_id}/placements",
                             headers=headers, params=params)

    # --- placements ---
    def create_placement(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/placements",
                             payload, headers)

    def list_student_placements(self, student_id, headers, params=None):
        return self._request("GET", f"/ccr/students/{student_id}/placements",
                             headers=headers, params=params)

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"/ccr/placements/{placement_id}", headers=headers)

    def transition_placement(self, placement_id, payload, headers):
        return self._request("POST", f"/ccr/placements/{placement_id}/transition",
                             payload, headers)

    # --- senior audits ---
    def create_senior_audit(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/senior-audits",
                             payload, headers)

    def list_student_senior_audits(self, student_id, headers):
        return self._request("GET", f"/ccr/students/{student_id}/senior-audits",
                             headers=headers)

    def get_senior_audit(self, audit_id, headers):
        return self._request("GET", f"/ccr/senior-audits/{audit_id}", headers=headers)

    def transition_senior_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/ccr/senior-audits/{audit_id}/transition",
                             payload, headers)

    # --- outcome records ---
    def create_outcome_record(self, student_id, payload, headers):
        return self._request("POST", f"/ccr/students/{student_id}/outcome-records",
                             payload, headers)

    def list_student_outcome_records(self, student_id, headers):
        return self._request("GET", f"/ccr/students/{student_id}/outcome-records",
                             headers=headers)

    def get_outcome_record(self, outcome_id, headers):
        return self._request("GET", f"/ccr/outcome-records/{outcome_id}",
                             headers=headers)

    def transition_outcome_record(self, outcome_id, payload, headers):
        return self._request("POST",
                             f"/ccr/outcome-records/{outcome_id}/transition",
                             payload, headers)

    # --- ops runs ---
    def create_ops_run(self, headers):
        return self._request("POST", "/ccr/ops-runs", None, headers)

    def get_ops_run(self, run_id, headers):
        return self._request("GET", f"/ccr/ops-runs/{run_id}", headers=headers)


api_client = ApiClient()
