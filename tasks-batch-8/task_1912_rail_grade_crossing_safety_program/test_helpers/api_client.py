"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Crossings ---
    def create_crossing(self, payload, headers):
        return self._request("POST", "/crossings", payload, headers)

    def list_crossings(self, headers, params=None):
        return self._request("GET", "/crossings", headers=headers, params=params)

    def get_crossing(self, crossing_id, headers):
        return self._request("GET", f"/crossings/{crossing_id}", headers=headers)

    def patch_crossing_inventory(self, crossing_id, payload, headers):
        return self._request(
            "PATCH", f"/crossings/{crossing_id}/inventory", payload, headers
        )

    def confirm_crossing_closure(self, crossing_id, headers):
        return self._request(
            "POST", f"/crossings/{crossing_id}/confirm-closure", None, headers
        )

    # --- Localities ---
    def create_locality(self, payload, headers):
        return self._request("POST", "/localities", payload, headers)

    def get_locality(self, locality_id, headers):
        return self._request("GET", f"/localities/{locality_id}", headers=headers)

    # --- Diagnostic teams ---
    def create_diagnostic_team(self, payload, headers):
        return self._request("POST", "/diagnostic-teams", payload, headers)

    def get_diagnostic_team(self, team_id, headers):
        return self._request("GET", f"/diagnostic-teams/{team_id}", headers=headers)

    # --- Diagnostic reviews ---
    def create_diagnostic_review(self, payload, headers):
        return self._request("POST", "/diagnostic-reviews", payload, headers)

    def list_diagnostic_reviews(self, headers, params=None):
        return self._request("GET", "/diagnostic-reviews", headers=headers, params=params)

    def get_diagnostic_review(self, review_id, headers):
        return self._request("GET", f"/diagnostic-reviews/{review_id}", headers=headers)

    def transition_diagnostic_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"/diagnostic-reviews/{review_id}/transition", payload, headers
        )

    def issue_recommendations(self, review_id, payload, headers):
        return self._request(
            "POST",
            f"/diagnostic-reviews/{review_id}/issue-recommendations",
            payload,
            headers,
        )

    # --- Incident reports ---
    def create_incident_report(self, payload, headers):
        return self._request("POST", "/incident-reports", payload, headers)

    def list_incident_reports(self, headers, params=None):
        return self._request("GET", "/incident-reports", headers=headers, params=params)

    def get_incident_report(self, incident_id, headers):
        return self._request("GET", f"/incident-reports/{incident_id}", headers=headers)

    def transition_incident_report(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/transition", payload, headers
        )

    def issue_findings(self, incident_id, payload, headers):
        return self._request(
            "POST", f"/incident-reports/{incident_id}/issue-findings", payload, headers
        )

    # --- Funding programs ---
    def create_funding_program(self, payload, headers):
        return self._request("POST", "/funding-programs", payload, headers)

    def get_funding_program(self, program_id, headers):
        return self._request("GET", f"/funding-programs/{program_id}", headers=headers)

    def transition_funding_program(self, program_id, payload, headers):
        return self._request(
            "POST", f"/funding-programs/{program_id}/transition", payload, headers
        )

    # --- Upgrade projects ---
    def create_upgrade_project(self, payload, headers):
        return self._request("POST", "/upgrade-projects", payload, headers)

    def list_upgrade_projects(self, headers, params=None):
        return self._request("GET", "/upgrade-projects", headers=headers, params=params)

    def get_upgrade_project(self, project_id, headers):
        return self._request("GET", f"/upgrade-projects/{project_id}", headers=headers)

    def transition_upgrade_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/upgrade-projects/{project_id}/transition", payload, headers
        )

    def award_upgrade_project(self, project_id, payload, headers):
        return self._request(
            "POST", f"/upgrade-projects/{project_id}/award", payload, headers
        )

    def rescind_award(self, project_id, headers):
        return self._request(
            "POST", f"/upgrade-projects/{project_id}/rescind-award", None, headers
        )

    # --- Closure agreements ---
    def create_closure_agreement(self, payload, headers):
        return self._request("POST", "/closure-agreements", payload, headers)

    def list_closure_agreements(self, headers, params=None):
        return self._request("GET", "/closure-agreements", headers=headers, params=params)

    def get_closure_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/closure-agreements/{agreement_id}", headers=headers
        )

    def transition_closure_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/closure-agreements/{agreement_id}/transition", payload, headers
        )

    def counter_closure_agreement(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"/closure-agreements/{agreement_id}/counter", payload, headers
        )

    # --- Quiet zones ---
    def create_quiet_zone_application(self, payload, headers):
        return self._request("POST", "/quiet-zone-applications", payload, headers)

    def list_quiet_zone_applications(self, headers, params=None):
        return self._request(
            "GET", "/quiet-zone-applications", headers=headers, params=params
        )

    def get_quiet_zone_application(self, qz_id, headers):
        return self._request(
            "GET", f"/quiet-zone-applications/{qz_id}", headers=headers
        )

    def add_quiet_zone_member(self, qz_id, payload, headers):
        return self._request(
            "POST", f"/quiet-zone-applications/{qz_id}/members", payload, headers
        )

    def list_quiet_zone_crossings(self, headers, params=None):
        return self._request(
            "GET", "/quiet-zone-crossings", headers=headers, params=params
        )

    def get_quiet_zone_crossing(self, member_id, headers):
        return self._request(
            "GET", f"/quiet-zone-crossings/{member_id}", headers=headers
        )

    def delete_quiet_zone_crossing(self, member_id, headers):
        return self._request(
            "DELETE", f"/quiet-zone-crossings/{member_id}", headers=headers
        )

    def transition_quiet_zone_application(self, qz_id, payload, headers):
        return self._request(
            "POST", f"/quiet-zone-applications/{qz_id}/transition", payload, headers
        )

    def decide_quiet_zone_application(self, qz_id, headers):
        return self._request(
            "POST", f"/quiet-zone-applications/{qz_id}/decide", None, headers
        )

    # --- Maintenance assignments ---
    def create_maintenance_assignment(self, payload, headers):
        return self._request("POST", "/maintenance-assignments", payload, headers)

    def list_maintenance_assignments(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-assignments", headers=headers, params=params
        )

    def get_maintenance_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/maintenance-assignments/{assignment_id}", headers=headers
        )

    def revoke_maintenance_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/maintenance-assignments/{assignment_id}/revoke", None, headers
        )

    # --- Maintenance work orders ---
    def create_maintenance_work_order(self, payload, headers):
        return self._request("POST", "/maintenance-work-orders", payload, headers)

    def list_maintenance_work_orders(self, headers, params=None):
        return self._request(
            "GET", "/maintenance-work-orders", headers=headers, params=params
        )

    def get_maintenance_work_order(self, work_order_id, headers):
        return self._request(
            "GET", f"/maintenance-work-orders/{work_order_id}", headers=headers
        )

    def transition_maintenance_work_order(self, work_order_id, payload, headers):
        return self._request(
            "POST",
            f"/maintenance-work-orders/{work_order_id}/transition",
            payload,
            headers,
        )

    # --- Preemption interconnections ---
    def create_preemption_interconnection(self, payload, headers):
        return self._request("POST", "/preemption-interconnections", payload, headers)

    def list_preemption_interconnections(self, headers, params=None):
        return self._request(
            "GET", "/preemption-interconnections", headers=headers, params=params
        )

    def get_preemption_interconnection(self, interconnection_id, headers):
        return self._request(
            "GET", f"/preemption-interconnections/{interconnection_id}", headers=headers
        )

    def transition_preemption_interconnection(self, interconnection_id, payload, headers):
        return self._request(
            "POST",
            f"/preemption-interconnections/{interconnection_id}/transition",
            payload,
            headers,
        )

    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
