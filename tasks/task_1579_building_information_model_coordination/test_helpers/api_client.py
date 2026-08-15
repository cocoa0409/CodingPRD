"""API client: one method per endpoint defined in the PRD (§4 endpoint table).

All resources are served under the `/api` prefix (PRD §1).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.5)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Project
    # ------------------------------------------------------------------
    def create_project(self, payload, headers):
        return self._request("POST", "/api/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/api/projects/{project_id}", headers=headers)

    def advance_phase(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/advance-phase",
                             {}, headers)

    def run_coordination_sweep(self, project_id, headers):
        return self._request("POST", f"/api/projects/{project_id}/run-coordination-sweep",
                             {}, headers)

    # ------------------------------------------------------------------
    # LodRequirement
    # ------------------------------------------------------------------
    def create_lod_requirement(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/lod-requirements",
                             payload, headers)

    def list_lod_requirements(self, project_id, headers, params=None):
        return self._request("GET", f"/api/projects/{project_id}/lod-requirements",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # TradePartner
    # ------------------------------------------------------------------
    def create_trade_partner(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/trade-partners",
                             payload, headers)

    def list_trade_partners(self, project_id, headers, params=None):
        return self._request("GET", f"/api/projects/{project_id}/trade-partners",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # TradeModel
    # ------------------------------------------------------------------
    def create_trade_model(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/trade-models",
                             payload, headers)

    def list_trade_models(self, headers, params=None):
        return self._request("GET", "/api/trade-models", headers=headers, params=params)

    def get_trade_model(self, model_id, headers):
        return self._request("GET", f"/api/trade-models/{model_id}", headers=headers)

    def submit_trade_model(self, model_id, headers):
        return self._request("POST", f"/api/trade-models/{model_id}/submit", {}, headers)

    def accept_trade_model(self, model_id, headers):
        return self._request("POST", f"/api/trade-models/{model_id}/accept", {}, headers)

    def reject_trade_model(self, model_id, headers):
        return self._request("POST", f"/api/trade-models/{model_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # FederatedModel / members
    # ------------------------------------------------------------------
    def create_federated_model(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/federated-models",
                             payload, headers)

    def list_federated_models(self, headers, params=None):
        return self._request("GET", "/api/federated-models", headers=headers, params=params)

    def get_federated_model(self, fed_id, headers):
        return self._request("GET", f"/api/federated-models/{fed_id}", headers=headers)

    def freeze_federated_model(self, fed_id, headers):
        return self._request("POST", f"/api/federated-models/{fed_id}/freeze", {}, headers)

    def unfreeze_federated_model(self, fed_id, headers):
        return self._request("POST", f"/api/federated-models/{fed_id}/unfreeze", {}, headers)

    def release_federated_model(self, fed_id, headers):
        return self._request("POST", f"/api/federated-models/{fed_id}/release", {}, headers)

    def list_federated_model_members(self, fed_id, headers, params=None):
        return self._request("GET", f"/api/federated-models/{fed_id}/members",
                             headers=headers, params=params)

    def list_trade_model_memberships(self, model_id, headers, params=None):
        return self._request("GET", f"/api/trade-models/{model_id}/federated-model-members",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # FreezeWindow
    # ------------------------------------------------------------------
    def create_freeze_window(self, fed_id, payload, headers):
        return self._request("POST", f"/api/federated-models/{fed_id}/freeze-windows",
                             payload, headers)

    def list_freeze_windows(self, fed_id, headers, params=None):
        return self._request("GET", f"/api/federated-models/{fed_id}/freeze-windows",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # ClashDetectionRun / ClashIssue
    # ------------------------------------------------------------------
    def create_clash_run(self, fed_id, payload, headers):
        return self._request("POST", f"/api/federated-models/{fed_id}/clash-runs",
                             payload, headers)

    def list_clash_runs(self, headers, params=None):
        return self._request("GET", "/api/clash-runs", headers=headers, params=params)

    def get_clash_run(self, run_id, headers):
        return self._request("GET", f"/api/clash-runs/{run_id}", headers=headers)

    def start_clash_run(self, run_id, headers):
        return self._request("POST", f"/api/clash-runs/{run_id}/start", {}, headers)

    def import_clash(self, run_id, payload, headers):
        return self._request("POST", f"/api/clash-runs/{run_id}/clashes", payload, headers)

    def complete_clash_run(self, run_id, headers):
        return self._request("POST", f"/api/clash-runs/{run_id}/complete", {}, headers)

    def list_clash_issues(self, headers, params=None):
        return self._request("GET", "/api/clash-issues", headers=headers, params=params)

    def get_clash_issue(self, clash_id, headers):
        return self._request("GET", f"/api/clash-issues/{clash_id}", headers=headers)

    def assign_clash(self, clash_id, payload, headers):
        return self._request("POST", f"/api/clash-issues/{clash_id}/assign",
                             payload, headers)

    def resolve_clash(self, clash_id, payload, headers):
        return self._request("POST", f"/api/clash-issues/{clash_id}/resolve",
                             payload, headers)

    def verify_clash(self, clash_id, payload, headers):
        return self._request("POST", f"/api/clash-issues/{clash_id}/verify",
                             payload, headers)

    def reopen_clash(self, clash_id, headers):
        return self._request("POST", f"/api/clash-issues/{clash_id}/reopen", {}, headers)

    # ------------------------------------------------------------------
    # CoordinationMeeting / ResolutionCommitment
    # ------------------------------------------------------------------
    def create_coordination_meeting(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/coordination-meetings",
                             payload, headers)

    def list_coordination_meetings(self, headers, params=None):
        return self._request("GET", "/api/coordination-meetings",
                             headers=headers, params=params)

    def get_coordination_meeting(self, meeting_id, headers):
        return self._request("GET", f"/api/coordination-meetings/{meeting_id}",
                             headers=headers)

    def start_meeting(self, meeting_id, headers):
        return self._request("POST", f"/api/coordination-meetings/{meeting_id}/start",
                             {}, headers)

    def adjourn_meeting(self, meeting_id, headers):
        return self._request("POST", f"/api/coordination-meetings/{meeting_id}/adjourn",
                             {}, headers)

    def create_commitment(self, meeting_id, payload, headers):
        return self._request("POST", f"/api/coordination-meetings/{meeting_id}/commitments",
                             payload, headers)

    def list_commitments(self, headers, params=None):
        return self._request("GET", "/api/commitments", headers=headers, params=params)

    def get_commitment(self, commitment_id, headers):
        return self._request("GET", f"/api/commitments/{commitment_id}", headers=headers)

    def waive_commitment(self, commitment_id, headers):
        return self._request("POST", f"/api/commitments/{commitment_id}/waive", {}, headers)

    # ------------------------------------------------------------------
    # FabricationPackage / SignOff
    # ------------------------------------------------------------------
    def create_fabrication_package(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/fabrication-packages",
                             payload, headers)

    def list_fabrication_packages(self, headers, params=None):
        return self._request("GET", "/api/fabrication-packages",
                             headers=headers, params=params)

    def get_fabrication_package(self, package_id, headers):
        return self._request("GET", f"/api/fabrication-packages/{package_id}",
                             headers=headers)

    def submit_package_for_signoff(self, package_id, headers):
        return self._request("POST",
                             f"/api/fabrication-packages/{package_id}/submit-for-signoff",
                             {}, headers)

    def release_fabrication_package(self, package_id, headers):
        return self._request("POST",
                             f"/api/fabrication-packages/{package_id}/release",
                             {}, headers)

    def void_fabrication_package(self, package_id, headers):
        return self._request("POST", f"/api/fabrication-packages/{package_id}/void",
                             {}, headers)

    def list_package_signoffs(self, package_id, headers, params=None):
        return self._request("GET", f"/api/fabrication-packages/{package_id}/signoffs",
                             headers=headers, params=params)

    def list_trade_model_signoffs(self, model_id, headers, params=None):
        return self._request("GET", f"/api/trade-models/{model_id}/signoffs",
                             headers=headers, params=params)

    def get_signoff(self, signoff_id, headers):
        return self._request("GET", f"/api/signoffs/{signoff_id}", headers=headers)

    def sign_signoff(self, signoff_id, headers):
        return self._request("POST", f"/api/signoffs/{signoff_id}/sign", {}, headers)

    def decline_signoff(self, signoff_id, headers):
        return self._request("POST", f"/api/signoffs/{signoff_id}/decline", {}, headers)

    # ------------------------------------------------------------------
    # AsBuiltModel
    # ------------------------------------------------------------------
    def create_as_built_model(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/as-built-models",
                             payload, headers)

    def list_as_built_models(self, headers, params=None):
        return self._request("GET", "/api/as-built-models", headers=headers, params=params)

    def get_as_built_model(self, as_built_id, headers):
        return self._request("GET", f"/api/as-built-models/{as_built_id}", headers=headers)

    def submit_as_built_model(self, as_built_id, headers):
        return self._request("POST", f"/api/as-built-models/{as_built_id}/submit",
                             {}, headers)

    def verify_as_built_model(self, as_built_id, payload, headers):
        return self._request("POST", f"/api/as-built-models/{as_built_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # QuantityTakeoff
    # ------------------------------------------------------------------
    def create_quantity_takeoff(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/quantity-takeoffs",
                             payload, headers)

    def list_quantity_takeoffs(self, headers, params=None):
        return self._request("GET", "/api/quantity-takeoffs", headers=headers, params=params)

    def get_quantity_takeoff(self, takeoff_id, headers):
        return self._request("GET", f"/api/quantity-takeoffs/{takeoff_id}", headers=headers)

    def approve_quantity_takeoff(self, takeoff_id, headers):
        return self._request("POST", f"/api/quantity-takeoffs/{takeoff_id}/approve",
                             {}, headers)

    # ------------------------------------------------------------------
    # HandoverPackage
    # ------------------------------------------------------------------
    def create_handover_package(self, project_id, payload, headers):
        return self._request("POST", f"/api/projects/{project_id}/handover-packages",
                             payload, headers)

    def list_handover_packages(self, headers, params=None):
        return self._request("GET", "/api/handover-packages", headers=headers, params=params)

    def get_handover_package(self, handover_id, headers):
        return self._request("GET", f"/api/handover-packages/{handover_id}",
                             headers=headers)

    def mark_handover_ready(self, handover_id, headers):
        return self._request("POST", f"/api/handover-packages/{handover_id}/mark-ready",
                             {}, headers)

    def transmit_handover_package(self, handover_id, headers):
        return self._request("POST", f"/api/handover-packages/{handover_id}/transmit",
                             {}, headers)

    def respond_handover_package(self, handover_id, payload, headers):
        return self._request("POST", f"/api/handover-packages/{handover_id}/respond",
                             payload, headers)


api_client = ApiClient()
