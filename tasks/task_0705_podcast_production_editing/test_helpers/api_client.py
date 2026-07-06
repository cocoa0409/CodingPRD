"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- Show ----
    def create_show(self, payload, headers):
        return self._request("POST", "/shows", payload, headers)

    def list_shows(self, headers, params=None):
        return self._request("GET", "/shows", headers=headers, params=params)

    def get_show(self, show_id, headers):
        return self._request("GET", f"/shows/{show_id}", headers=headers)

    # ---- EngagementContract ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", payload, headers)

    def expire_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/expire", {}, headers)

    # ---- RetainerCycle ----
    def create_retainer_cycle(self, payload, headers):
        return self._request("POST", "/retainer-cycles", payload, headers)

    def list_retainer_cycles(self, headers, params=None):
        return self._request("GET", "/retainer-cycles", headers=headers, params=params)

    def get_retainer_cycle(self, cycle_id, headers):
        return self._request("GET", f"/retainer-cycles/{cycle_id}", headers=headers)

    def retainer_cycle_projection(self, cycle_id, headers):
        return self._request("GET", f"/retainer-cycles/{cycle_id}/projection", headers=headers)

    def close_retainer_cycle(self, cycle_id, headers):
        return self._request("POST", f"/retainer-cycles/{cycle_id}/close", {}, headers)

    # ---- Engineer ----
    def create_engineer(self, payload, headers):
        return self._request("POST", "/engineers", payload, headers)

    def list_engineers(self, headers, params=None):
        return self._request("GET", "/engineers", headers=headers, params=params)

    def get_engineer(self, engineer_id, headers):
        return self._request("GET", f"/engineers/{engineer_id}", headers=headers)

    # ---- Episode ----
    def create_episode(self, payload, headers):
        return self._request("POST", "/episodes", payload, headers)

    def list_episodes(self, headers, params=None):
        return self._request("GET", "/episodes", headers=headers, params=params)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def lock_assets(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/lock-assets", payload, headers)

    def submit_edit(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/submit-edit", {}, headers)

    def request_revision(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/request-revision", {}, headers)

    def approve_edit(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/approve-edit", {}, headers)

    def schedule_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/schedule", {}, headers)

    def publish_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/publish", {}, headers)

    def cancel_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/cancel", {}, headers)

    def archive_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/archive", {}, headers)

    # ---- Session ----
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def start_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/start", {}, headers)

    def complete_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", {}, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", {}, headers)

    # ---- Deliverable ----
    def create_deliverable(self, payload, headers):
        return self._request("POST", "/deliverables", payload, headers)

    def list_deliverables(self, headers, params=None):
        return self._request("GET", "/deliverables", headers=headers, params=params)

    def get_deliverable(self, deliverable_id, headers):
        return self._request("GET", f"/deliverables/{deliverable_id}", headers=headers)

    # ---- AssetVersion ----
    def create_asset_version(self, payload, headers):
        return self._request("POST", "/asset-versions", payload, headers)

    def list_asset_versions(self, headers, params=None):
        return self._request("GET", "/asset-versions", headers=headers, params=params)

    def get_asset_version(self, version_id, headers):
        return self._request("GET", f"/asset-versions/{version_id}", headers=headers)

    def accept_asset_version(self, version_id, headers):
        return self._request("POST", f"/asset-versions/{version_id}/accept", {}, headers)

    def reject_asset_version(self, version_id, headers):
        return self._request("POST", f"/asset-versions/{version_id}/reject", {}, headers)

    # ---- Invoice ----
    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def mark_invoice_overdue(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/mark-overdue", {}, headers)

    def dispute_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/dispute", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # ---- AdCampaign ----
    def create_ad_campaign(self, payload, headers):
        return self._request("POST", "/ad-campaigns", payload, headers)

    def list_ad_campaigns(self, headers, params=None):
        return self._request("GET", "/ad-campaigns", headers=headers, params=params)

    def get_ad_campaign(self, campaign_id, headers):
        return self._request("GET", f"/ad-campaigns/{campaign_id}", headers=headers)

    def approve_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/ad-campaigns/{campaign_id}/approve", {}, headers)

    def reconcile_ad_campaign(self, campaign_id, payload, headers):
        return self._request("POST", f"/ad-campaigns/{campaign_id}/reconcile", payload, headers)

    def cancel_ad_campaign(self, campaign_id, headers):
        return self._request("POST", f"/ad-campaigns/{campaign_id}/cancel", {}, headers)

    # ---- AdSlot ----
    def create_ad_slot(self, payload, headers):
        return self._request("POST", "/ad-slots", payload, headers)

    def list_ad_slots(self, headers, params=None):
        return self._request("GET", "/ad-slots", headers=headers, params=params)

    def get_ad_slot(self, slot_id, headers):
        return self._request("GET", f"/ad-slots/{slot_id}", headers=headers)


api_client = ApiClient()
