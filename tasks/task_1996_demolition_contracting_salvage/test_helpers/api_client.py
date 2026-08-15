"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/demolition/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/demolition/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/demolition/projects/{project_id}", headers=headers)

    def transition_project(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/transition", payload, headers)

    def release_project(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/release", payload, headers)

    def resume_project(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/resume", payload, headers)

    def pin_engineering_survey(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/engineering-pin", payload, headers)

    # --- StructureSurvey / HazmatAbatement ---
    def create_structure_survey(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/structure-surveys", payload, headers)

    def list_structure_surveys(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/structure-surveys", headers=headers, params=params)

    def get_structure_survey(self, survey_id, headers):
        return self._request("GET", f"/demolition/structure-surveys/{survey_id}", headers=headers)

    def transition_structure_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/demolition/structure-surveys/{survey_id}/transition", payload, headers)

    def create_abatement(self, survey_id, payload, headers):
        return self._request("POST", f"/demolition/structure-surveys/{survey_id}/abatements", payload, headers)

    def list_abatements(self, survey_id, headers, params=None):
        return self._request("GET", f"/demolition/structure-surveys/{survey_id}/abatements", headers=headers, params=params)

    def transition_abatement(self, abatement_id, payload, headers):
        return self._request("POST", f"/demolition/abatements/{abatement_id}/transition", payload, headers)

    # --- UtilityDisconnect ---
    def create_utility_disconnect(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/utility-disconnects", payload, headers)

    def list_utility_disconnects(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/utility-disconnects", headers=headers, params=params)

    def transition_utility_disconnect(self, disconnect_id, payload, headers):
        return self._request("POST", f"/demolition/utility-disconnects/{disconnect_id}/transition", payload, headers)

    # --- DemolitionPermit ---
    def create_permit(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/permits", payload, headers)

    def list_permits(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/permits", headers=headers, params=params)

    def transition_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/demolition/permits/{permit_id}/transition", payload, headers)

    def renew_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/demolition/permits/{permit_id}/renewals", payload, headers)

    # --- EngineeringSurvey ---
    def create_engineering_survey(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/engineering-surveys", payload, headers)

    def list_engineering_surveys(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/engineering-surveys", headers=headers, params=params)

    def transition_engineering_survey(self, survey_id, payload, headers):
        return self._request("POST", f"/demolition/engineering-surveys/{survey_id}/transition", payload, headers)

    # --- SalvageManifest / SalvageItem ---
    def create_salvage_manifest(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/salvage-manifests", payload, headers)

    def list_salvage_manifests(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/salvage-manifests", headers=headers, params=params)

    def get_salvage_manifest(self, manifest_id, headers):
        return self._request("GET", f"/demolition/salvage-manifests/{manifest_id}", headers=headers)

    def create_salvage_item(self, manifest_id, payload, headers):
        return self._request("POST", f"/demolition/salvage-manifests/{manifest_id}/items", payload, headers)

    def list_salvage_items(self, manifest_id, headers, params=None):
        return self._request("GET", f"/demolition/salvage-manifests/{manifest_id}/items", headers=headers, params=params)

    def transition_salvage_manifest(self, manifest_id, payload, headers):
        return self._request("POST", f"/demolition/salvage-manifests/{manifest_id}/transition", payload, headers)

    # --- NeighborNotification ---
    def create_neighbor_notification(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/neighbor-notifications", payload, headers)

    def list_neighbor_notifications(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/neighbor-notifications", headers=headers, params=params)

    def transition_neighbor_notification(self, notification_id, payload, headers):
        return self._request("POST", f"/demolition/neighbor-notifications/{notification_id}/transition", payload, headers)

    # --- DustNoiseLog ---
    def create_dust_noise_log(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/dust-noise-logs", payload, headers)

    def list_dust_noise_logs(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/dust-noise-logs", headers=headers, params=params)

    # --- DebrisTicket ---
    def create_debris_ticket(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/debris-tickets", payload, headers)

    def list_debris_tickets(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/debris-tickets", headers=headers, params=params)

    def transition_debris_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"/demolition/debris-tickets/{ticket_id}/transition", payload, headers)

    # --- BackfillPlan ---
    def create_backfill_plan(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/backfill-plans", payload, headers)

    def list_backfill_plans(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/backfill-plans", headers=headers, params=params)

    def transition_backfill_plan(self, plan_id, payload, headers):
        return self._request("POST", f"/demolition/backfill-plans/{plan_id}/transition", payload, headers)

    # --- FinalInspection ---
    def create_final_inspection(self, project_id, payload, headers):
        return self._request("POST", f"/demolition/projects/{project_id}/final-inspections", payload, headers)

    def list_final_inspections(self, project_id, headers, params=None):
        return self._request("GET", f"/demolition/projects/{project_id}/final-inspections", headers=headers, params=params)

    def transition_final_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/demolition/final-inspections/{inspection_id}/transition", payload, headers)


api_client = ApiClient()
