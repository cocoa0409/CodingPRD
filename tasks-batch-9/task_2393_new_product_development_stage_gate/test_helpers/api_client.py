"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ------------------------------------------------------------ stage gates
    def create_stage_gate(self, payload, headers):
        return self._request("POST", "/stage-gates", payload, headers)

    def list_stage_gates(self, headers, params=None):
        return self._request("GET", "/stage-gates", headers=headers, params=params)

    def get_stage_gate(self, gate_id, headers):
        return self._request("GET", f"/stage-gates/{gate_id}", headers=headers)

    # -------------------------------------------------------------- retailers
    def create_retailer(self, payload, headers):
        return self._request("POST", "/retailers", payload, headers)

    def list_retailers(self, headers, params=None):
        return self._request("GET", "/retailers", headers=headers, params=params)

    def get_retailer(self, retailer_id, headers):
        return self._request("GET", f"/retailers/{retailer_id}", headers=headers)

    # ----------------------------------------------------- shelf reset windows
    def create_shelf_reset_window(self, retailer_id, payload, headers):
        return self._request(
            "POST", f"/retailers/{retailer_id}/shelf-reset-windows", payload, headers
        )

    def list_shelf_reset_windows(self, retailer_id, headers, params=None):
        return self._request(
            "GET", f"/retailers/{retailer_id}/shelf-reset-windows",
            headers=headers, params=params,
        )

    def get_shelf_reset_window(self, window_id, headers):
        return self._request("GET", f"/shelf-reset-windows/{window_id}", headers=headers)

    # ------------------------------------------------------------ pilot lines
    def create_pilot_line(self, payload, headers):
        return self._request("POST", "/pilot-lines", payload, headers)

    def list_pilot_lines(self, headers, params=None):
        return self._request("GET", "/pilot-lines", headers=headers, params=params)

    def get_pilot_line(self, pilot_line_id, headers):
        return self._request("GET", f"/pilot-lines/{pilot_line_id}", headers=headers)

    # ------------------------------------------------------ innovation projects
    def create_project(self, payload, headers):
        return self._request("POST", "/innovation-projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/innovation-projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/innovation-projects/{project_id}", headers=headers)

    def get_launch_readiness(self, project_id, headers):
        return self._request(
            "GET", f"/innovation-projects/{project_id}/launch-readiness", headers=headers
        )

    def screen_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/screen", payload, headers
        )

    # ----------------------------------------------------------- concept tests
    def create_concept_test(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/concept-tests", payload, headers
        )

    def list_concept_tests(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/innovation-projects/{project_id}/concept-tests",
            headers=headers, params=params,
        )

    # ---------------------------------------------------------- business cases
    def create_business_case(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/business-cases", payload, headers
        )

    def list_business_cases(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/innovation-projects/{project_id}/business-cases",
            headers=headers, params=params,
        )

    def get_business_case(self, business_case_id, headers):
        return self._request("GET", f"/business-cases/{business_case_id}", headers=headers)

    def create_forecast_line(self, business_case_id, payload, headers):
        return self._request(
            "POST", f"/business-cases/{business_case_id}/forecast-lines", payload, headers
        )

    def list_forecast_lines(self, business_case_id, headers, params=None):
        return self._request(
            "GET", f"/business-cases/{business_case_id}/forecast-lines",
            headers=headers, params=params,
        )

    # ----------------------------------------------------------- deliverables
    def create_deliverable(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/deliverables", payload, headers
        )

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/deliverables", headers=headers, params=params)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    def submit_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/submit", payload, headers
        )

    def decide_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/decide", payload, headers
        )

    def waive_deliverable(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/waive", payload, headers
        )

    def set_deliverable_prerequisite(self, deliverable_id, payload, headers):
        return self._request(
            "POST", f"/deliverables/{deliverable_id}/set-prerequisite", payload, headers
        )

    # ----------------------------------------------------------- gate reviews
    def create_gate_review(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/gate-reviews", payload, headers
        )

    def list_gate_reviews(self, headers, params=None):
        return self._request("GET", "/gate-reviews", headers=headers, params=params)

    def get_gate_review(self, gate_review_id, headers):
        return self._request("GET", f"/gate-reviews/{gate_review_id}", headers=headers)

    def open_gate_review(self, gate_review_id, payload, headers):
        return self._request(
            "POST", f"/gate-reviews/{gate_review_id}/open", payload, headers
        )

    def cast_gate_vote(self, gate_review_id, payload, headers):
        return self._request(
            "POST", f"/gate-reviews/{gate_review_id}/votes", payload, headers
        )

    def list_gate_votes(self, gate_review_id, headers, params=None):
        return self._request(
            "GET", f"/gate-reviews/{gate_review_id}/votes", headers=headers, params=params
        )

    def close_gate_review(self, gate_review_id, payload, headers):
        return self._request(
            "POST", f"/gate-reviews/{gate_review_id}/close", payload, headers
        )

    def clear_gate_conditions(self, gate_review_id, payload, headers):
        return self._request(
            "POST", f"/gate-reviews/{gate_review_id}/clear-conditions", payload, headers
        )

    def expire_gate_conditions(self, gate_review_id, payload, headers):
        return self._request(
            "POST", f"/gate-reviews/{gate_review_id}/expire-conditions", payload, headers
        )

    # ----------------------------------------------------------- formulations
    def create_formulation(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/formulations", payload, headers
        )

    def list_formulations(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/innovation-projects/{project_id}/formulations",
            headers=headers, params=params,
        )

    def get_formulation(self, formulation_id, headers):
        return self._request("GET", f"/formulations/{formulation_id}", headers=headers)

    # ------------------------------------------------------------- pilot runs
    def create_pilot_run(self, formulation_id, payload, headers):
        return self._request(
            "POST", f"/formulations/{formulation_id}/pilot-runs", payload, headers
        )

    def list_pilot_runs(self, headers, params=None):
        return self._request("GET", "/pilot-runs", headers=headers, params=params)

    def get_pilot_run(self, pilot_run_id, headers):
        return self._request("GET", f"/pilot-runs/{pilot_run_id}", headers=headers)

    def start_pilot_run(self, pilot_run_id, payload, headers):
        return self._request("POST", f"/pilot-runs/{pilot_run_id}/start", payload, headers)

    def complete_pilot_run(self, pilot_run_id, payload, headers):
        return self._request(
            "POST", f"/pilot-runs/{pilot_run_id}/complete", payload, headers
        )

    def cancel_pilot_run(self, pilot_run_id, payload, headers):
        return self._request("POST", f"/pilot-runs/{pilot_run_id}/cancel", payload, headers)

    # ------------------------------------------------------ shelf life studies
    def create_shelf_life_study(self, formulation_id, payload, headers):
        return self._request(
            "POST", f"/formulations/{formulation_id}/shelf-life-studies", payload, headers
        )

    def list_shelf_life_studies(self, formulation_id, headers, params=None):
        return self._request(
            "GET", f"/formulations/{formulation_id}/shelf-life-studies",
            headers=headers, params=params,
        )

    def get_shelf_life_study(self, study_id, headers):
        return self._request("GET", f"/shelf-life-studies/{study_id}", headers=headers)

    def add_timepoint(self, study_id, payload, headers):
        return self._request(
            "POST", f"/shelf-life-studies/{study_id}/timepoints", payload, headers
        )

    # -------------------------------------------------------- label approvals
    def create_label_approval(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/label-approvals", payload, headers
        )

    def list_label_approvals(self, headers, params=None):
        return self._request("GET", "/label-approvals", headers=headers, params=params)

    def get_label_approval(self, label_approval_id, headers):
        return self._request(
            "GET", f"/label-approvals/{label_approval_id}", headers=headers
        )

    def submit_label_approval(self, label_approval_id, payload, headers):
        return self._request(
            "POST", f"/label-approvals/{label_approval_id}/submit", payload, headers
        )

    def decide_label_approval(self, label_approval_id, payload, headers):
        return self._request(
            "POST", f"/label-approvals/{label_approval_id}/decide", payload, headers
        )

    # -------------------------------------------------- sell-in presentations
    def create_sell_in_presentation(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/sell-in-presentations",
            payload, headers,
        )

    def list_sell_in_presentations(self, headers, params=None):
        return self._request(
            "GET", "/sell-in-presentations", headers=headers, params=params
        )

    def get_sell_in_presentation(self, presentation_id, headers):
        return self._request(
            "GET", f"/sell-in-presentations/{presentation_id}", headers=headers
        )

    def present_sell_in_presentation(self, presentation_id, payload, headers):
        return self._request(
            "POST", f"/sell-in-presentations/{presentation_id}/present", payload, headers
        )

    def record_sell_in_outcome(self, presentation_id, payload, headers):
        return self._request(
            "POST", f"/sell-in-presentations/{presentation_id}/record-outcome",
            payload, headers,
        )

    def withdraw_sell_in_presentation(self, presentation_id, payload, headers):
        return self._request(
            "POST", f"/sell-in-presentations/{presentation_id}/withdraw", payload, headers
        )

    # ------------------------------------------------------- launch lifecycle
    def lock_launch_date(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/launch-lock", payload, headers
        )

    def launch_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/launch", payload, headers
        )

    def create_post_launch_period(self, project_id, payload, headers):
        return self._request(
            "POST", f"/innovation-projects/{project_id}/post-launch-periods",
            payload, headers,
        )

    def list_post_launch_periods(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/innovation-projects/{project_id}/post-launch-periods",
            headers=headers, params=params,
        )


api_client = ApiClient()
