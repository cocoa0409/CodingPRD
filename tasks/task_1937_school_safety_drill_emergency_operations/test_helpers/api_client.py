"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # SchoolSite
    # ------------------------------------------------------------------
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    # ------------------------------------------------------------------
    # DrillTypeRequirement
    # ------------------------------------------------------------------
    def create_drill_requirement(self, payload, headers):
        return self._request("POST", "/drill-requirements", payload, headers)

    def list_drill_requirements(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/drill-requirements",
                             headers=headers, params=params)

    def update_drill_requirement(self, requirement_id, payload, headers):
        return self._request("PUT", f"/drill-requirements/{requirement_id}",
                             payload, headers)

    # ------------------------------------------------------------------
    # EmergencyOperationsPlan
    # ------------------------------------------------------------------
    def create_eop(self, payload, headers):
        return self._request("POST", "/emergency-operations-plans", payload, headers)

    def list_eops(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/emergency-operations-plans",
                             headers=headers, params=params)

    def submit_eop(self, eop_id, headers):
        return self._request("POST", f"/emergency-operations-plans/{eop_id}/submit",
                             {}, headers)

    def decide_eop(self, eop_id, payload, headers):
        return self._request("POST", f"/emergency-operations-plans/{eop_id}/decide",
                             payload, headers)

    def activate_eop(self, eop_id, headers):
        return self._request("POST", f"/emergency-operations-plans/{eop_id}/activate",
                             {}, headers)

    # ------------------------------------------------------------------
    # SitePlanDocument
    # ------------------------------------------------------------------
    def create_site_plan_document(self, payload, headers):
        return self._request("POST", "/site-plan-documents", payload, headers)

    def list_site_plan_documents(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/site-plan-documents",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # FirstResponderWalkthrough
    # ------------------------------------------------------------------
    def create_walkthrough(self, payload, headers):
        return self._request("POST", "/walkthroughs", payload, headers)

    def list_walkthroughs(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/walkthroughs",
                             headers=headers, params=params)

    def complete_walkthrough(self, walkthrough_id, payload, headers):
        return self._request("POST", f"/walkthroughs/{walkthrough_id}/complete",
                             payload, headers)

    # ------------------------------------------------------------------
    # DrillEvent
    # ------------------------------------------------------------------
    def create_drill_event(self, payload, headers):
        return self._request("POST", "/drill-events", payload, headers)

    def list_drill_events(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/drill-events",
                             headers=headers, params=params)

    def get_drill_event(self, drill_id, headers):
        return self._request("GET", f"/drill-events/{drill_id}", headers=headers)

    def start_drill(self, drill_id, headers):
        return self._request("POST", f"/drill-events/{drill_id}/start", {}, headers)

    def complete_drill(self, drill_id, payload, headers):
        return self._request("POST", f"/drill-events/{drill_id}/complete",
                             payload, headers)

    def cancel_drill(self, drill_id, payload, headers):
        return self._request("POST", f"/drill-events/{drill_id}/cancel",
                             payload, headers)

    # ------------------------------------------------------------------
    # RosterEntry
    # ------------------------------------------------------------------
    def add_roster_entry(self, drill_id, payload, headers):
        return self._request("POST", f"/drill-events/{drill_id}/roster-entries",
                             payload, headers)

    def list_roster_entries(self, drill_id, headers, params=None):
        return self._request("GET", f"/drill-events/{drill_id}/roster-entries",
                             headers=headers, params=params)

    def account_roster_entry(self, entry_id, headers):
        return self._request("POST", f"/roster-entries/{entry_id}/account", {}, headers)

    def unaccount_roster_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/roster-entries/{entry_id}/unaccount",
                             payload, headers)

    def release_roster_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/roster-entries/{entry_id}/release",
                             payload, headers)

    # ------------------------------------------------------------------
    # AfterActionReview
    # ------------------------------------------------------------------
    def create_after_action_review(self, drill_id, payload, headers):
        return self._request("POST", f"/drill-events/{drill_id}/after-action-reviews",
                             payload, headers)

    def list_after_action_reviews(self, drill_id, headers, params=None):
        return self._request("GET", f"/drill-events/{drill_id}/after-action-reviews",
                             headers=headers, params=params)

    def get_after_action_review(self, review_id, headers):
        return self._request("GET", f"/after-action-reviews/{review_id}",
                             headers=headers)

    def submit_after_action_review(self, review_id, headers):
        return self._request("POST", f"/after-action-reviews/{review_id}/submit",
                             {}, headers)

    def decide_after_action_review(self, review_id, payload, headers):
        return self._request("POST", f"/after-action-reviews/{review_id}/decide",
                             payload, headers)

    # ------------------------------------------------------------------
    # CorrectiveAction
    # ------------------------------------------------------------------
    def create_corrective_action(self, review_id, payload, headers):
        return self._request("POST",
                             f"/after-action-reviews/{review_id}/corrective-actions",
                             payload, headers)

    def list_corrective_actions(self, review_id, headers, params=None):
        return self._request("GET",
                             f"/after-action-reviews/{review_id}/corrective-actions",
                             headers=headers, params=params)

    def submit_ca_verification(self, action_id, payload, headers):
        return self._request("POST",
                             f"/corrective-actions/{action_id}/submit-verification",
                             payload, headers)

    def verify_corrective_action(self, action_id, payload, headers):
        return self._request("POST", f"/corrective-actions/{action_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # AccommodationPlan
    # ------------------------------------------------------------------
    def create_accommodation_plan(self, payload, headers):
        return self._request("POST", "/accommodation-plans", payload, headers)

    def list_accommodation_plans(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/accommodation-plans",
                             headers=headers, params=params)

    def deactivate_accommodation_plan(self, plan_id, headers):
        return self._request("POST", f"/accommodation-plans/{plan_id}/deactivate",
                             {}, headers)

    # ------------------------------------------------------------------
    # ComplianceReport
    # ------------------------------------------------------------------
    def create_compliance_report(self, payload, headers):
        return self._request("POST", "/compliance-reports", payload, headers)

    def list_compliance_reports(self, site_id, headers, params=None):
        return self._request("GET", f"/sites/{site_id}/compliance-reports",
                             headers=headers, params=params)

    def submit_compliance_report(self, report_id, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/submit",
                             {}, headers)

    def decide_compliance_report(self, report_id, payload, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/decide",
                             payload, headers)

    def regenerate_compliance_report(self, report_id, headers):
        return self._request("POST", f"/compliance-reports/{report_id}/regenerate",
                             {}, headers)


api_client = ApiClient()
