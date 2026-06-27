"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ---- Projects ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def start_provisioning(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/start-provisioning", headers=headers)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/activate", headers=headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", headers=headers)

    # ---- Rack ----
    def create_rack(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/rack", payload, headers)

    def get_rack(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/rack", headers=headers)

    # ---- Proposals ----
    def create_proposal(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/proposals", payload, headers)

    def list_proposals(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/proposals", headers=headers, params=params)

    def get_proposal_nested(self, project_id, proposal_id, headers):
        return self._request("GET", f"/projects/{project_id}/proposals/{proposal_id}", headers=headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def list_line_items_flat(self, proposal_id, headers, params=None):
        return self._request("GET", f"/proposals/{proposal_id}/line-items", headers=headers, params=params)

    def add_line_item(self, project_id, proposal_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/proposals/{proposal_id}/line-items", payload, headers)

    def list_line_items(self, project_id, proposal_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/proposals/{proposal_id}/line-items", headers=headers, params=params)

    def remove_line_item(self, project_id, proposal_id, line_item_id, headers):
        return self._request("POST", f"/projects/{project_id}/proposals/{proposal_id}/line-items/{line_item_id}/remove", headers=headers)

    def send_proposal(self, project_id, proposal_id, headers):
        return self._request("POST", f"/projects/{project_id}/proposals/{proposal_id}/send", headers=headers)

    def accept_proposal(self, project_id, proposal_id, headers):
        return self._request("POST", f"/projects/{project_id}/proposals/{proposal_id}/accept", headers=headers)

    def reject_proposal(self, project_id, proposal_id, headers):
        return self._request("POST", f"/projects/{project_id}/proposals/{proposal_id}/reject", headers=headers)

    # ---- Devices ----
    def create_device(self, payload, headers):
        return self._request("POST", "/devices", payload, headers)

    def get_device(self, device_id, headers):
        return self._request("GET", f"/devices/{device_id}", headers=headers)

    def list_devices(self, headers, params=None):
        return self._request("GET", "/devices", headers=headers, params=params)

    def provision_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/provision", headers=headers)

    def bring_online(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/bring-online", headers=headers)

    def mark_faulted(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/mark-faulted", headers=headers)

    def retire_device(self, device_id, headers):
        return self._request("POST", f"/devices/{device_id}/retire", headers=headers)

    # ---- Firmware ----
    def stage_firmware_update(self, device_id, payload, headers):
        return self._request("POST", f"/devices/{device_id}/firmware-updates", payload, headers)

    def list_firmware_updates(self, device_id, headers, params=None):
        return self._request("GET", f"/devices/{device_id}/firmware-updates", headers=headers, params=params)

    def apply_firmware_update(self, device_id, update_id, headers):
        return self._request("POST", f"/devices/{device_id}/firmware-updates/{update_id}/apply", headers=headers)

    def fail_firmware_update(self, device_id, update_id, headers):
        return self._request("POST", f"/devices/{device_id}/firmware-updates/{update_id}/fail", headers=headers)

    def rollback_firmware_update(self, device_id, update_id, headers):
        return self._request("POST", f"/devices/{device_id}/firmware-updates/{update_id}/rollback", headers=headers)

    # ---- Scenes ----
    def create_scene(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/scenes", payload, headers)

    def list_scenes(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/scenes", headers=headers, params=params)

    def get_scene(self, project_id, scene_id, headers):
        return self._request("GET", f"/projects/{project_id}/scenes/{scene_id}", headers=headers)

    def validate_scene(self, project_id, scene_id, headers):
        return self._request("POST", f"/projects/{project_id}/scenes/{scene_id}/validate", headers=headers)

    def deploy_scene(self, project_id, scene_id, headers):
        return self._request("POST", f"/projects/{project_id}/scenes/{scene_id}/deploy", headers=headers)

    def revise_scene(self, project_id, scene_id, headers):
        return self._request("POST", f"/projects/{project_id}/scenes/{scene_id}/revise", headers=headers)

    def archive_scene(self, project_id, scene_id, headers):
        return self._request("POST", f"/projects/{project_id}/scenes/{scene_id}/archive", headers=headers)

    # ---- Visits & assignments ----
    def create_visit(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/visits", payload, headers)

    def list_visits(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/visits", headers=headers, params=params)

    def get_visit_nested(self, project_id, visit_id, headers):
        return self._request("GET", f"/projects/{project_id}/visits/{visit_id}", headers=headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visit_assignments_flat(self, visit_id, headers, params=None):
        return self._request("GET", f"/visits/{visit_id}/assignments", headers=headers, params=params)

    def list_crew_assignments(self, crew_member_id, headers, params=None):
        return self._request("GET", f"/crew-members/{crew_member_id}/assignments", headers=headers, params=params)

    def create_assignment(self, project_id, visit_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/visits/{visit_id}/assignments", payload, headers)

    def list_assignments(self, project_id, visit_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/visits/{visit_id}/assignments", headers=headers, params=params)

    def release_assignment(self, project_id, visit_id, assignment_id, headers):
        return self._request("POST", f"/projects/{project_id}/visits/{visit_id}/assignments/{assignment_id}/release", headers=headers)

    def confirm_visit(self, project_id, visit_id, headers):
        return self._request("POST", f"/projects/{project_id}/visits/{visit_id}/confirm", headers=headers)

    def start_visit(self, project_id, visit_id, headers):
        return self._request("POST", f"/projects/{project_id}/visits/{visit_id}/start", headers=headers)

    def complete_visit(self, project_id, visit_id, headers):
        return self._request("POST", f"/projects/{project_id}/visits/{visit_id}/complete", headers=headers)

    def cancel_visit(self, project_id, visit_id, headers):
        return self._request("POST", f"/projects/{project_id}/visits/{visit_id}/cancel", headers=headers)

    def no_show_visit(self, project_id, visit_id, headers):
        return self._request("POST", f"/projects/{project_id}/visits/{visit_id}/no-show", headers=headers)

    # ---- Crew ----
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/crew-members/{crew_member_id}", headers=headers)

    # ---- Contract ----
    def create_contract(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/contract", payload, headers)

    def get_contract(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/contract", headers=headers)

    def activate_contract(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/contract/activate", headers=headers)

    def suspend_contract(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/contract/suspend", headers=headers)

    def resume_contract(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/contract/resume", headers=headers)

    def cancel_contract(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/contract/cancel", headers=headers)

    def consume_contract(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/contract/consume", payload, headers)

    # ---- RMA ----
    def create_rma_ticket(self, payload, headers):
        return self._request("POST", "/rma-tickets", payload, headers)

    def get_rma_ticket(self, rma_id, headers):
        return self._request("GET", f"/rma-tickets/{rma_id}", headers=headers)

    def list_rma_tickets(self, headers, params=None):
        return self._request("GET", "/rma-tickets", headers=headers, params=params)

    def authorize_rma(self, rma_id, headers):
        return self._request("POST", f"/rma-tickets/{rma_id}/authorize", headers=headers)

    def deny_rma(self, rma_id, headers):
        return self._request("POST", f"/rma-tickets/{rma_id}/deny", headers=headers)

    def ship_rma(self, rma_id, headers):
        return self._request("POST", f"/rma-tickets/{rma_id}/ship", headers=headers)

    def close_rma(self, rma_id, headers):
        return self._request("POST", f"/rma-tickets/{rma_id}/close", headers=headers)

    # ---- Change orders ----
    def create_change_order(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/change-orders", payload, headers)

    def list_change_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/change-orders", headers=headers, params=params)

    def get_change_order(self, project_id, co_id, headers):
        return self._request("GET", f"/projects/{project_id}/change-orders/{co_id}", headers=headers)

    def approve_change_order(self, project_id, co_id, headers):
        return self._request("POST", f"/projects/{project_id}/change-orders/{co_id}/approve", headers=headers)

    def reject_change_order(self, project_id, co_id, headers):
        return self._request("POST", f"/projects/{project_id}/change-orders/{co_id}/reject", headers=headers)

    def apply_change_order(self, project_id, co_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/change-orders/{co_id}/apply", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
