"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient

P = "/citizen-science"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Protocols ---
    def create_protocol(self, payload, headers):
        return self._request("POST", f"{P}/protocols", payload, headers)

    def list_protocols(self, headers, params=None):
        return self._request("GET", f"{P}/protocols", headers=headers, params=params)

    def get_protocol(self, protocol_id, headers):
        return self._request("GET", f"{P}/protocols/{protocol_id}", headers=headers)

    def activate_protocol(self, protocol_id, headers):
        return self._request("POST", f"{P}/protocols/{protocol_id}/activate", {}, headers)

    # --- Volunteers ---
    def create_volunteer(self, payload, headers):
        return self._request("POST", f"{P}/volunteers", payload, headers)

    def list_volunteers(self, headers, params=None):
        return self._request("GET", f"{P}/volunteers", headers=headers, params=params)

    def get_volunteer(self, volunteer_id, headers):
        return self._request("GET", f"{P}/volunteers/{volunteer_id}", headers=headers)

    def reinstate_volunteer(self, volunteer_id, headers):
        return self._request("POST", f"{P}/volunteers/{volunteer_id}/reinstate", {}, headers)

    # --- Experts ---
    def create_expert(self, payload, headers):
        return self._request("POST", f"{P}/experts", payload, headers)

    def list_experts(self, headers, params=None):
        return self._request("GET", f"{P}/experts", headers=headers, params=params)

    def get_expert(self, expert_id, headers):
        return self._request("GET", f"{P}/experts/{expert_id}", headers=headers)

    def list_expert_votes(self, expert_id, headers, params=None):
        return self._request("GET", f"{P}/experts/{expert_id}/votes",
                             headers=headers, params=params)

    # --- Certifications ---
    def create_certification(self, payload, headers):
        return self._request("POST", f"{P}/certifications", payload, headers)

    def list_certifications(self, headers, params=None):
        return self._request("GET", f"{P}/certifications", headers=headers, params=params)

    def get_certification(self, certification_id, headers):
        return self._request("GET", f"{P}/certifications/{certification_id}", headers=headers)

    def complete_training(self, certification_id, payload, headers):
        return self._request("POST", f"{P}/certifications/{certification_id}/complete-training",
                             payload, headers)

    def grant_certification(self, certification_id, headers):
        return self._request("POST", f"{P}/certifications/{certification_id}/grant", {}, headers)

    # --- Campaigns and survey sites ---
    def create_campaign(self, payload, headers):
        return self._request("POST", f"{P}/campaigns", payload, headers)

    def list_campaigns(self, headers, params=None):
        return self._request("GET", f"{P}/campaigns", headers=headers, params=params)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"{P}/campaigns/{campaign_id}", headers=headers)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"{P}/campaigns/{campaign_id}/open", {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"{P}/campaigns/{campaign_id}/close", {}, headers)

    def create_site(self, campaign_id, payload, headers):
        return self._request("POST", f"{P}/campaigns/{campaign_id}/sites", payload, headers)

    def list_sites(self, campaign_id, headers, params=None):
        return self._request("GET", f"{P}/campaigns/{campaign_id}/sites",
                             headers=headers, params=params)

    # --- Observations ---
    def create_observation(self, payload, headers):
        return self._request("POST", f"{P}/observations", payload, headers)

    def list_observations(self, headers, params=None):
        return self._request("GET", f"{P}/observations", headers=headers, params=params)

    def get_observation(self, observation_id, headers):
        return self._request("GET", f"{P}/observations/{observation_id}", headers=headers)

    def attach_photo(self, observation_id, payload, headers):
        return self._request("POST", f"{P}/observations/{observation_id}/photos",
                             payload, headers)

    def list_photos(self, observation_id, headers, params=None):
        return self._request("GET", f"{P}/observations/{observation_id}/photos",
                             headers=headers, params=params)

    def start_review(self, observation_id, headers):
        return self._request("POST", f"{P}/observations/{observation_id}/start-review",
                             {}, headers)

    def cast_vote(self, observation_id, payload, headers):
        return self._request("POST", f"{P}/observations/{observation_id}/votes",
                             payload, headers)

    def list_votes(self, observation_id, headers, params=None):
        return self._request("GET", f"{P}/observations/{observation_id}/votes",
                             headers=headers, params=params)

    def resubmit_observation(self, observation_id, payload, headers):
        return self._request("POST", f"{P}/observations/{observation_id}/resubmit",
                             payload, headers)

    def retract_observation(self, observation_id, payload, headers):
        return self._request("POST", f"{P}/observations/{observation_id}/retract",
                             payload, headers)

    # --- Equipment ---
    def create_equipment(self, payload, headers):
        return self._request("POST", f"{P}/equipment", payload, headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", f"{P}/equipment", headers=headers, params=params)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"{P}/equipment/{equipment_id}", headers=headers)

    def clear_quarantine(self, equipment_id, headers):
        return self._request("POST", f"{P}/equipment/{equipment_id}/clear-quarantine",
                             {}, headers)

    def complete_calibration(self, equipment_id, headers):
        return self._request("POST", f"{P}/equipment/{equipment_id}/complete-calibration",
                             {}, headers)

    # --- Equipment loans ---
    def create_loan(self, payload, headers):
        return self._request("POST", f"{P}/equipment-loans", payload, headers)

    def list_loans(self, headers, params=None):
        return self._request("GET", f"{P}/equipment-loans", headers=headers, params=params)

    def get_loan(self, loan_id, headers):
        return self._request("GET", f"{P}/equipment-loans/{loan_id}", headers=headers)

    def issue_loan(self, loan_id, headers):
        return self._request("POST", f"{P}/equipment-loans/{loan_id}/issue", {}, headers)

    def return_loan(self, loan_id, payload, headers):
        return self._request("POST", f"{P}/equipment-loans/{loan_id}/return", payload, headers)

    # --- Publications ---
    def create_publication(self, payload, headers):
        return self._request("POST", f"{P}/publications", payload, headers)

    def list_publications(self, headers, params=None):
        return self._request("GET", f"{P}/publications", headers=headers, params=params)

    def get_publication(self, publication_id, headers):
        return self._request("GET", f"{P}/publications/{publication_id}", headers=headers)

    def release_publication(self, publication_id, headers):
        return self._request("POST", f"{P}/publications/{publication_id}/release", {}, headers)

    def withdraw_publication(self, publication_id, payload, headers):
        return self._request("POST", f"{P}/publications/{publication_id}/withdraw",
                             payload, headers)

    # --- Research partners ---
    def create_partner(self, payload, headers):
        return self._request("POST", f"{P}/partners", payload, headers)

    def list_partners(self, headers, params=None):
        return self._request("GET", f"{P}/partners", headers=headers, params=params)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"{P}/partners/{partner_id}", headers=headers)

    def approve_partner(self, partner_id, headers):
        return self._request("POST", f"{P}/partners/{partner_id}/approve", {}, headers)

    # --- Access grants ---
    def create_access_grant(self, payload, headers):
        return self._request("POST", f"{P}/access-grants", payload, headers)

    def list_access_grants(self, headers, params=None):
        return self._request("GET", f"{P}/access-grants", headers=headers, params=params)

    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"{P}/access-grants/{grant_id}", headers=headers)

    def approve_access_grant(self, grant_id, headers):
        return self._request("POST", f"{P}/access-grants/{grant_id}/approve", {}, headers)

    def revoke_access_grant(self, grant_id, headers):
        return self._request("POST", f"{P}/access-grants/{grant_id}/revoke", {}, headers)

    # --- Recognition award ledger ---
    def list_awards(self, headers, params=None):
        return self._request("GET", f"{P}/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"{P}/awards/{award_id}", headers=headers)

    # --- Maintenance sweep ---
    def run_maintenance(self, headers):
        return self._request("POST", f"{P}/maintenance-runs", {}, headers)

    # --- Raw dispatch helpers for header-level negative tests ---
    def raw_get(self, path, headers, params=None):
        return self._request("GET", path, headers=headers, params=params)

    def raw_post(self, path, payload, headers):
        return self._request("POST", path, payload, headers)


api_client = ApiClient()
