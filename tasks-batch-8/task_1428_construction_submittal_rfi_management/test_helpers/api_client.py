"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving capability, PRD §2.11) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Projects ---
    def create_project(self, payload, headers):
        return self._request("POST", "/v1/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/v1/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/v1/projects/{project_id}", headers=headers)

    def patch_project(self, project_id, payload, headers):
        return self._request("PATCH", f"/v1/projects/{project_id}", payload, headers)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/activate", {}, headers)

    def suspend_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/suspend", {}, headers)

    def resume_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/resume", {}, headers)

    def begin_closeout_project(self, project_id, headers):
        return self._request(
            "POST", f"/v1/projects/{project_id}/begin-closeout", {}, headers
        )

    def close_project(self, project_id, headers):
        return self._request("POST", f"/v1/projects/{project_id}/close", {}, headers)

    def run_daily_scan(self, project_id, headers):
        return self._request(
            "POST", f"/v1/projects/{project_id}/run-daily-scan", {}, headers
        )

    # --- Spec sections ---
    def create_spec_section(self, project_id, payload, headers):
        return self._request(
            "POST", f"/v1/projects/{project_id}/spec-sections", payload, headers
        )

    def list_project_spec_sections(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/spec-sections", headers=headers, params=params
        )

    def list_spec_sections(self, headers, params=None):
        return self._request("GET", "/v1/spec-sections", headers=headers, params=params)

    def get_spec_section(self, section_id, headers):
        return self._request("GET", f"/v1/spec-sections/{section_id}", headers=headers)

    def patch_spec_section(self, section_id, payload, headers):
        return self._request(
            "PATCH", f"/v1/spec-sections/{section_id}", payload, headers
        )

    def activate_spec_section(self, section_id, headers):
        return self._request(
            "POST", f"/v1/spec-sections/{section_id}/activate", {}, headers
        )

    def lock_spec_section(self, section_id, headers):
        return self._request("POST", f"/v1/spec-sections/{section_id}/lock", {}, headers)

    # --- Subcontractors ---
    def create_subcontractor(self, project_id, payload, headers):
        return self._request(
            "POST", f"/v1/projects/{project_id}/subcontractors", payload, headers
        )

    def list_project_subcontractors(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/subcontractors", headers=headers, params=params
        )

    def list_subcontractors(self, headers, params=None):
        return self._request("GET", "/v1/subcontractors", headers=headers, params=params)

    def get_subcontractor(self, subcontractor_id, headers):
        return self._request(
            "GET", f"/v1/subcontractors/{subcontractor_id}", headers=headers
        )

    # --- Reviewers ---
    def create_reviewer(self, project_id, payload, headers):
        return self._request("POST", f"/v1/projects/{project_id}/reviewers", payload, headers)

    def list_project_reviewers(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/reviewers", headers=headers, params=params
        )

    def list_reviewers(self, headers, params=None):
        return self._request("GET", "/v1/reviewers", headers=headers, params=params)

    def get_reviewer(self, reviewer_id, headers):
        return self._request("GET", f"/v1/reviewers/{reviewer_id}", headers=headers)

    def patch_reviewer(self, reviewer_id, payload, headers):
        return self._request("PATCH", f"/v1/reviewers/{reviewer_id}", payload, headers)

    # --- Submittals ---
    def list_project_submittals(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/submittals", headers=headers, params=params
        )

    def list_submittals(self, headers, params=None):
        return self._request("GET", "/v1/submittals", headers=headers, params=params)

    def get_submittal(self, submittal_id, headers):
        return self._request("GET", f"/v1/submittals/{submittal_id}", headers=headers)

    def patch_submittal(self, submittal_id, payload, headers):
        return self._request("PATCH", f"/v1/submittals/{submittal_id}", payload, headers)

    def request_deferral(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/v1/submittals/{submittal_id}/request-deferral", payload, headers
        )

    def decide_deferral(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/v1/submittals/{submittal_id}/decide-deferral", payload, headers
        )

    def release_submittal_for_construction(self, submittal_id, headers):
        return self._request(
            "POST",
            f"/v1/submittals/{submittal_id}/release-for-construction",
            {},
            headers,
        )

    def void_submittal(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/v1/submittals/{submittal_id}/void", payload, headers
        )

    def close_submittal(self, submittal_id, headers):
        return self._request("POST", f"/v1/submittals/{submittal_id}/close", {}, headers)

    # --- Submittal revisions ---
    def create_revision(self, submittal_id, payload, headers):
        return self._request(
            "POST", f"/v1/submittals/{submittal_id}/revisions", payload, headers
        )

    def list_submittal_revisions(self, submittal_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/submittals/{submittal_id}/revisions",
            headers=headers,
            params=params,
        )

    def list_revisions(self, headers, params=None):
        return self._request("GET", "/v1/revisions", headers=headers, params=params)

    def get_revision(self, revision_id, headers):
        return self._request("GET", f"/v1/revisions/{revision_id}", headers=headers)

    def route_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"/v1/revisions/{revision_id}/route", payload, headers
        )

    def return_revision(self, revision_id, payload, headers):
        return self._request(
            "POST", f"/v1/revisions/{revision_id}/return", payload, headers
        )

    # --- Long-lead items ---
    def list_project_long_lead_items(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/long-lead-items", headers=headers, params=params
        )

    def list_long_lead_items(self, headers, params=None):
        return self._request("GET", "/v1/long-lead-items", headers=headers, params=params)

    def get_long_lead_item(self, item_id, headers):
        return self._request("GET", f"/v1/long-lead-items/{item_id}", headers=headers)

    def get_submittal_long_lead_item(self, submittal_id, headers):
        return self._request(
            "GET", f"/v1/submittals/{submittal_id}/long-lead-item", headers=headers
        )

    def patch_long_lead_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/v1/long-lead-items/{item_id}", payload, headers)

    def advance_long_lead_item(self, item_id, payload, headers):
        return self._request(
            "POST", f"/v1/long-lead-items/{item_id}/advance", payload, headers
        )

    def expedite_long_lead_item(self, item_id, headers):
        return self._request(
            "POST", f"/v1/long-lead-items/{item_id}/expedite", {}, headers
        )

    # --- RFIs ---
    def create_rfi(self, project_id, payload, headers):
        return self._request("POST", f"/v1/projects/{project_id}/rfis", payload, headers)

    def list_project_rfis(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/rfis", headers=headers, params=params
        )

    def list_rfis(self, headers, params=None):
        return self._request("GET", "/v1/rfis", headers=headers, params=params)

    def get_rfi(self, rfi_id, headers):
        return self._request("GET", f"/v1/rfis/{rfi_id}", headers=headers)

    def route_rfi(self, rfi_id, payload, headers):
        return self._request("POST", f"/v1/rfis/{rfi_id}/route", payload, headers)

    def answer_rfi(self, rfi_id, payload, headers):
        return self._request("POST", f"/v1/rfis/{rfi_id}/answer", payload, headers)

    def reopen_rfi(self, rfi_id, headers):
        return self._request("POST", f"/v1/rfis/{rfi_id}/reopen", {}, headers)

    def distribute_rfi(self, rfi_id, headers):
        return self._request("POST", f"/v1/rfis/{rfi_id}/distribute", {}, headers)

    def close_rfi(self, rfi_id, headers):
        return self._request("POST", f"/v1/rfis/{rfi_id}/close", {}, headers)

    def void_rfi(self, rfi_id, payload, headers):
        return self._request("POST", f"/v1/rfis/{rfi_id}/void", payload, headers)

    # --- Impact assessments ---
    def list_project_impact_assessments(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/projects/{project_id}/impact-assessments",
            headers=headers,
            params=params,
        )

    def list_impact_assessments(self, headers, params=None):
        return self._request("GET", "/v1/impact-assessments", headers=headers, params=params)

    def get_impact_assessment(self, assessment_id, headers):
        return self._request(
            "GET", f"/v1/impact-assessments/{assessment_id}", headers=headers
        )

    def price_impact_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/v1/impact-assessments/{assessment_id}/price", payload, headers
        )

    def reprice_impact_assessment(self, assessment_id, payload, headers):
        return self._request(
            "POST", f"/v1/impact-assessments/{assessment_id}/reprice", payload, headers
        )

    def accept_impact_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/v1/impact-assessments/{assessment_id}/accept", {}, headers
        )

    def waive_impact_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/v1/impact-assessments/{assessment_id}/waive", {}, headers
        )

    def dispute_impact_assessment(self, assessment_id, headers):
        return self._request(
            "POST", f"/v1/impact-assessments/{assessment_id}/dispute", {}, headers
        )

    # --- Distribution records ---
    def list_project_distribution_records(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/projects/{project_id}/distribution-records",
            headers=headers,
            params=params,
        )

    def list_distribution_records(self, headers, params=None):
        return self._request("GET", "/v1/distribution-records", headers=headers, params=params)

    def get_distribution_record(self, record_id, headers):
        return self._request(
            "GET", f"/v1/distribution-records/{record_id}", headers=headers
        )

    def send_distribution_record(self, record_id, headers):
        return self._request(
            "POST", f"/v1/distribution-records/{record_id}/send", {}, headers
        )

    def acknowledge_distribution_record(self, record_id, headers):
        return self._request(
            "POST", f"/v1/distribution-records/{record_id}/acknowledge", {}, headers
        )

    # --- Installation activities ---
    def create_installation_activity(self, project_id, payload, headers):
        return self._request(
            "POST", f"/v1/projects/{project_id}/installation-activities", payload, headers
        )

    def list_project_installation_activities(self, project_id, headers, params=None):
        return self._request(
            "GET",
            f"/v1/projects/{project_id}/installation-activities",
            headers=headers,
            params=params,
        )

    def list_installation_activities(self, headers, params=None):
        return self._request(
            "GET", "/v1/installation-activities", headers=headers, params=params
        )

    def get_installation_activity(self, activity_id, headers):
        return self._request(
            "GET", f"/v1/installation-activities/{activity_id}", headers=headers
        )

    def release_installation_activity(self, activity_id, headers):
        return self._request(
            "POST", f"/v1/installation-activities/{activity_id}/release", {}, headers
        )

    def complete_installation_activity(self, activity_id, headers):
        return self._request(
            "POST", f"/v1/installation-activities/{activity_id}/complete", {}, headers
        )

    def cancel_installation_activity(self, activity_id, headers):
        return self._request(
            "POST", f"/v1/installation-activities/{activity_id}/cancel", {}, headers
        )

    # --- Owner reports ---
    def create_owner_report(self, project_id, payload, headers):
        return self._request(
            "POST", f"/v1/projects/{project_id}/owner-reports", payload, headers
        )

    def list_project_owner_reports(self, project_id, headers, params=None):
        return self._request(
            "GET", f"/v1/projects/{project_id}/owner-reports", headers=headers, params=params
        )

    def list_owner_reports(self, headers, params=None):
        return self._request("GET", "/v1/owner-reports", headers=headers, params=params)

    def get_owner_report(self, report_id, headers):
        return self._request("GET", f"/v1/owner-reports/{report_id}", headers=headers)

    def publish_owner_report(self, report_id, headers):
        return self._request(
            "POST", f"/v1/owner-reports/{report_id}/publish", {}, headers
        )

    def get_owner_report_metrics(self, report_id, headers, params=None):
        return self._request(
            "GET", f"/v1/owner-reports/{report_id}/metrics", headers=headers, params=params
        )

    # --- Escalation events (append-only log) ---
    def list_escalation_events(self, headers, params=None):
        return self._request("GET", "/v1/escalation-events", headers=headers, params=params)

    def get_escalation_event(self, event_id, headers):
        return self._request("GET", f"/v1/escalation-events/{event_id}", headers=headers)


api_client = ApiClient()
