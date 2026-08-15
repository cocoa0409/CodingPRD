"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/emergency/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ------------------------------------------------------------------
    # Staff roster (PRD §3.5)
    # ------------------------------------------------------------------
    def create_staff_member(self, payload, headers):
        return self._request("POST", "/emergency/staff-members", payload, headers)

    def list_staff_members(self, headers, params=None):
        return self._request("GET", "/emergency/staff-members", headers=headers, params=params)

    def get_staff_member(self, staff_id, headers):
        return self._request("GET", f"/emergency/staff-members/{staff_id}", headers=headers)

    def patch_staff_member(self, staff_id, payload, headers):
        return self._request("PATCH", f"/emergency/staff-members/{staff_id}", payload, headers)

    # ------------------------------------------------------------------
    # Hazard vulnerability analysis (PRD §3.1)
    # ------------------------------------------------------------------
    def create_hazard_assessment(self, payload, headers):
        return self._request("POST", "/emergency/hazard-assessments", payload, headers)

    def get_hazard_assessment(self, hva_id, headers):
        return self._request("GET", f"/emergency/hazard-assessments/{hva_id}", headers=headers)

    def patch_hazard_assessment(self, hva_id, payload, headers):
        return self._request("PATCH", f"/emergency/hazard-assessments/{hva_id}", payload, headers)

    def finalize_hazard_assessment(self, hva_id, headers):
        return self._request(
            "POST", f"/emergency/hazard-assessments/{hva_id}/finalize", {}, headers
        )

    # ------------------------------------------------------------------
    # Plan update cycle (PRD §3.2)
    # ------------------------------------------------------------------
    def create_plan_revision(self, payload, headers):
        return self._request("POST", "/emergency/plan-revisions", payload, headers)

    def list_plan_revisions(self, headers, params=None):
        return self._request("GET", "/emergency/plan-revisions", headers=headers, params=params)

    def get_plan_revision(self, plan_id, headers):
        return self._request("GET", f"/emergency/plan-revisions/{plan_id}", headers=headers)

    def submit_plan_review(self, plan_id, headers):
        return self._request(
            "POST", f"/emergency/plan-revisions/{plan_id}/submit-review", {}, headers
        )

    def approve_plan_revision(self, plan_id, headers):
        return self._request(
            "POST", f"/emergency/plan-revisions/{plan_id}/approve", {}, headers
        )

    def reject_plan_revision(self, plan_id, headers):
        return self._request(
            "POST", f"/emergency/plan-revisions/{plan_id}/reject", {}, headers
        )

    # ------------------------------------------------------------------
    # Exercises / drills (PRD §3.3)
    # ------------------------------------------------------------------
    def create_exercise(self, payload, headers):
        return self._request("POST", "/emergency/exercises", payload, headers)

    def list_exercises(self, headers, params=None):
        return self._request("GET", "/emergency/exercises", headers=headers, params=params)

    def get_exercise(self, exercise_id, headers):
        return self._request("GET", f"/emergency/exercises/{exercise_id}", headers=headers)

    def start_exercise(self, exercise_id, headers):
        return self._request("POST", f"/emergency/exercises/{exercise_id}/start", {}, headers)

    def complete_exercise(self, exercise_id, headers):
        return self._request(
            "POST", f"/emergency/exercises/{exercise_id}/complete", {}, headers
        )

    def cancel_exercise(self, exercise_id, headers):
        return self._request("POST", f"/emergency/exercises/{exercise_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # After-action reports & improvement tasks (PRD §3.3)
    # ------------------------------------------------------------------
    def create_after_action_report(self, payload, headers):
        return self._request("POST", "/emergency/after-action-reports", payload, headers)

    def get_after_action_report(self, aar_id, headers):
        return self._request("GET", f"/emergency/after-action-reports/{aar_id}", headers=headers)

    def submit_after_action_report(self, aar_id, headers):
        return self._request(
            "POST", f"/emergency/after-action-reports/{aar_id}/submit", {}, headers
        )

    def approve_after_action_report(self, aar_id, headers):
        return self._request(
            "POST", f"/emergency/after-action-reports/{aar_id}/approve", {}, headers
        )

    def create_improvement_task(self, payload, headers):
        return self._request("POST", "/emergency/improvement-tasks", payload, headers)

    def list_improvement_tasks(self, headers, params=None):
        return self._request("GET", "/emergency/improvement-tasks", headers=headers, params=params)

    def get_improvement_task(self, task_id, headers):
        return self._request("GET", f"/emergency/improvement-tasks/{task_id}", headers=headers)

    def patch_improvement_task(self, task_id, payload, headers):
        return self._request("PATCH", f"/emergency/improvement-tasks/{task_id}", payload, headers)

    # ------------------------------------------------------------------
    # Incidents & surge assessment (PRD §3.4)
    # ------------------------------------------------------------------
    def create_incident(self, payload, headers):
        return self._request("POST", "/emergency/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/emergency/incidents/{incident_id}", headers=headers)

    def assess_surge(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/emergency/incidents/{incident_id}/assess-surge", payload, headers
        )

    def demobilize_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/emergency/incidents/{incident_id}/demobilize", {}, headers
        )

    def reactivate_incident(self, incident_id, headers):
        return self._request(
            "POST", f"/emergency/incidents/{incident_id}/reactivate", {}, headers
        )

    # ------------------------------------------------------------------
    # Command role assignments (PRD §3.5, OCC-guarded per §2.8)
    # ------------------------------------------------------------------
    def create_command_assignment(self, payload, headers):
        return self._request("POST", "/emergency/command-assignments", payload, headers)

    def list_command_assignments(self, headers, params=None):
        return self._request(
            "GET", "/emergency/command-assignments", headers=headers, params=params
        )

    def get_command_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/emergency/command-assignments/{assignment_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Staffing call-back (PRD §3.5)
    # ------------------------------------------------------------------
    def create_callback_request(self, payload, headers):
        return self._request("POST", "/emergency/callback-requests", payload, headers)

    def list_callback_requests(self, headers, params=None):
        return self._request("GET", "/emergency/callback-requests", headers=headers, params=params)

    def get_callback_request(self, request_id, headers):
        return self._request("GET", f"/emergency/callback-requests/{request_id}", headers=headers)

    def respond_callback_request(self, request_id, payload, headers):
        return self._request(
            "POST", f"/emergency/callback-requests/{request_id}/respond", payload, headers
        )

    def cancel_callback_request(self, request_id, headers, payload=None):
        return self._request(
            "POST", f"/emergency/callback-requests/{request_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------------------
    # Supply / PPE cache (PRD §3.6)
    # ------------------------------------------------------------------
    def create_supply_item(self, payload, headers):
        return self._request("POST", "/emergency/supply-items", payload, headers)

    def list_supply_items(self, headers, params=None):
        return self._request("GET", "/emergency/supply-items", headers=headers, params=params)

    def get_supply_item(self, item_id, headers):
        return self._request("GET", f"/emergency/supply-items/{item_id}", headers=headers)

    def create_stock_transaction(self, payload, headers):
        return self._request("POST", "/emergency/stock-transactions", payload, headers)

    def list_stock_transactions(self, headers, params=None):
        return self._request("GET", "/emergency/stock-transactions", headers=headers, params=params)

    def get_stock_transaction(self, tx_id, headers):
        return self._request("GET", f"/emergency/stock-transactions/{tx_id}", headers=headers)

    # ------------------------------------------------------------------
    # Alternate care sites (PRD §3.7)
    # ------------------------------------------------------------------
    def create_alternate_care_site(self, payload, headers):
        return self._request("POST", "/emergency/alternate-care-sites", payload, headers)

    def list_alternate_care_sites(self, headers, params=None):
        return self._request(
            "GET", "/emergency/alternate-care-sites", headers=headers, params=params
        )

    def get_alternate_care_site(self, site_id, headers):
        return self._request("GET", f"/emergency/alternate-care-sites/{site_id}", headers=headers)

    def commit_site_window(self, site_id, payload, headers):
        return self._request(
            "POST", f"/emergency/alternate-care-sites/{site_id}/commit", payload, headers
        )

    def activate_site(self, site_id, headers):
        return self._request(
            "POST", f"/emergency/alternate-care-sites/{site_id}/activate", {}, headers
        )

    def demobilize_site(self, site_id, headers):
        return self._request(
            "POST", f"/emergency/alternate-care-sites/{site_id}/demobilize", {}, headers
        )

    # ------------------------------------------------------------------
    # Patient tracking (PRD §3.7)
    # ------------------------------------------------------------------
    def create_patient_record(self, payload, headers):
        return self._request("POST", "/emergency/patient-records", payload, headers)

    def list_patient_records(self, headers, params=None):
        return self._request("GET", "/emergency/patient-records", headers=headers, params=params)

    def get_patient_record(self, patient_id, headers):
        return self._request("GET", f"/emergency/patient-records/{patient_id}", headers=headers)

    def transfer_patient(self, patient_id, payload, headers):
        return self._request(
            "POST", f"/emergency/patient-records/{patient_id}/transfer", payload, headers
        )

    def discharge_patient(self, patient_id, headers):
        return self._request(
            "POST", f"/emergency/patient-records/{patient_id}/discharge", {}, headers
        )

    # ------------------------------------------------------------------
    # Family reunification (PRD §3.8)
    # ------------------------------------------------------------------
    def create_family_inquiry(self, payload, headers):
        return self._request("POST", "/emergency/family-inquiries", payload, headers)

    def list_family_inquiries(self, headers, params=None):
        return self._request("GET", "/emergency/family-inquiries", headers=headers, params=params)

    def get_family_inquiry(self, inquiry_id, headers):
        return self._request("GET", f"/emergency/family-inquiries/{inquiry_id}", headers=headers)

    def match_family_inquiry(self, inquiry_id, payload, headers):
        return self._request(
            "POST", f"/emergency/family-inquiries/{inquiry_id}/match", payload, headers
        )

    def reunite_family_inquiry(self, inquiry_id, headers):
        return self._request(
            "POST", f"/emergency/family-inquiries/{inquiry_id}/reunite", {}, headers
        )

    def close_inquiry_no_match(self, inquiry_id, headers):
        return self._request(
            "POST", f"/emergency/family-inquiries/{inquiry_id}/close-no-match", {}, headers
        )

    # ------------------------------------------------------------------
    # Coalition & regulatory reporting (PRD §3.9)
    # ------------------------------------------------------------------
    def create_external_report(self, payload, headers):
        return self._request("POST", "/emergency/external-reports", payload, headers)

    def list_external_reports(self, headers, params=None):
        return self._request("GET", "/emergency/external-reports", headers=headers, params=params)

    def get_external_report(self, report_id, headers):
        return self._request("GET", f"/emergency/external-reports/{report_id}", headers=headers)

    def submit_external_report(self, report_id, headers):
        return self._request(
            "POST", f"/emergency/external-reports/{report_id}/submit", {}, headers
        )


api_client = ApiClient()
