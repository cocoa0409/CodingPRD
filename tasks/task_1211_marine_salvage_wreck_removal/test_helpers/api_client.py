"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Casualties ───
    def create_casualty(self, payload, headers):
        return self._request("POST", "/casualties", payload, headers)

    def list_casualties(self, headers, params=None):
        return self._request("GET", "/casualties", headers=headers, params=params)

    def get_casualty(self, casualty_id, headers):
        return self._request("GET", f"/casualties/{casualty_id}", headers=headers)

    def close_casualty(self, casualty_id, headers):
        return self._request("POST", f"/casualties/{casualty_id}/close", {}, headers)

    # ─── Assessments ───
    def create_assessment(self, payload, headers):
        return self._request("POST", "/assessments", payload, headers)

    def list_assessments(self, headers, params=None):
        return self._request("GET", "/assessments", headers=headers, params=params)

    def get_assessment(self, assessment_id, headers):
        return self._request("GET", f"/assessments/{assessment_id}", headers=headers)

    def approve_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/approve", {}, headers)

    def reject_assessment(self, assessment_id, headers):
        return self._request("POST", f"/assessments/{assessment_id}/reject", {}, headers)

    # ─── Salvage plans ───
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", headers=headers, params=params)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def submit_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/submit", {}, headers)

    def approve_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/approve", {}, headers)

    def reject_plan(self, plan_id, headers):
        return self._request("POST", f"/plans/{plan_id}/reject", {}, headers)

    # ─── Contracts ───
    def create_contract(self, payload, headers):
        return self._request("POST", "/contracts", payload, headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/contracts", headers=headers, params=params)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def offer_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/offer", {}, headers)

    def counter_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/counter", payload, headers)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/sign", {}, headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", payload, headers)

    def settle_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/settle", {}, headers)

    # ─── Securities ───
    def create_security(self, payload, headers):
        return self._request("POST", "/securities", payload, headers)

    def list_securities(self, headers, params=None):
        return self._request("GET", "/securities", headers=headers, params=params)

    def get_security(self, security_id, headers):
        return self._request("GET", f"/securities/{security_id}", headers=headers)

    def disburse_security(self, security_id, payload, headers):
        return self._request("POST", f"/securities/{security_id}/disburse", payload, headers)

    # ─── Permits ───
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def grant_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/grant", {}, headers)

    def suspend_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/suspend", {}, headers)

    def reinstate_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reinstate", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    # ─── Equipment assets ───
    def create_equipment_asset(self, payload, headers):
        return self._request("POST", "/equipment-assets", payload, headers)

    def list_equipment_assets(self, headers, params=None):
        return self._request("GET", "/equipment-assets", headers=headers, params=params)

    def get_equipment_asset(self, asset_id, headers):
        return self._request("GET", f"/equipment-assets/{asset_id}", headers=headers)

    # ─── Equipment charters ───
    def create_charter(self, payload, headers):
        return self._request("POST", "/charters", payload, headers)

    def list_charters(self, headers, params=None):
        return self._request("GET", "/charters", headers=headers, params=params)

    def get_charter(self, charter_id, headers):
        return self._request("GET", f"/charters/{charter_id}", headers=headers)

    def on_hire_charter(self, charter_id, headers):
        return self._request("POST", f"/charters/{charter_id}/on-hire", {}, headers)

    def off_hire_charter(self, charter_id, headers):
        return self._request("POST", f"/charters/{charter_id}/off-hire", {}, headers)

    # ─── Weather windows ───
    def create_weather_window(self, payload, headers):
        return self._request("POST", "/weather-windows", payload, headers)

    def list_weather_windows(self, headers, params=None):
        return self._request("GET", "/weather-windows", headers=headers, params=params)

    def get_weather_window(self, window_id, headers):
        return self._request("GET", f"/weather-windows/{window_id}", headers=headers)

    # ─── Operation phases ───
    def create_phase(self, payload, headers):
        return self._request("POST", "/phases", payload, headers)

    def list_phases(self, headers, params=None):
        return self._request("GET", "/phases", headers=headers, params=params)

    def get_phase(self, phase_id, headers):
        return self._request("GET", f"/phases/{phase_id}", headers=headers)

    def activate_phase(self, phase_id, payload, headers):
        return self._request("POST", f"/phases/{phase_id}/activate", payload, headers)

    def hold_weather_phase(self, phase_id, headers):
        return self._request("POST", f"/phases/{phase_id}/hold-weather", {}, headers)

    def resume_phase(self, phase_id, headers):
        return self._request("POST", f"/phases/{phase_id}/resume", {}, headers)

    def complete_phase(self, phase_id, headers):
        return self._request("POST", f"/phases/{phase_id}/complete", {}, headers)

    # ─── Pollution events ───
    def create_pollution_event(self, payload, headers):
        return self._request("POST", "/pollution-events", payload, headers)

    def list_pollution_events(self, headers, params=None):
        return self._request("GET", "/pollution-events", headers=headers, params=params)

    def get_pollution_event(self, event_id, headers):
        return self._request("GET", f"/pollution-events/{event_id}", headers=headers)

    def escalate_pollution_event(self, event_id, payload, headers):
        return self._request("POST", f"/pollution-events/{event_id}/escalate", payload, headers)

    def contain_pollution_event(self, event_id, headers):
        return self._request("POST", f"/pollution-events/{event_id}/contain", {}, headers)

    def verify_clean_pollution_event(self, event_id, headers):
        return self._request("POST", f"/pollution-events/{event_id}/verify-clean", {}, headers)

    # ─── Recovered property ───
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def secure_ashore_property(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/secure-ashore", payload, headers)

    def survey_property(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/survey", payload, headers)

    def verify_value_property(self, property_id, headers):
        return self._request("POST", f"/properties/{property_id}/verify-value", {}, headers)

    def lien_property(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/lien", payload, headers)

    def dispose_property(self, property_id, payload, headers):
        return self._request("POST", f"/properties/{property_id}/dispose", payload, headers)

    # ─── Storage sites ───
    def create_storage_site(self, payload, headers):
        return self._request("POST", "/storage-sites", payload, headers)

    def list_storage_sites(self, headers, params=None):
        return self._request("GET", "/storage-sites", headers=headers, params=params)

    def get_storage_site(self, site_id, headers):
        return self._request("GET", f"/storage-sites/{site_id}", headers=headers)

    # ─── Salvage awards ───
    def create_award(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/award", {}, headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/awards/{award_id}", headers=headers)

    def agree_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/agree", payload, headers)

    def submit_arbitration_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/submit-arbitration", {}, headers)

    def decide_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/decide", payload, headers)

    def appeal_award(self, award_id, payload, headers):
        return self._request("POST", f"/awards/{award_id}/appeal", payload, headers)

    def mark_paid_award(self, award_id, headers):
        return self._request("POST", f"/awards/{award_id}/mark-paid", {}, headers)

    # ─── Insurer documentation packs ───
    def create_doc_pack(self, payload, headers):
        return self._request("POST", "/doc-packs", payload, headers)

    def list_doc_packs(self, headers, params=None):
        return self._request("GET", "/doc-packs", headers=headers, params=params)

    def get_doc_pack(self, pack_id, headers):
        return self._request("GET", f"/doc-packs/{pack_id}", headers=headers)

    def create_doc_entry(self, pack_id, payload, headers):
        return self._request("POST", f"/doc-packs/{pack_id}/entries", payload, headers)

    def list_doc_entries(self, pack_id, headers, params=None):
        return self._request("GET", f"/doc-packs/{pack_id}/entries", headers=headers, params=params)

    def submit_doc_pack(self, pack_id, headers):
        return self._request("POST", f"/doc-packs/{pack_id}/submit", {}, headers)

    def review_doc_pack(self, pack_id, payload, headers):
        return self._request("POST", f"/doc-packs/{pack_id}/review", payload, headers)


api_client = ApiClient()
