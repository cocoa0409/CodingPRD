"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.10)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Team members (PRD §3.1)
    # ------------------------------------------------------------------
    def create_team_member(self, payload, headers):
        return self._request("POST", "/team-members", payload, headers)

    def list_team_members(self, headers, params=None):
        return self._request("GET", "/team-members", headers=headers, params=params)

    def get_team_member(self, member_id, headers):
        return self._request("GET", f"/team-members/{member_id}", headers=headers)

    # ------------------------------------------------------------------
    # Credit library (PRD §3.2)
    # ------------------------------------------------------------------
    def create_credit_library_entry(self, payload, headers):
        return self._request("POST", "/credit-library-entries", payload, headers)

    def list_credit_library_entries(self, headers, params=None):
        return self._request("GET", "/credit-library-entries", headers=headers, params=params)

    def get_credit_library_entry(self, entry_id, headers):
        return self._request("GET", f"/credit-library-entries/{entry_id}", headers=headers)

    # ------------------------------------------------------------------
    # Certification projects (PRD §3.1, §3.4, §3.7, §3.8)
    # ------------------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/certification-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/certification-projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request(
            "GET", f"/certification-projects/{project_id}", headers=headers
        )

    def lock_strategy(self, project_id, expected_project_version, headers):
        return self._request(
            "POST",
            f"/certification-projects/{project_id}/lock-strategy",
            {"expected_project_version": expected_project_version},
            headers,
        )

    def submit_phase(self, project_id, phase, headers):
        return self._request(
            "POST",
            f"/certification-projects/{project_id}/submit-phase",
            {"phase": phase},
            headers,
        )

    def withdraw_phase(self, project_id, phase, headers):
        return self._request(
            "POST",
            f"/certification-projects/{project_id}/withdraw-phase",
            {"phase": phase},
            headers,
        )

    def issue_decision(self, project_id, decision, headers):
        return self._request(
            "POST",
            f"/certification-projects/{project_id}/issue-decision",
            {"decision": decision},
            headers,
        )

    def submit_recertification(self, project_id, headers):
        return self._request(
            "POST",
            f"/certification-projects/{project_id}/submit-recertification",
            {},
            headers,
        )

    def confirm_recertification(self, project_id, outcome, headers):
        return self._request(
            "POST",
            f"/certification-projects/{project_id}/confirm-recertification",
            {"outcome": outcome},
            headers,
        )

    def list_project_performance_reports(self, project_id, headers):
        return self._request(
            "GET",
            f"/certification-projects/{project_id}/performance-reports",
            headers=headers,
        )

    def get_project_cost_premium_analysis(self, project_id, headers):
        return self._request(
            "GET",
            f"/certification-projects/{project_id}/cost-premium-analysis",
            headers=headers,
        )

    # ------------------------------------------------------------------
    # Energy models (PRD §3.3)
    # ------------------------------------------------------------------
    def create_energy_model(self, payload, headers):
        return self._request("POST", "/energy-models", payload, headers)

    def list_energy_models(self, headers, params=None):
        return self._request("GET", "/energy-models", headers=headers, params=params)

    def get_energy_model(self, model_id, headers):
        return self._request("GET", f"/energy-models/{model_id}", headers=headers)

    def lock_energy_model(self, model_id, headers):
        return self._request("POST", f"/energy-models/{model_id}/lock", {}, headers)

    # ------------------------------------------------------------------
    # Credit attempts (PRD §3.2, §3.5)
    # ------------------------------------------------------------------
    def create_credit_attempt(self, payload, headers):
        return self._request("POST", "/credit-attempts", payload, headers)

    def list_credit_attempts(self, headers, params=None):
        return self._request("GET", "/credit-attempts", headers=headers, params=params)

    def get_credit_attempt(self, attempt_id, headers):
        return self._request("GET", f"/credit-attempts/{attempt_id}", headers=headers)

    def assign_owner(self, attempt_id, documentation_owner_id, headers):
        return self._request(
            "POST",
            f"/credit-attempts/{attempt_id}/assign-owner",
            {"documentation_owner_id": documentation_owner_id},
            headers,
        )

    def mark_ready(self, attempt_id, headers):
        return self._request(
            "POST", f"/credit-attempts/{attempt_id}/mark-ready", {}, headers
        )

    def drop_attempt(self, attempt_id, headers):
        return self._request("POST", f"/credit-attempts/{attempt_id}/drop", {}, headers)

    def begin_review(self, attempt_id, headers):
        return self._request(
            "POST", f"/credit-attempts/{attempt_id}/begin-review", {}, headers
        )

    def resubmit_attempt(self, attempt_id, headers):
        return self._request(
            "POST", f"/credit-attempts/{attempt_id}/resubmit", {}, headers
        )

    def award_attempt(self, attempt_id, headers, raw_points_earned=None):
        payload = {} if raw_points_earned is None else {"raw_points_earned": raw_points_earned}
        return self._request(
            "POST", f"/credit-attempts/{attempt_id}/award", payload, headers
        )

    def deny_attempt(self, attempt_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request(
            "POST", f"/credit-attempts/{attempt_id}/deny", payload, headers
        )

    def appeal_attempt(self, attempt_id, appeal_justification, headers):
        return self._request(
            "POST",
            f"/credit-attempts/{attempt_id}/appeal",
            {"appeal_justification": appeal_justification},
            headers,
        )

    def list_attempt_review_comments(self, attempt_id, headers):
        return self._request(
            "GET", f"/credit-attempts/{attempt_id}/review-comments", headers=headers
        )

    # ------------------------------------------------------------------
    # Review comments (PRD §3.5)
    # ------------------------------------------------------------------
    def create_review_comment(self, payload, headers):
        return self._request("POST", "/review-comments", payload, headers)

    def respond_to_comment(self, comment_id, response_text, headers):
        return self._request(
            "POST",
            f"/review-comments/{comment_id}/respond",
            {"response_text": response_text},
            headers,
        )

    def accept_comment(self, comment_id, headers):
        return self._request(
            "POST", f"/review-comments/{comment_id}/accept", {}, headers
        )

    def reopen_comment(self, comment_id, headers):
        return self._request(
            "POST", f"/review-comments/{comment_id}/reopen", {}, headers
        )

    # ------------------------------------------------------------------
    # Commissioning tasks (PRD §3.6)
    # ------------------------------------------------------------------
    def create_commissioning_task(self, payload, headers):
        return self._request("POST", "/commissioning-tasks", payload, headers)

    def list_commissioning_tasks(self, headers, params=None):
        return self._request("GET", "/commissioning-tasks", headers=headers, params=params)

    def get_commissioning_task(self, task_id, headers):
        return self._request("GET", f"/commissioning-tasks/{task_id}", headers=headers)

    def start_commissioning_task(self, task_id, headers):
        return self._request(
            "POST", f"/commissioning-tasks/{task_id}/start", {}, headers
        )

    def complete_commissioning_task(self, task_id, outcome, headers, result_notes=None):
        payload = {"outcome": outcome}
        if result_notes is not None:
            payload["result_notes"] = result_notes
        return self._request(
            "POST", f"/commissioning-tasks/{task_id}/complete", payload, headers
        )

    # ------------------------------------------------------------------
    # Incentive programs and applications (PRD §3.7)
    # ------------------------------------------------------------------
    def create_incentive_program(self, payload, headers):
        return self._request("POST", "/incentive-programs", payload, headers)

    def list_incentive_programs(self, headers, params=None):
        return self._request("GET", "/incentive-programs", headers=headers, params=params)

    def get_incentive_program(self, program_id, headers):
        return self._request("GET", f"/incentive-programs/{program_id}", headers=headers)

    def create_project_incentive(self, payload, headers):
        return self._request("POST", "/project-incentives", payload, headers)

    def list_project_incentives(self, headers, params=None):
        return self._request("GET", "/project-incentives", headers=headers, params=params)

    def get_project_incentive(self, project_incentive_id, headers):
        return self._request(
            "GET", f"/project-incentives/{project_incentive_id}", headers=headers
        )

    def approve_project_incentive(self, project_incentive_id, headers):
        return self._request(
            "POST", f"/project-incentives/{project_incentive_id}/approve", {}, headers
        )

    def disburse_project_incentive(self, project_incentive_id, headers):
        return self._request(
            "POST", f"/project-incentives/{project_incentive_id}/disburse", {}, headers
        )

    # ------------------------------------------------------------------
    # Cost premium analysis (PRD §3.7)
    # ------------------------------------------------------------------
    def create_cost_premium_analysis(self, payload, headers):
        return self._request("POST", "/cost-premium-analyses", payload, headers)

    def get_cost_premium_analysis(self, analysis_id, headers):
        return self._request(
            "GET", f"/cost-premium-analyses/{analysis_id}", headers=headers
        )

    def recalculate_cost_premium_analysis(self, analysis_id, headers):
        return self._request(
            "POST", f"/cost-premium-analyses/{analysis_id}/recalculate", {}, headers
        )

    # ------------------------------------------------------------------
    # Performance reports (PRD §3.8)
    # ------------------------------------------------------------------
    def create_performance_report(self, payload, headers):
        return self._request("POST", "/performance-reports", payload, headers)

    def get_performance_report(self, report_id, headers):
        return self._request("GET", f"/performance-reports/{report_id}", headers=headers)

    def submit_performance_report(self, report_id, headers):
        return self._request(
            "POST", f"/performance-reports/{report_id}/submit", {}, headers
        )

    def verify_performance_report(self, report_id, outcome, headers, rejection_reason=None):
        payload = {"outcome": outcome}
        if rejection_reason is not None:
            payload["rejection_reason"] = rejection_reason
        return self._request(
            "POST", f"/performance-reports/{report_id}/verify", payload, headers
        )

    def revise_performance_report(self, report_id, headers):
        return self._request(
            "POST", f"/performance-reports/{report_id}/revise", {}, headers
        )


api_client = ApiClient()
