"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Client accounts
    # ------------------------------------------------------------------
    def create_client(self, payload, headers):
        return self._request("POST", "/sensory-lab/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/sensory-lab/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/sensory-lab/clients/{client_id}", headers=headers)

    def top_up_retainer(self, client_id, hours, headers):
        return self._request("POST", f"/sensory-lab/clients/{client_id}/retainer-topups",
                             {"hours": hours}, headers)

    # ------------------------------------------------------------------
    # Studies
    # ------------------------------------------------------------------
    def create_study(self, payload, headers):
        return self._request("POST", "/sensory-lab/studies", payload, headers)

    def list_studies(self, headers, params=None):
        return self._request("GET", "/sensory-lab/studies", headers=headers, params=params)

    def get_study(self, study_id, headers):
        return self._request("GET", f"/sensory-lab/studies/{study_id}", headers=headers)

    def update_study(self, study_id, payload, headers):
        return self._request("PUT", f"/sensory-lab/studies/{study_id}", payload, headers)

    def submit_design(self, study_id, headers):
        return self._request("POST", f"/sensory-lab/studies/{study_id}/submit-design", {}, headers)

    def approve_design(self, study_id, headers):
        return self._request("POST", f"/sensory-lab/studies/{study_id}/approve-design", {}, headers)

    def reject_design(self, study_id, headers):
        return self._request("POST", f"/sensory-lab/studies/{study_id}/reject-design", {}, headers)

    def activate_study(self, study_id, headers):
        return self._request("POST", f"/sensory-lab/studies/{study_id}/activate", {}, headers)

    def close_fieldwork(self, study_id, headers):
        return self._request("POST", f"/sensory-lab/studies/{study_id}/close-fieldwork", {}, headers)

    def reopen_fieldwork(self, study_id, headers):
        return self._request("POST", f"/sensory-lab/studies/{study_id}/reopen-fieldwork", {}, headers)

    def abort_study(self, study_id, headers):
        return self._request("POST", f"/sensory-lab/studies/{study_id}/abort", {}, headers)

    def get_correlation(self, study_id, headers, params=None):
        return self._request("GET", f"/sensory-lab/studies/{study_id}/correlation",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Study arms
    # ------------------------------------------------------------------
    def create_study_arm(self, payload, headers):
        return self._request("POST", "/sensory-lab/study-arms", payload, headers)

    def list_study_arms(self, headers, params=None):
        return self._request("GET", "/sensory-lab/study-arms", headers=headers, params=params)

    def get_study_arm(self, arm_id, headers):
        return self._request("GET", f"/sensory-lab/study-arms/{arm_id}", headers=headers)

    # ------------------------------------------------------------------
    # Sampling time points
    # ------------------------------------------------------------------
    def create_time_point(self, payload, headers):
        return self._request("POST", "/sensory-lab/sampling-time-points", payload, headers)

    def list_time_points(self, headers, params=None):
        return self._request("GET", "/sensory-lab/sampling-time-points", headers=headers, params=params)

    def get_time_point(self, time_point_id, headers):
        return self._request("GET", f"/sensory-lab/sampling-time-points/{time_point_id}", headers=headers)

    def pull_samples(self, time_point_id, payload, headers):
        return self._request("POST", f"/sensory-lab/sampling-time-points/{time_point_id}/pull",
                             payload, headers)

    def close_time_point(self, time_point_id, headers):
        return self._request("POST", f"/sensory-lab/sampling-time-points/{time_point_id}/close",
                             {}, headers)

    def skip_time_point(self, time_point_id, headers):
        return self._request("POST", f"/sensory-lab/sampling-time-points/{time_point_id}/skip",
                             {}, headers)

    # ------------------------------------------------------------------
    # Storage chambers
    # ------------------------------------------------------------------
    def create_chamber(self, payload, headers):
        return self._request("POST", "/sensory-lab/chambers", payload, headers)

    def list_chambers(self, headers, params=None):
        return self._request("GET", "/sensory-lab/chambers", headers=headers, params=params)

    def get_chamber(self, chamber_id, headers):
        return self._request("GET", f"/sensory-lab/chambers/{chamber_id}", headers=headers)

    # ------------------------------------------------------------------
    # Sample units
    # ------------------------------------------------------------------
    def list_sample_units(self, headers, params=None):
        return self._request("GET", "/sensory-lab/sample-units", headers=headers, params=params)

    def get_sample_unit(self, unit_id, headers):
        return self._request("GET", f"/sensory-lab/sample-units/{unit_id}", headers=headers)

    def checkout_sample_unit(self, unit_id, headers, session_id=None):
        payload = {}
        if session_id is not None:
            payload["session_id"] = session_id
        return self._request("POST", f"/sensory-lab/sample-units/{unit_id}/checkout",
                             payload, headers)

    def return_sample_unit(self, unit_id, headers):
        return self._request("POST", f"/sensory-lab/sample-units/{unit_id}/return", {}, headers)

    def consume_sample_unit(self, unit_id, headers):
        return self._request("POST", f"/sensory-lab/sample-units/{unit_id}/consume", {}, headers)

    def discard_sample_unit(self, unit_id, headers):
        return self._request("POST", f"/sensory-lab/sample-units/{unit_id}/discard", {}, headers)

    def retain_sweep(self, headers):
        return self._request("POST", "/sensory-lab/retain-sweeps", {}, headers)

    # ------------------------------------------------------------------
    # Panelists
    # ------------------------------------------------------------------
    def create_panelist(self, payload, headers):
        return self._request("POST", "/sensory-lab/panelists", payload, headers)

    def list_panelists(self, headers, params=None):
        return self._request("GET", "/sensory-lab/panelists", headers=headers, params=params)

    def get_panelist(self, panelist_id, headers):
        return self._request("GET", f"/sensory-lab/panelists/{panelist_id}", headers=headers)

    def record_screening(self, panelist_id, acuity_score, headers):
        return self._request("POST", f"/sensory-lab/panelists/{panelist_id}/record-screening",
                             {"acuity_score": acuity_score}, headers)

    def record_training(self, panelist_id, headers):
        return self._request("POST", f"/sensory-lab/panelists/{panelist_id}/record-training",
                             {}, headers)

    def deactivate_panelist(self, panelist_id, headers):
        return self._request("POST", f"/sensory-lab/panelists/{panelist_id}/deactivate", {}, headers)

    def reactivate_panelist(self, panelist_id, headers):
        return self._request("POST", f"/sensory-lab/panelists/{panelist_id}/reactivate", {}, headers)

    def assign_remedial(self, panelist_id, headers):
        return self._request("POST", f"/sensory-lab/panelists/{panelist_id}/assign-remedial",
                             {}, headers)

    # ------------------------------------------------------------------
    # Evaluation sessions
    # ------------------------------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/sensory-lab/evaluation-sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sensory-lab/evaluation-sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sensory-lab/evaluation-sessions/{session_id}", headers=headers)

    def open_session(self, session_id, headers):
        return self._request("POST", f"/sensory-lab/evaluation-sessions/{session_id}/open",
                             {}, headers)

    def lock_session(self, session_id, headers):
        return self._request("POST", f"/sensory-lab/evaluation-sessions/{session_id}/lock",
                             {}, headers)

    def analyze_session(self, session_id, headers):
        return self._request("POST", f"/sensory-lab/evaluation-sessions/{session_id}/analyze",
                             {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sensory-lab/evaluation-sessions/{session_id}/cancel",
                             {}, headers)

    def schedule_makeup(self, session_id, payload, headers):
        return self._request("POST", f"/sensory-lab/evaluation-sessions/{session_id}/schedule-makeup",
                             payload, headers)

    # ------------------------------------------------------------------
    # Panel assignments
    # ------------------------------------------------------------------
    def create_assignment(self, payload, headers):
        return self._request("POST", "/sensory-lab/panel-assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/sensory-lab/panel-assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/sensory-lab/panel-assignments/{assignment_id}", headers=headers)

    def mark_no_show(self, assignment_id, headers):
        return self._request("POST", f"/sensory-lab/panel-assignments/{assignment_id}/mark-no-show",
                             {}, headers)

    def excuse_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sensory-lab/panel-assignments/{assignment_id}/excuse",
                             {}, headers)

    # ------------------------------------------------------------------
    # Attribute scores
    # ------------------------------------------------------------------
    def create_score(self, payload, headers):
        return self._request("POST", "/sensory-lab/attribute-scores", payload, headers)

    def list_scores(self, headers, params=None):
        return self._request("GET", "/sensory-lab/attribute-scores", headers=headers, params=params)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/sensory-lab/attribute-scores/{score_id}", headers=headers)

    # ------------------------------------------------------------------
    # Lab test results
    # ------------------------------------------------------------------
    def create_lab_result(self, payload, headers):
        return self._request("POST", "/sensory-lab/lab-test-results", payload, headers)

    def list_lab_results(self, headers, params=None):
        return self._request("GET", "/sensory-lab/lab-test-results", headers=headers, params=params)

    def get_lab_result(self, result_id, headers):
        return self._request("GET", f"/sensory-lab/lab-test-results/{result_id}", headers=headers)

    # ------------------------------------------------------------------
    # Date-code recommendations
    # ------------------------------------------------------------------
    def create_recommendation(self, payload, headers):
        return self._request("POST", "/sensory-lab/date-code-recommendations", payload, headers)

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/sensory-lab/date-code-recommendations",
                             headers=headers, params=params)

    def get_recommendation(self, rec_id, headers):
        return self._request("GET", f"/sensory-lab/date-code-recommendations/{rec_id}",
                             headers=headers)

    def accept_recommendation(self, rec_id, headers):
        return self._request("POST", f"/sensory-lab/date-code-recommendations/{rec_id}/accept",
                             {}, headers)

    def reject_recommendation(self, rec_id, headers):
        return self._request("POST", f"/sensory-lab/date-code-recommendations/{rec_id}/reject",
                             {}, headers)

    # ------------------------------------------------------------------
    # Study reports
    # ------------------------------------------------------------------
    def create_report(self, payload, headers):
        return self._request("POST", "/sensory-lab/study-reports", payload, headers)

    def list_reports(self, headers, params=None):
        return self._request("GET", "/sensory-lab/study-reports", headers=headers, params=params)

    def get_report(self, report_id, headers):
        return self._request("GET", f"/sensory-lab/study-reports/{report_id}", headers=headers)

    def attach_recommendation(self, report_id, recommendation_id, headers):
        return self._request("POST",
                             f"/sensory-lab/study-reports/{report_id}/attach-recommendation",
                             {"recommendation_id": recommendation_id}, headers)

    def submit_report(self, report_id, headers):
        return self._request("POST", f"/sensory-lab/study-reports/{report_id}/submit", {}, headers)

    def qa_approve_report(self, report_id, headers):
        return self._request("POST", f"/sensory-lab/study-reports/{report_id}/qa-approve",
                             {}, headers)

    def qa_return_report(self, report_id, headers):
        return self._request("POST", f"/sensory-lab/study-reports/{report_id}/qa-return",
                             {}, headers)

    def qa_reject_report(self, report_id, headers):
        return self._request("POST", f"/sensory-lab/study-reports/{report_id}/qa-reject",
                             {}, headers)

    def request_changes(self, report_id, headers):
        return self._request("POST", f"/sensory-lab/study-reports/{report_id}/request-changes",
                             {}, headers)

    def release_report(self, report_id, headers):
        return self._request("POST", f"/sensory-lab/study-reports/{report_id}/release", {}, headers)

    # ------------------------------------------------------------------
    # Claim substantiations
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/sensory-lab/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/sensory-lab/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/sensory-lab/claims/{claim_id}", headers=headers)

    def verify_claim(self, claim_id, verdict, headers):
        return self._request("POST", f"/sensory-lab/claims/{claim_id}/verify",
                             {"verdict": verdict}, headers)


api_client = ApiClient()
