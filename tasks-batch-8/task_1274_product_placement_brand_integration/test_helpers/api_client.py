"""API client: one method per endpoint defined in PRD §4."""
from typing import Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Brand & Brief ----
    def create_brand(self, payload, headers):
        return self._request("POST", "/brands", payload, headers)

    def get_brand(self, brand_id, headers):
        return self._request("GET", f"/brands/{brand_id}", headers=headers)

    def suspend_brand(self, brand_id, headers):
        return self._request("POST", f"/brands/{brand_id}/suspend", headers=headers)

    def resume_brand(self, brand_id, headers):
        return self._request("POST", f"/brands/{brand_id}/resume", headers=headers)

    def create_brief(self, brand_id, payload, headers):
        return self._request("POST", f"/brands/{brand_id}/briefs", payload, headers)

    def list_brand_briefs(self, brand_id, headers, params=None):
        return self._request("GET", f"/brands/{brand_id}/briefs", headers=headers, params=params)

    def list_brand_clearances(self, brand_id, headers, params=None):
        return self._request("GET", f"/brands/{brand_id}/clearances", headers=headers, params=params)

    def get_brief(self, brief_id, headers):
        return self._request("GET", f"/briefs/{brief_id}", headers=headers)

    def submit_brief(self, brief_id, headers):
        return self._request("POST", f"/briefs/{brief_id}/submit", headers=headers)

    def close_brief(self, brief_id, headers):
        return self._request("POST", f"/briefs/{brief_id}/close", headers=headers)

    def list_brief_proposals(self, brief_id, headers, params=None):
        return self._request("GET", f"/briefs/{brief_id}/proposals", headers=headers, params=params)

    # ---- Series / Episode / Opportunity ----
    def create_series(self, payload, headers):
        return self._request("POST", "/series", payload, headers)

    def get_series(self, series_id, headers):
        return self._request("GET", f"/series/{series_id}", headers=headers)

    def create_episode(self, series_id, payload, headers):
        return self._request("POST", f"/series/{series_id}/episodes", payload, headers)

    def list_series_episodes(self, series_id, headers, params=None):
        return self._request("GET", f"/series/{series_id}/episodes", headers=headers, params=params)

    def get_episode(self, episode_id, headers):
        return self._request("GET", f"/episodes/{episode_id}", headers=headers)

    def lock_episode(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/lock", headers=headers)

    def mark_episode_aired(self, episode_id, headers):
        return self._request("POST", f"/episodes/{episode_id}/mark-aired", headers=headers)

    def create_opportunity(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/opportunities", payload, headers)

    def list_episode_opportunities(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/opportunities", headers=headers, params=params)

    def get_opportunity(self, opportunity_id, headers):
        return self._request("GET", f"/opportunities/{opportunity_id}", headers=headers)

    def withdraw_opportunity(self, opportunity_id, headers):
        return self._request("POST", f"/opportunities/{opportunity_id}/withdraw", headers=headers)

    def list_opportunity_proposals(self, opportunity_id, headers, params=None):
        return self._request("GET", f"/opportunities/{opportunity_id}/proposals", headers=headers, params=params)

    # ---- Clearance ----
    def create_clearance(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/clearances", payload, headers)

    def list_episode_clearances(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/clearances", headers=headers, params=params)

    def decide_clearance(self, clearance_id, payload, headers):
        return self._request("POST", f"/clearances/{clearance_id}/decide", payload, headers)

    def release_clearance(self, clearance_id, headers):
        return self._request("POST", f"/clearances/{clearance_id}/release", headers=headers)

    # ---- Proposal ----
    def create_proposal(self, payload, headers):
        return self._request("POST", "/proposals", payload, headers)

    def get_proposal(self, proposal_id, headers):
        return self._request("GET", f"/proposals/{proposal_id}", headers=headers)

    def submit_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/submit", headers=headers)

    def production_decision(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/production-decision", payload, headers)

    def network_decision(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/network-decision", payload, headers)

    def submit_revision(self, proposal_id, payload, headers):
        return self._request("POST", f"/proposals/{proposal_id}/revisions", payload, headers)

    def withdraw_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/withdraw", headers=headers)

    def create_contract_from_proposal(self, proposal_id, headers):
        return self._request("POST", f"/proposals/{proposal_id}/contract", headers=headers)

    def list_proposal_contracts(self, proposal_id, headers, params=None):
        return self._request("GET", f"/proposals/{proposal_id}/contracts", headers=headers, params=params)

    # ---- Contract ----
    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}", headers=headers)

    def list_episode_contracts(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/contracts", headers=headers, params=params)

    def amend_contract_terms(self, contract_id, payload, headers):
        return self._request("PATCH", f"/contracts/{contract_id}/terms", payload, headers)

    def activate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/activate", headers=headers)

    def terminate_contract(self, contract_id, headers):
        return self._request("POST", f"/contracts/{contract_id}/terminate", headers=headers)

    def get_contract_ledger(self, contract_id, headers):
        return self._request("GET", f"/contracts/{contract_id}/ledger", headers=headers)

    # ---- Shipment & Continuity ----
    def create_shipment(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/shipments", payload, headers)

    def list_contract_shipments(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def advance_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/advance", payload, headers)

    def create_continuity_record(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/continuity-records", payload, headers)

    def list_contract_continuity_records(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/continuity-records", headers=headers, params=params)

    def list_shipment_continuity_records(self, shipment_id, headers, params=None):
        return self._request("GET", f"/shipments/{shipment_id}/continuity-records", headers=headers, params=params)

    # ---- Airing report / verification / makegood ----
    def create_airing_report(self, episode_id, payload, headers):
        return self._request("POST", f"/episodes/{episode_id}/airing-reports", payload, headers)

    def list_episode_airing_reports(self, episode_id, headers, params=None):
        return self._request("GET", f"/episodes/{episode_id}/airing-reports", headers=headers, params=params)

    def list_contract_airing_reports(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/airing-reports", headers=headers, params=params)

    def verify_airing_report(self, report_id, headers):
        return self._request("POST", f"/airing-reports/{report_id}/verify", headers=headers)

    def dispute_airing_report(self, report_id, headers):
        return self._request("POST", f"/airing-reports/{report_id}/dispute", headers=headers)

    def remeasure_airing_report(self, report_id, payload, headers):
        return self._request("POST", f"/airing-reports/{report_id}/remeasure", payload, headers)

    def list_contract_makegood_credits(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/makegood-credits", headers=headers, params=params)

    def waive_makegood_credit(self, credit_id, headers):
        return self._request("POST", f"/makegood-credits/{credit_id}/waive", headers=headers)

    # ---- Cross-promotion & disclosure ----
    def list_contract_cross_promos(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/cross-promos", headers=headers, params=params)

    def fulfill_cross_promo(self, cross_promo_id, headers):
        return self._request("POST", f"/cross-promos/{cross_promo_id}/fulfill", headers=headers)

    def create_disclosure(self, contract_id, payload, headers):
        return self._request("POST", f"/contracts/{contract_id}/disclosures", payload, headers)

    def list_contract_disclosures(self, contract_id, headers, params=None):
        return self._request("GET", f"/contracts/{contract_id}/disclosures", headers=headers, params=params)

    def file_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/disclosures/{disclosure_id}/file", headers=headers)

    def acknowledge_disclosure(self, disclosure_id, headers):
        return self._request("POST", f"/disclosures/{disclosure_id}/acknowledge", headers=headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
