"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/studio/_clock/set_current_utc", payload, headers)

    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/studio/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/studio/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/studio/clients/{client_id}", headers=headers)

    def activate_client(self, client_id, headers):
        return self._request("POST", f"/studio/clients/{client_id}/activate", {}, headers)

    def suspend_client(self, client_id, headers):
        return self._request("POST", f"/studio/clients/{client_id}/suspend", {}, headers)

    def terminate_client(self, client_id, headers):
        return self._request("POST", f"/studio/clients/{client_id}/terminate", {}, headers)

    def create_credit_adjustment(self, client_id, payload, headers):
        return self._request("POST", f"/studio/clients/{client_id}/credit-adjustments", payload, headers)

    # ---- Engineers ----
    def create_engineer(self, payload, headers):
        return self._request("POST", "/studio/engineers", payload, headers)

    def list_engineers(self, headers, params=None):
        return self._request("GET", "/studio/engineers", headers=headers, params=params)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/studio/engineers/{engineer_id}", headers=headers)

    def set_engineer_availability(self, engineer_id, payload, headers):
        return self._request("POST", f"/studio/engineers/{engineer_id}/set-availability", payload, headers)

    # ---- Platform profiles ----
    def create_platform_profile(self, payload, headers):
        return self._request("POST", "/studio/platform-profiles", payload, headers)

    def list_platform_profiles(self, headers, params=None):
        return self._request("GET", "/studio/platform-profiles", headers=headers, params=params)

    def get_platform_profile(self, profile_id, headers):
        return self._request("GET", f"/studio/platform-profiles/{profile_id}", headers=headers)

    # ---- Rush tier rules ----
    def create_rush_tier_rule(self, payload, headers):
        return self._request("POST", "/studio/rush-tier-rules", payload, headers)

    def list_rush_tier_rules(self, headers, params=None):
        return self._request("GET", "/studio/rush-tier-rules", headers=headers, params=params)

    # ---- Projects ----
    def create_project(self, payload, headers):
        return self._request("POST", "/studio/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/studio/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/studio/projects/{project_id}", headers=headers)

    def book_project(self, project_id, payload, headers):
        return self._request("POST", f"/studio/projects/{project_id}/book", payload, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/cancel", {}, headers)

    def begin_intake(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/begin-intake", {}, headers)

    def complete_project_qc(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/qc/complete", {}, headers)

    def start_mastering(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/start-mastering", {}, headers)

    def deliver_project(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/deliver", {}, headers)

    def finalize_delivery(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/finalize-delivery", {}, headers)

    def archive_project(self, project_id, payload, headers):
        return self._request("POST", f"/studio/projects/{project_id}/archive", payload, headers)

    def recall_project(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/recall", {}, headers)

    def resume_from_recall(self, project_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/resume-from-recall", {}, headers)

    # ---- Session slots ----
    def create_session_slot(self, payload, headers):
        return self._request("POST", "/studio/session-slots", payload, headers)

    def list_session_slots(self, headers, params=None):
        return self._request("GET", "/studio/session-slots", headers=headers, params=params)

    def get_session_slot(self, slot_id, headers):
        return self._request("GET", f"/studio/session-slots/{slot_id}", headers=headers)

    def confirm_session_slot(self, slot_id, headers):
        return self._request("POST", f"/studio/session-slots/{slot_id}/confirm", {}, headers)

    def release_session_slot(self, slot_id, headers):
        return self._request("POST", f"/studio/session-slots/{slot_id}/release", {}, headers)

    def cancel_session_slot(self, slot_id, headers):
        return self._request("POST", f"/studio/session-slots/{slot_id}/cancel", {}, headers)

    # ---- Source assets ----
    def upload_source_asset(self, project_id, payload, headers):
        return self._request("POST", f"/studio/projects/{project_id}/source-assets", payload, headers)

    def list_source_assets(self, project_id, headers, params=None):
        return self._request("GET", f"/studio/projects/{project_id}/source-assets", headers=headers, params=params)

    def get_source_asset(self, asset_id, headers):
        return self._request("GET", f"/studio/source-assets/{asset_id}", headers=headers)

    def qc_pass_source_asset(self, asset_id, headers):
        return self._request("POST", f"/studio/source-assets/{asset_id}/qc-pass", {}, headers)

    def qc_fail_source_asset(self, asset_id, payload, headers):
        return self._request("POST", f"/studio/source-assets/{asset_id}/qc-fail", payload, headers)

    def qc_waive_source_asset(self, asset_id, headers):
        return self._request("POST", f"/studio/source-assets/{asset_id}/qc-waive", {}, headers)

    # ---- Revision rounds ----
    def list_revision_rounds(self, project_id, headers, params=None):
        return self._request("GET", f"/studio/projects/{project_id}/rounds", headers=headers, params=params)

    def get_revision_round(self, round_id, headers):
        return self._request("GET", f"/studio/rounds/{round_id}", headers=headers)

    def submit_round(self, project_id, round_id, payload, headers):
        return self._request("POST", f"/studio/projects/{project_id}/rounds/{round_id}/submit", payload, headers)

    def approve_round(self, project_id, round_id, headers):
        return self._request("POST", f"/studio/projects/{project_id}/rounds/{round_id}/approve", {}, headers)

    def reject_round(self, project_id, round_id, payload, headers):
        return self._request("POST", f"/studio/projects/{project_id}/rounds/{round_id}/reject", payload, headers)

    # ---- Deliverables ----
    def create_deliverable(self, project_id, payload, headers):
        return self._request("POST", f"/studio/projects/{project_id}/deliverables", payload, headers)

    def list_project_deliverables(self, project_id, headers, params=None):
        return self._request("GET", f"/studio/projects/{project_id}/deliverables", headers=headers, params=params)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/studio/deliverables", headers=headers, params=params)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/studio/deliverables/{deliverable_id}", headers=headers)

    def submit_deliverable_qc(self, deliverable_id, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/submit-qc", {}, headers)

    def qc_pass_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/qc-pass", {}, headers)

    def qc_fail_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/qc-fail", {}, headers)

    def rebuild_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/rebuild", {}, headers)

    def embed_metadata(self, deliverable_id, payload, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/metadata-tags", payload, headers)

    def verify_deliverable_metadata(self, deliverable_id, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/verify-metadata", {}, headers)

    def retire_deliverable(self, deliverable_id, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/retire", {}, headers)

    # ---- Metadata tags ----
    def list_deliverable_metadata_tags(self, deliverable_id, headers, params=None):
        return self._request("GET", f"/studio/deliverables/{deliverable_id}/metadata-tags", headers=headers, params=params)

    def get_metadata_tag(self, tag_id, headers):
        return self._request("GET", f"/studio/metadata-tags/{tag_id}", headers=headers)

    def verify_metadata_tag(self, tag_id, headers):
        return self._request("POST", f"/studio/metadata-tags/{tag_id}/verify", {}, headers)

    def flag_metadata_mismatch(self, tag_id, headers):
        return self._request("POST", f"/studio/metadata-tags/{tag_id}/flag-mismatch", {}, headers)

    def revoke_metadata_tag(self, tag_id, headers):
        return self._request("POST", f"/studio/metadata-tags/{tag_id}/revoke", {}, headers)

    # ---- QC reports ----
    def create_qc_report(self, deliverable_id, payload, headers):
        return self._request("POST", f"/studio/deliverables/{deliverable_id}/qc-reports", payload, headers)

    def list_project_qc_reports(self, project_id, headers, params=None):
        return self._request("GET", f"/studio/projects/{project_id}/qc-reports", headers=headers, params=params)

    def list_qc_reports(self, headers, params=None):
        return self._request("GET", "/studio/qc-reports", headers=headers, params=params)

    def list_deliverable_qc_reports(self, deliverable_id, headers, params=None):
        return self._request("GET", f"/studio/deliverables/{deliverable_id}/qc-reports", headers=headers, params=params)

    # ---- Archive bundles ----
    def list_archive_bundles(self, headers, params=None):
        return self._request("GET", "/studio/archive-bundles", headers=headers, params=params)

    def get_archive_bundle(self, bundle_id, headers):
        return self._request("GET", f"/studio/archive-bundles/{bundle_id}", headers=headers)

    def recall_archive_bundle(self, bundle_id, headers):
        return self._request("POST", f"/studio/archive-bundles/{bundle_id}/recall", {}, headers)

    def begin_restore(self, bundle_id, headers):
        return self._request("POST", f"/studio/archive-bundles/{bundle_id}/begin-restore", {}, headers)

    def complete_restore(self, bundle_id, headers):
        return self._request("POST", f"/studio/archive-bundles/{bundle_id}/complete-restore", {}, headers)

    def fail_restore(self, bundle_id, headers):
        return self._request("POST", f"/studio/archive-bundles/{bundle_id}/fail-restore", {}, headers)


api_client = ApiClient()
