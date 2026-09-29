"""API client: one method per endpoint defined in the PRD."""

from prd_bench_local_runner.testing import GenericApiClient

from .constants import API_PREFIX


class ApiClient(GenericApiClient):
    """Work-Based Learning API client. Every method returns the raw response."""

    # ---------------------------------------------------------------- clock
    def set_clock(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/_clock/set_current_utc", payload, headers)

    # ----------------------------------------------------- employer partners
    def create_employer_partner(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/employer-partners", payload, headers)

    def get_employer_partner(self, employer_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/employer-partners/{employer_id}", headers=headers
        )

    def list_employer_partners(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/employer-partners", headers=headers, params=params
        )

    def update_employer_partner_insurance(self, employer_id, payload, headers):
        return self._request(
            "PATCH",
            f"{API_PREFIX}/employer-partners/{employer_id}/insurance",
            payload,
            headers,
        )

    def list_employer_partner_worksites(self, employer_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/employer-partners/{employer_id}/worksites",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------- worksites
    def create_worksite(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/worksites", payload, headers)

    def get_worksite(self, worksite_id, headers):
        return self._request("GET", f"{API_PREFIX}/worksites/{worksite_id}", headers=headers)

    # -------------------------------------------------------- safety reviews
    def create_safety_review(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/safety-reviews", payload, headers)

    def decide_safety_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/safety-reviews/{review_id}/decision", payload, headers
        )

    def list_worksite_safety_reviews(self, worksite_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/worksites/{worksite_id}/safety-reviews",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------------- supervisors
    def create_supervisor(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/supervisors", payload, headers)

    def list_worksite_supervisors(self, worksite_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/worksites/{worksite_id}/supervisors",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ agreements
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/agreements", payload, headers)

    def employer_sign_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/employer-sign", payload, headers
        )

    def request_agreement_changes(self, agreement_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/agreements/{agreement_id}/request-changes",
            payload,
            headers,
        )

    def execute_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/execute", payload, headers
        )

    def terminate_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/agreements/{agreement_id}/terminate", payload, headers
        )

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"{API_PREFIX}/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/agreements", headers=headers, params=params)

    # -------------------------------------------------------------- students
    def create_student(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/students", payload, headers)

    def update_student_academics(self, student_id, payload, headers):
        return self._request(
            "PATCH", f"{API_PREFIX}/students/{student_id}/academics", payload, headers
        )

    def get_student(self, student_id, headers):
        return self._request("GET", f"{API_PREFIX}/students/{student_id}", headers=headers)

    # ----------------------------------------------------------- work permits
    def create_work_permit(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/work-permits", payload, headers)

    def issue_work_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/work-permits/{permit_id}/issue", payload, headers
        )

    def revoke_work_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/work-permits/{permit_id}/revoke", payload, headers
        )

    def list_student_work_permits(self, student_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/students/{student_id}/work-permits",
            headers=headers,
            params=params,
        )

    # ------------------------------------------------------------ placements
    def create_placement(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/placements", payload, headers)

    def activate_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/placements/{placement_id}/activate", payload, headers
        )

    def terminate_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/placements/{placement_id}/terminate", payload, headers
        )

    def complete_placement(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/placements/{placement_id}/complete", payload, headers
        )

    def placement_compliance_decision(self, placement_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/placements/{placement_id}/compliance-decision",
            payload,
            headers,
        )

    def settle_placement_wages(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/placements/{placement_id}/settle-wages", payload, headers
        )

    def award_placement_credit(self, placement_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/placements/{placement_id}/award-credit", payload, headers
        )

    def get_placement(self, placement_id, headers):
        return self._request("GET", f"{API_PREFIX}/placements/{placement_id}", headers=headers)

    def list_placements(self, headers, params=None):
        return self._request("GET", f"{API_PREFIX}/placements", headers=headers, params=params)

    def get_wage_preview(self, placement_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/placements/{placement_id}/wage-preview", headers=headers
        )

    def get_credit_preview(self, placement_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/placements/{placement_id}/credit-preview", headers=headers
        )

    def get_reimbursement(self, placement_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/placements/{placement_id}/reimbursement", headers=headers
        )

    # -------------------------------------------------------- training plans
    def create_training_plan(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/training-plans", payload, headers)

    def submit_training_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/training-plans/{plan_id}/submit", payload, headers
        )

    def request_training_plan_changes(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/training-plans/{plan_id}/request-changes", payload, headers
        )

    def approve_training_plan(self, plan_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/training-plans/{plan_id}/approve", payload, headers
        )

    def get_training_plan(self, plan_id, headers):
        return self._request("GET", f"{API_PREFIX}/training-plans/{plan_id}", headers=headers)

    def list_placement_training_plans(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/placements/{placement_id}/training-plans",
            headers=headers,
            params=params,
        )

    # --------------------------------------------------- learning objectives
    def create_learning_objective(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/learning-objectives", payload, headers)

    def list_training_plan_objectives(self, plan_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/training-plans/{plan_id}/objectives",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------- timesheet entries
    def create_timesheet_entry(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/timesheet-entries", payload, headers)

    def void_timesheet_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/timesheet-entries/{entry_id}/void", payload, headers
        )

    def list_placement_timesheet_entries(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/placements/{placement_id}/timesheet-entries",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------- evaluation cycles
    def submit_evaluation(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/evaluation-cycles/{cycle_id}/evaluation", payload, headers
        )

    def submit_reflection(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/evaluation-cycles/{cycle_id}/reflection", payload, headers
        )

    def decide_reflection(self, cycle_id, payload, headers):
        return self._request(
            "POST",
            f"{API_PREFIX}/evaluation-cycles/{cycle_id}/reflection-decision",
            payload,
            headers,
        )

    def list_placement_evaluation_cycles(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/placements/{placement_id}/evaluation-cycles",
            headers=headers,
            params=params,
        )

    # ----------------------------------------------------- incident reports
    def create_incident_report(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/incident-reports", payload, headers)

    def record_incident_finding(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/incident-reports/{incident_id}/finding", payload, headers
        )

    def record_incident_coverage(self, incident_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/incident-reports/{incident_id}/coverage", payload, headers
        )

    def get_incident_report(self, incident_id, headers):
        return self._request(
            "GET", f"{API_PREFIX}/incident-reports/{incident_id}", headers=headers
        )

    def list_incident_reports(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/incident-reports", headers=headers, params=params
        )

    # --------------------------------------------------- placement outcomes
    def create_placement_outcome(self, payload, headers):
        return self._request("POST", f"{API_PREFIX}/placement-outcomes", payload, headers)

    def verify_placement_outcome(self, outcome_id, payload, headers):
        return self._request(
            "POST", f"{API_PREFIX}/placement-outcomes/{outcome_id}/verify", payload, headers
        )

    def list_placement_outcomes(self, placement_id, headers, params=None):
        return self._request(
            "GET",
            f"{API_PREFIX}/placements/{placement_id}/outcomes",
            headers=headers,
            params=params,
        )

    def get_outcome_rate_report(self, headers, params=None):
        return self._request(
            "GET", f"{API_PREFIX}/reports/outcome-rate", headers=headers, params=params
        )


api_client = ApiClient()
