"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Reporting portals -------------------------------------------------
    def create_reporting_portal(self, payload, headers):
        return self._request("POST", "/reporting-portals", payload, headers)

    # --- Wage determinations ----------------------------------------------
    def create_wage_determination(self, payload, headers):
        return self._request("POST", "/wage-determinations", payload, headers)

    def add_wage_rate(self, determination_id, payload, headers):
        return self._request(
            "POST", f"/wage-determinations/{determination_id}/wage-rates", payload, headers
        )

    def list_wage_rates(self, determination_id, headers, params=None):
        return self._request(
            "GET", f"/wage-determinations/{determination_id}/wage-rates",
            headers=headers, params=params,
        )

    def activate_wage_determination(self, determination_id, headers, payload=None):
        return self._request(
            "POST", f"/wage-determinations/{determination_id}/activate",
            payload if payload is not None else {}, headers,
        )

    def list_wage_determinations(self, headers, params=None):
        return self._request("GET", "/wage-determinations", headers=headers, params=params)

    def get_wage_determination(self, determination_id, headers):
        return self._request("GET", f"/wage-determinations/{determination_id}", headers=headers)

    # --- Apprenticeship programs ------------------------------------------
    def create_apprentice_program(self, payload, headers):
        return self._request("POST", "/apprentice-programs", payload, headers)

    def update_apprentice_program(self, program_id, payload, headers):
        return self._request("PATCH", f"/apprentice-programs/{program_id}", payload, headers)

    # --- Contractors -------------------------------------------------------
    def create_contractor(self, payload, headers):
        return self._request("POST", "/contractors", payload, headers)

    def list_contractors(self, headers, params=None):
        return self._request("GET", "/contractors", headers=headers, params=params)

    def get_contractor(self, contractor_id, headers):
        return self._request("GET", f"/contractors/{contractor_id}", headers=headers)

    def decide_debarment(self, contractor_id, payload, headers):
        return self._request("POST", f"/contractors/{contractor_id}/debarment", payload, headers)

    def add_staff(self, contractor_id, payload, headers):
        return self._request("POST", f"/contractors/{contractor_id}/staff", payload, headers)

    def list_staff(self, contractor_id, headers, params=None):
        return self._request(
            "GET", f"/contractors/{contractor_id}/staff", headers=headers, params=params
        )

    # --- Fringe benefit plans ---------------------------------------------
    def create_fringe_plan(self, contractor_id, payload, headers):
        return self._request(
            "POST", f"/contractors/{contractor_id}/fringe-plans", payload, headers
        )

    def list_fringe_plans(self, contractor_id, headers, params=None):
        return self._request(
            "GET", f"/contractors/{contractor_id}/fringe-plans", headers=headers, params=params
        )

    def approve_fringe_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/fringe-plans/{plan_id}/approve", payload, headers)

    # --- Projects ----------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def set_project_status(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/status", payload, headers)

    # --- Contract assignments ---------------------------------------------
    def create_contract_assignment(self, project_id, payload, headers):
        return self._request(
            "POST", f"/projects/{project_id}/contract-assignments", payload, headers
        )

    def list_project_contract_assignments(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/projects/{project_id}/contract-assignments",
            headers=headers, params=params,
        )

    def list_contract_assignments(self, headers, params=None):
        return self._request("GET", "/contract-assignments", headers=headers, params=params)

    def get_contract_assignment(self, assignment_id, headers):
        return self._request("GET", f"/contract-assignments/{assignment_id}", headers=headers)

    def activate_contract_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/contract-assignments/{assignment_id}/activate", {}, headers
        )

    def reinstate_contract_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"/contract-assignments/{assignment_id}/reinstate", payload, headers
        )

    # --- Workers -----------------------------------------------------------
    def create_worker(self, payload, headers):
        return self._request("POST", "/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/workers/{worker_id}", headers=headers)

    # --- Payroll submissions ----------------------------------------------
    def create_payroll_submission(self, payload, headers):
        return self._request("POST", "/payroll-submissions", payload, headers)

    def list_payroll_submissions(self, headers, params=None):
        return self._request("GET", "/payroll-submissions", headers=headers, params=params)

    def get_payroll_submission(self, submission_id, headers):
        return self._request("GET", f"/payroll-submissions/{submission_id}", headers=headers)

    def add_payroll_line(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/payroll-submissions/{submission_id}/lines", payload, headers
        )

    def list_payroll_lines(self, headers, params=None):
        return self._request("GET", "/payroll-lines", headers=headers, params=params)

    def get_payroll_line(self, line_id, headers):
        return self._request("GET", f"/payroll-lines/{line_id}", headers=headers)

    def finalize_payroll_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/payroll-submissions/{submission_id}/finalize", {}, headers
        )

    def certify_payroll_submission(self, submission_id, headers, payload=None):
        return self._request(
            "POST", f"/payroll-submissions/{submission_id}/certify",
            payload if payload is not None else {}, headers,
        )

    def begin_review_payroll_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/payroll-submissions/{submission_id}/begin-review", {}, headers
        )

    def accept_payroll_submission(self, submission_id, headers):
        return self._request(
            "POST", f"/payroll-submissions/{submission_id}/accept", {}, headers
        )

    def return_payroll_submission(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/payroll-submissions/{submission_id}/return", payload, headers
        )

    def rescind_acceptance(self, submission_id, payload, headers):
        return self._request(
            "POST", f"/payroll-submissions/{submission_id}/rescind-acceptance", payload, headers
        )

    def get_underpayment_summary(self, submission_id, headers):
        return self._request(
            "GET", f"/payroll-submissions/{submission_id}/underpayment-summary", headers=headers
        )

    # --- Findings ----------------------------------------------------------
    def create_finding(self, payload, headers):
        return self._request("POST", "/findings", payload, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", "/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"/findings/{finding_id}", headers=headers)

    def file_finding_response(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/response", payload, headers)

    def review_finding_response(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/review-response", payload, headers)

    def withdraw_finding(self, finding_id, payload, headers):
        return self._request("POST", f"/findings/{finding_id}/withdraw", payload, headers)

    # --- Restitution payments ---------------------------------------------
    def create_restitution_payment(self, finding_id, payload, headers):
        return self._request(
            "POST", f"/findings/{finding_id}/restitution-payments", payload, headers
        )

    def list_restitution_payments(self, headers, params=None):
        return self._request("GET", "/restitution-payments", headers=headers, params=params)

    def get_restitution_payment(self, payment_id, headers):
        return self._request("GET", f"/restitution-payments/{payment_id}", headers=headers)

    def disburse_restitution_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/restitution-payments/{payment_id}/disburse", {}, headers
        )

    def reverse_restitution_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/restitution-payments/{payment_id}/reverse", payload, headers
        )

    # --- On-site interviews ------------------------------------------------
    def create_interview(self, payload, headers):
        return self._request("POST", "/interviews", payload, headers)

    def conduct_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/interviews/{interview_id}/conduct", payload, headers)

    def cancel_interview(self, interview_id, payload, headers):
        return self._request("POST", f"/interviews/{interview_id}/cancel", payload, headers)

    def list_interviews(self, headers, params=None):
        return self._request("GET", "/interviews", headers=headers, params=params)

    def get_interview(self, interview_id, headers):
        return self._request("GET", f"/interviews/{interview_id}", headers=headers)


api_client = ApiClient()
