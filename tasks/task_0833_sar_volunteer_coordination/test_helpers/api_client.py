"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/sar/_clock/set_current_utc", payload, headers)

    # --- Incident ---
    def create_incident(self, payload, headers):
        return self._request("POST", "/sar/incidents", payload, headers)

    def get_incident(self, incident_id, headers):
        return self._request("GET", f"/sar/incidents/{incident_id}", headers=headers)

    def list_incidents(self, headers, params=None):
        return self._request("GET", "/sar/incidents", headers=headers, params=params)

    def activate_incident(self, incident_id, headers):
        return self._request("POST", f"/sar/incidents/{incident_id}/activate", {}, headers)

    def demobilize_incident(self, incident_id, headers):
        return self._request("POST", f"/sar/incidents/{incident_id}/demobilize", {}, headers)

    def close_incident(self, incident_id, headers):
        return self._request("POST", f"/sar/incidents/{incident_id}/close", {}, headers)

    def cancel_incident(self, incident_id, headers):
        return self._request("POST", f"/sar/incidents/{incident_id}/cancel", {}, headers)

    # --- Task ---
    def create_task(self, payload, headers):
        return self._request("POST", "/sar/tasks", payload, headers)

    def get_task(self, task_id, headers):
        return self._request("GET", f"/sar/tasks/{task_id}", headers=headers)

    def list_tasks(self, headers, params=None):
        return self._request("GET", "/sar/tasks", headers=headers, params=params)

    def assign_task(self, task_id, headers):
        return self._request("POST", f"/sar/tasks/{task_id}/assign", {}, headers)

    def start_task(self, task_id, headers):
        return self._request("POST", f"/sar/tasks/{task_id}/start", {}, headers)

    def suspend_task(self, task_id, headers):
        return self._request("POST", f"/sar/tasks/{task_id}/suspend", {}, headers)

    def resume_task(self, task_id, headers):
        return self._request("POST", f"/sar/tasks/{task_id}/resume", {}, headers)

    def debrief_task(self, task_id, headers):
        return self._request("POST", f"/sar/tasks/{task_id}/debrief", {}, headers)

    def cancel_task(self, task_id, headers):
        return self._request("POST", f"/sar/tasks/{task_id}/cancel", {}, headers)

    # --- Team ---
    def create_team(self, payload, headers):
        return self._request("POST", "/sar/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/sar/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/sar/teams", headers=headers, params=params)

    def deactivate_team(self, team_id, headers):
        return self._request("POST", f"/sar/teams/{team_id}/deactivate", {}, headers)

    # --- Member ---
    def create_member(self, payload, headers):
        return self._request("POST", "/sar/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/sar/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/sar/members", headers=headers, params=params)

    # --- Certification ---
    def create_certification(self, payload, headers):
        return self._request("POST", "/sar/certifications", payload, headers)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"/sar/certifications/{certification_id}", headers=headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", "/sar/certifications", headers=headers, params=params)

    # --- Callout ---
    def create_callout(self, payload, headers):
        return self._request("POST", "/sar/callouts", payload, headers)

    def get_callout(self, callout_id, headers):
        return self._request("GET", f"/sar/callouts/{callout_id}", headers=headers)

    def list_callouts(self, headers, params=None):
        return self._request("GET", "/sar/callouts", headers=headers, params=params)

    def acknowledge_callout(self, callout_id, headers):
        return self._request("POST", f"/sar/callouts/{callout_id}/acknowledge", {}, headers)

    def decline_callout(self, callout_id, headers):
        return self._request("POST", f"/sar/callouts/{callout_id}/decline", {}, headers)

    def standby_callout(self, callout_id, headers):
        return self._request("POST", f"/sar/callouts/{callout_id}/standby", {}, headers)

    def deploy_callout(self, callout_id, headers):
        return self._request("POST", f"/sar/callouts/{callout_id}/deploy", {}, headers)

    def demobilize_callout(self, callout_id, headers):
        return self._request("POST", f"/sar/callouts/{callout_id}/demobilize", {}, headers)

    # --- Resource ---
    def create_resource(self, payload, headers):
        return self._request("POST", "/sar/resources", payload, headers)

    def get_resource(self, resource_id, headers):
        return self._request("GET", f"/sar/resources/{resource_id}", headers=headers)

    def list_resources(self, headers, params=None):
        return self._request("GET", "/sar/resources", headers=headers, params=params)

    def set_resource_status(self, resource_id, payload, headers):
        return self._request("POST", f"/sar/resources/{resource_id}/set-status", payload, headers)

    # --- ResourceAssignment ---
    def create_resource_assignment(self, payload, headers):
        return self._request("POST", "/sar/resource-assignments", payload, headers)

    def get_resource_assignment(self, assignment_id, headers):
        return self._request("GET", f"/sar/resource-assignments/{assignment_id}", headers=headers)

    def list_resource_assignments(self, headers, params=None):
        return self._request("GET", "/sar/resource-assignments", headers=headers, params=params)

    def activate_resource_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sar/resource-assignments/{assignment_id}/activate", {}, headers)

    def release_resource_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sar/resource-assignments/{assignment_id}/release", {}, headers)

    def cancel_resource_assignment(self, assignment_id, headers):
        return self._request("POST", f"/sar/resource-assignments/{assignment_id}/cancel", {}, headers)

    # --- GroundTrack ---
    def create_ground_track(self, payload, headers):
        return self._request("POST", "/sar/ground-tracks", payload, headers)

    def get_ground_track(self, ground_track_id, headers):
        return self._request("GET", f"/sar/ground-tracks/{ground_track_id}", headers=headers)

    def list_ground_tracks(self, headers, params=None):
        return self._request("GET", "/sar/ground-tracks", headers=headers, params=params)

    # --- Clue ---
    def create_clue(self, payload, headers):
        return self._request("POST", "/sar/clues", payload, headers)

    def get_clue(self, clue_id, headers):
        return self._request("GET", f"/sar/clues/{clue_id}", headers=headers)

    def list_clues(self, headers, params=None):
        return self._request("GET", "/sar/clues", headers=headers, params=params)

    def promote_clue(self, clue_id, headers):
        return self._request("POST", f"/sar/clues/{clue_id}/promote", {}, headers)

    def dismiss_clue(self, clue_id, headers):
        return self._request("POST", f"/sar/clues/{clue_id}/dismiss", {}, headers)

    def resolve_clue(self, clue_id, headers):
        return self._request("POST", f"/sar/clues/{clue_id}/resolve", {}, headers)

    # --- ReimbursementClaim ---
    def create_claim(self, payload, headers):
        return self._request("POST", "/sar/reimbursement-claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/sar/reimbursement-claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/sar/reimbursement-claims", headers=headers, params=params)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"/sar/reimbursement-claims/{claim_id}/submit", {}, headers)

    def return_claim(self, claim_id, headers):
        return self._request("POST", f"/sar/reimbursement-claims/{claim_id}/return", {}, headers)

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/sar/reimbursement-claims/{claim_id}/approve", {}, headers)

    def reject_claim(self, claim_id, headers):
        return self._request("POST", f"/sar/reimbursement-claims/{claim_id}/reject", {}, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/sar/reimbursement-claims/{claim_id}/pay", {}, headers)

    # --- AfterActionReport ---
    def create_aar(self, payload, headers):
        return self._request("POST", "/sar/after-action-reports", payload, headers)

    def get_aar(self, aar_id, headers):
        return self._request("GET", f"/sar/after-action-reports/{aar_id}", headers=headers)

    def list_aars(self, headers, params=None):
        return self._request("GET", "/sar/after-action-reports", headers=headers, params=params)

    def finalize_aar(self, aar_id, headers):
        return self._request("POST", f"/sar/after-action-reports/{aar_id}/finalize", {}, headers)


api_client = ApiClient()
