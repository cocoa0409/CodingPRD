"""API client: one method per endpoint defined in PRD §4.

All resources live under the flat /residency-programs namespace; the logical
clock test-driving endpoint is /_clock/set_current_utc (PRD §2.4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Residency programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/residency-programs", payload, headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/residency-programs", headers=headers, params=params)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/residency-programs/{program_id}", headers=headers)

    # --- Academic years ---
    def create_academic_year(self, payload, headers):
        return self._request("POST", "/residency-programs/academic-years", payload, headers)

    def list_academic_years(self, headers, params=None):
        return self._request("GET", "/residency-programs/academic-years", headers=headers, params=params)

    def get_academic_year(self, year_id, headers):
        return self._request("GET", f"/residency-programs/academic-years/{year_id}", headers=headers)

    def activate_academic_year(self, year_id, headers):
        return self._request("POST", f"/residency-programs/academic-years/{year_id}/activate", {}, headers)

    def close_academic_year(self, year_id, headers):
        return self._request("POST", f"/residency-programs/academic-years/{year_id}/close", {}, headers)

    def regenerate_blocks(self, year_id, payload, headers):
        return self._request("POST", f"/residency-programs/academic-years/{year_id}/regenerate-blocks", payload, headers)

    # --- Schedule blocks ---
    def list_schedule_blocks(self, headers, params=None):
        return self._request("GET", "/residency-programs/schedule-blocks", headers=headers, params=params)

    def get_schedule_block(self, block_id, headers):
        return self._request("GET", f"/residency-programs/schedule-blocks/{block_id}", headers=headers)

    # --- Complement approvals ---
    def create_complement(self, payload, headers):
        return self._request("POST", "/residency-programs/complement-approvals", payload, headers)

    def list_complements(self, headers, params=None):
        return self._request("GET", "/residency-programs/complement-approvals", headers=headers, params=params)

    def get_complement(self, complement_id, headers):
        return self._request("GET", f"/residency-programs/complement-approvals/{complement_id}", headers=headers)

    def update_complement(self, complement_id, payload, headers):
        return self._request("PUT", f"/residency-programs/complement-approvals/{complement_id}", payload, headers)

    def submit_complement(self, complement_id, headers):
        return self._request("POST", f"/residency-programs/complement-approvals/{complement_id}/submit", {}, headers)

    def approve_complement(self, complement_id, headers):
        return self._request("POST", f"/residency-programs/complement-approvals/{complement_id}/approve", {}, headers)

    def reject_complement(self, complement_id, headers):
        return self._request("POST", f"/residency-programs/complement-approvals/{complement_id}/reject", {}, headers)

    def lock_complement(self, complement_id, headers):
        return self._request("POST", f"/residency-programs/complement-approvals/{complement_id}/lock", {}, headers)

    # --- Residents ---
    def create_resident(self, payload, headers):
        return self._request("POST", "/residency-programs/residents", payload, headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/residency-programs/residents", headers=headers, params=params)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residency-programs/residents/{resident_id}", headers=headers)

    def activate_resident(self, resident_id, headers):
        return self._request("POST", f"/residency-programs/residents/{resident_id}/activate", {}, headers)

    def place_on_leave(self, resident_id, headers):
        return self._request("POST", f"/residency-programs/residents/{resident_id}/place-on-leave", {}, headers)

    def return_from_leave(self, resident_id, headers):
        return self._request("POST", f"/residency-programs/residents/{resident_id}/return-from-leave", {}, headers)

    def graduate_resident(self, resident_id, headers):
        return self._request("POST", f"/residency-programs/residents/{resident_id}/graduate", {}, headers)

    def transfer_resident(self, resident_id, headers):
        return self._request("POST", f"/residency-programs/residents/{resident_id}/transfer", {}, headers)

    def get_duty_hour_summary(self, resident_id, week_start, headers):
        return self._request("GET", f"/residency-programs/residents/{resident_id}/duty-hour-summary",
                             {"week_start": week_start}, headers)

    def get_case_progress(self, resident_id, headers):
        return self._request("GET", f"/residency-programs/residents/{resident_id}/case-progress",
                             headers=headers)

    # --- Rotations ---
    def create_rotation(self, payload, headers):
        return self._request("POST", "/residency-programs/rotations", payload, headers)

    def list_rotations(self, headers, params=None):
        return self._request("GET", "/residency-programs/rotations", headers=headers, params=params)

    def get_rotation(self, rotation_id, headers):
        return self._request("GET", f"/residency-programs/rotations/{rotation_id}", headers=headers)

    def update_rotation(self, rotation_id, payload, headers):
        return self._request("PUT", f"/residency-programs/rotations/{rotation_id}", payload, headers)

    def retire_rotation(self, rotation_id, headers):
        return self._request("POST", f"/residency-programs/rotations/{rotation_id}/retire", {}, headers)

    # --- Rotation assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/residency-programs/rotation-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/residency-programs/rotation-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/residency-programs/rotation-assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/residency-programs/rotation-assignments/{assignment_id}/confirm", {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/residency-programs/rotation-assignments/{assignment_id}/complete", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/residency-programs/rotation-assignments/{assignment_id}/cancel", {}, headers)

    # --- Duty-hour logs ---
    def create_duty_log(self, payload, headers):
        return self._request("POST", "/residency-programs/duty-hour-logs", payload, headers)

    def list_duty_logs(self, headers, params=None):
        return self._request("GET", "/residency-programs/duty-hour-logs", headers=headers, params=params)

    def get_duty_log(self, log_id, headers):
        return self._request("GET", f"/residency-programs/duty-hour-logs/{log_id}", headers=headers)

    def attest_duty_log(self, log_id, headers):
        return self._request("POST", f"/residency-programs/duty-hour-logs/{log_id}/attest", {}, headers)

    def void_duty_log(self, log_id, payload, headers):
        return self._request("POST", f"/residency-programs/duty-hour-logs/{log_id}/void", payload, headers)

    # --- Duty-hour violations ---
    def list_violations(self, headers, params=None):
        return self._request("GET", "/residency-programs/duty-hour-violations", headers=headers, params=params)

    def get_violation(self, violation_id, headers):
        return self._request("GET", f"/residency-programs/duty-hour-violations/{violation_id}", headers=headers)

    def acknowledge_violation(self, violation_id, headers):
        return self._request("POST", f"/residency-programs/duty-hour-violations/{violation_id}/acknowledge", {}, headers)

    def resolve_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/residency-programs/duty-hour-violations/{violation_id}/resolve", payload, headers)

    def dismiss_violation(self, violation_id, payload, headers):
        return self._request("POST", f"/residency-programs/duty-hour-violations/{violation_id}/dismiss", payload, headers)

    # --- Moonlighting requests ---
    def create_moonlighting(self, payload, headers):
        return self._request("POST", "/residency-programs/moonlighting-requests", payload, headers)

    def list_moonlighting(self, headers, params=None):
        return self._request("GET", "/residency-programs/moonlighting-requests", headers=headers, params=params)

    def get_moonlighting(self, request_id, headers):
        return self._request("GET", f"/residency-programs/moonlighting-requests/{request_id}", headers=headers)

    def submit_moonlighting(self, request_id, headers):
        return self._request("POST", f"/residency-programs/moonlighting-requests/{request_id}/submit", {}, headers)

    def approve_moonlighting(self, request_id, headers):
        return self._request("POST", f"/residency-programs/moonlighting-requests/{request_id}/approve", {}, headers)

    def deny_moonlighting(self, request_id, payload, headers):
        return self._request("POST", f"/residency-programs/moonlighting-requests/{request_id}/deny", payload, headers)

    def withdraw_moonlighting(self, request_id, headers):
        return self._request("POST", f"/residency-programs/moonlighting-requests/{request_id}/withdraw", {}, headers)

    def revoke_moonlighting(self, request_id, payload, headers):
        return self._request("POST", f"/residency-programs/moonlighting-requests/{request_id}/revoke", payload, headers)

    # --- Milestone evaluations ---
    def create_evaluation(self, payload, headers):
        return self._request("POST", "/residency-programs/milestone-evaluations", payload, headers)

    def list_evaluations(self, headers, params=None):
        return self._request("GET", "/residency-programs/milestone-evaluations", headers=headers, params=params)

    def get_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/residency-programs/milestone-evaluations/{evaluation_id}", headers=headers)

    # --- CCC reviews ---
    def create_ccc_review(self, payload, headers):
        return self._request("POST", "/residency-programs/ccc-reviews", payload, headers)

    def list_ccc_reviews(self, headers, params=None):
        return self._request("GET", "/residency-programs/ccc-reviews", headers=headers, params=params)

    def get_ccc_review(self, review_id, headers):
        return self._request("GET", f"/residency-programs/ccc-reviews/{review_id}", headers=headers)

    def begin_deliberation(self, review_id, headers):
        return self._request("POST", f"/residency-programs/ccc-reviews/{review_id}/begin-deliberation", {}, headers)

    def finalize_ccc_review(self, review_id, payload, headers):
        return self._request("POST", f"/residency-programs/ccc-reviews/{review_id}/finalize", payload, headers)

    def reopen_ccc_review(self, review_id, headers):
        return self._request("POST", f"/residency-programs/ccc-reviews/{review_id}/reopen", {}, headers)

    # --- Procedure case logs ---
    def create_case_log(self, payload, headers):
        return self._request("POST", "/residency-programs/procedure-case-logs", payload, headers)

    def list_case_logs(self, headers, params=None):
        return self._request("GET", "/residency-programs/procedure-case-logs", headers=headers, params=params)

    def get_case_log(self, log_id, headers):
        return self._request("GET", f"/residency-programs/procedure-case-logs/{log_id}", headers=headers)

    def verify_case_log(self, log_id, headers):
        return self._request("POST", f"/residency-programs/procedure-case-logs/{log_id}/verify", {}, headers)

    def reject_case_log(self, log_id, payload, headers):
        return self._request("POST", f"/residency-programs/procedure-case-logs/{log_id}/reject", payload, headers)

    def resubmit_case_log(self, log_id, headers):
        return self._request("POST", f"/residency-programs/procedure-case-logs/{log_id}/resubmit", {}, headers)

    def void_case_log(self, log_id, payload, headers):
        return self._request("POST", f"/residency-programs/procedure-case-logs/{log_id}/void", payload, headers)

    # --- Case requirements ---
    def create_case_requirement(self, payload, headers):
        return self._request("POST", "/residency-programs/case-requirements", payload, headers)

    def list_case_requirements(self, headers, params=None):
        return self._request("GET", "/residency-programs/case-requirements", headers=headers, params=params)

    def get_case_requirement(self, requirement_id, headers):
        return self._request("GET", f"/residency-programs/case-requirements/{requirement_id}", headers=headers)

    # --- Remediation plans ---
    def create_remediation_plan(self, payload, headers):
        return self._request("POST", "/residency-programs/remediation-plans", payload, headers)

    def list_remediation_plans(self, headers, params=None):
        return self._request("GET", "/residency-programs/remediation-plans", headers=headers, params=params)

    def get_remediation_plan(self, plan_id, headers):
        return self._request("GET", f"/residency-programs/remediation-plans/{plan_id}", headers=headers)

    def complete_remediation_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/residency-programs/remediation-plans/{plan_id}/complete", payload, headers)

    def cancel_remediation_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/residency-programs/remediation-plans/{plan_id}/cancel", payload, headers)

    # --- Probation cases ---
    def create_probation_case(self, payload, headers):
        return self._request("POST", "/residency-programs/probation-cases", payload, headers)

    def list_probation_cases(self, headers, params=None):
        return self._request("GET", "/residency-programs/probation-cases", headers=headers, params=params)

    def get_probation_case(self, case_id, headers):
        return self._request("GET", f"/residency-programs/probation-cases/{case_id}", headers=headers)

    def lift_probation_case(self, case_id, headers):
        return self._request("POST", f"/residency-programs/probation-cases/{case_id}/lift", {}, headers)

    def recommend_dismissal(self, case_id, headers):
        return self._request("POST", f"/residency-programs/probation-cases/{case_id}/recommend-dismissal", {}, headers)

    def confirm_dismissal(self, case_id, headers):
        return self._request("POST", f"/residency-programs/probation-cases/{case_id}/confirm-dismissal", {}, headers)

    # --- Accreditation citations ---
    def create_citation(self, payload, headers):
        return self._request("POST", "/residency-programs/accreditation-citations", payload, headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/residency-programs/accreditation-citations", headers=headers, params=params)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/residency-programs/accreditation-citations/{citation_id}", headers=headers)

    def draft_citation_response(self, citation_id, payload, headers):
        return self._request("POST", f"/residency-programs/accreditation-citations/{citation_id}/draft-response", payload, headers)

    def submit_citation_response(self, citation_id, headers):
        return self._request("POST", f"/residency-programs/accreditation-citations/{citation_id}/submit-response", {}, headers)

    def resolve_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/residency-programs/accreditation-citations/{citation_id}/resolve", payload, headers)

    def escalate_citation(self, citation_id, payload, headers):
        return self._request("POST", f"/residency-programs/accreditation-citations/{citation_id}/escalate", payload, headers)

    # --- Annual surveys ---
    def create_survey(self, payload, headers):
        return self._request("POST", "/residency-programs/annual-surveys", payload, headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/residency-programs/annual-surveys", headers=headers, params=params)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/residency-programs/annual-surveys/{survey_id}", headers=headers)

    def close_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/residency-programs/annual-surveys/{survey_id}/close", payload, headers)


api_client = ApiClient()
