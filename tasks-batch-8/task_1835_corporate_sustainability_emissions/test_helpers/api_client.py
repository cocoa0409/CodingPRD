"""API client: one method per endpoint defined in the PRD (§4 table)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Logical clock (PRD §2.5) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/sustainability/_clock/set_current_utc", payload, headers)

    # --- Sites (PRD §3.1) ---
    def create_site(self, payload, headers):
        return self._request("POST", "/sustainability/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sustainability/sites/{site_id}", headers=headers)

    def decommission_site(self, site_id, headers):
        return self._request("POST", f"/sustainability/sites/{site_id}/decommission", {}, headers)

    # --- Emission factors (PRD §3.1) ---
    def create_emission_factor(self, payload, headers):
        return self._request("POST", "/sustainability/emission-factors", payload, headers)

    def get_emission_factor(self, factor_id, headers):
        return self._request("GET", f"/sustainability/emission-factors/{factor_id}", headers=headers)

    def transition_emission_factor(self, factor_id, payload, headers):
        return self._request("POST", f"/sustainability/emission-factors/{factor_id}/transition", payload, headers)

    # --- Reporting cycles (PRD §3.2) ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/sustainability/cycles", payload, headers)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/sustainability/cycles/{cycle_id}", headers=headers)

    def transition_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/sustainability/cycles/{cycle_id}/transition", payload, headers)

    def recalculate_inventory(self, cycle_id, payload, headers):
        return self._request("POST", f"/sustainability/cycles/{cycle_id}/inventory/recalculate", payload, headers)

    # --- Inventory results (PRD §3.7) ---
    def get_inventory_result(self, result_id, headers):
        return self._request("GET", f"/sustainability/inventory-results/{result_id}", headers=headers)

    def list_inventory_results(self, headers, params=None):
        return self._request("GET", "/sustainability/inventory-results", headers=headers, params=params)

    # --- Activity records (PRD §3.3) ---
    def create_activity_record(self, payload, headers):
        return self._request("POST", "/sustainability/activity-records", payload, headers)

    def get_activity_record(self, record_id, headers):
        return self._request("GET", f"/sustainability/activity-records/{record_id}", headers=headers)

    def list_activity_records(self, headers, params=None):
        return self._request("GET", "/sustainability/activity-records", headers=headers, params=params)

    def transition_activity_record(self, record_id, payload, headers):
        return self._request("POST", f"/sustainability/activity-records/{record_id}/transition", payload, headers)

    # --- Evidence items (PRD §3.4) ---
    def upload_evidence(self, record_id, payload, headers):
        return self._request("POST", f"/sustainability/activity-records/{record_id}/evidence", payload, headers)

    def get_evidence_item(self, evidence_id, headers):
        return self._request("GET", f"/sustainability/evidence-items/{evidence_id}", headers=headers)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", "/sustainability/evidence-items", headers=headers, params=params)

    def transition_evidence_item(self, evidence_id, payload, headers):
        return self._request("POST", f"/sustainability/evidence-items/{evidence_id}/transition", payload, headers)

    # --- Supplier engagements (PRD §3.5) ---
    def create_supplier_engagement(self, payload, headers):
        return self._request("POST", "/sustainability/supplier-engagements", payload, headers)

    def get_supplier_engagement(self, engagement_id, headers):
        return self._request("GET", f"/sustainability/supplier-engagements/{engagement_id}", headers=headers)

    def list_supplier_engagements(self, headers, params=None):
        return self._request("GET", "/sustainability/supplier-engagements", headers=headers, params=params)

    def respond_to_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/sustainability/supplier-engagements/{engagement_id}/respond", payload, headers)

    def decide_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/sustainability/supplier-engagements/{engagement_id}/decision", payload, headers)

    # --- Emission targets (PRD §3.8) ---
    def create_target(self, payload, headers):
        return self._request("POST", "/sustainability/targets", payload, headers)

    def get_target(self, target_id, headers):
        return self._request("GET", f"/sustainability/targets/{target_id}", headers=headers)

    def list_targets(self, headers, params=None):
        return self._request("GET", "/sustainability/targets", headers=headers, params=params)

    def transition_target(self, target_id, payload, headers):
        return self._request("POST", f"/sustainability/targets/{target_id}/transition", payload, headers)

    def recalculate_baseline(self, target_id, payload, headers):
        return self._request("POST", f"/sustainability/targets/{target_id}/recalculate-baseline", payload, headers)

    # --- Renewable instruments (PRD §3.6) ---
    def create_instrument(self, payload, headers):
        return self._request("POST", "/sustainability/instruments", payload, headers)

    def get_instrument(self, instrument_id, headers):
        return self._request("GET", f"/sustainability/instruments/{instrument_id}", headers=headers)

    def list_instruments(self, headers, params=None):
        return self._request("GET", "/sustainability/instruments", headers=headers, params=params)

    def retire_instrument(self, instrument_id, payload, headers):
        return self._request("POST", f"/sustainability/instruments/{instrument_id}/retire", payload, headers)

    def void_retirement(self, instrument_id, headers):
        return self._request("POST", f"/sustainability/instruments/{instrument_id}/void-retirement", {}, headers)

    # --- Questionnaire responses (PRD §3.9) ---
    def create_questionnaire(self, payload, headers):
        return self._request("POST", "/sustainability/questionnaire-responses", payload, headers)

    def get_questionnaire(self, questionnaire_id, headers):
        return self._request("GET", f"/sustainability/questionnaire-responses/{questionnaire_id}", headers=headers)

    def list_questionnaires(self, headers, params=None):
        return self._request("GET", "/sustainability/questionnaire-responses", headers=headers, params=params)

    def answer_section(self, questionnaire_id, payload, headers):
        return self._request("POST", f"/sustainability/questionnaire-responses/{questionnaire_id}/answers", payload, headers)

    def transition_questionnaire(self, questionnaire_id, payload, headers):
        return self._request("POST", f"/sustainability/questionnaire-responses/{questionnaire_id}/transition", payload, headers)

    def review_questionnaire(self, questionnaire_id, payload, headers):
        return self._request("POST", f"/sustainability/questionnaire-responses/{questionnaire_id}/review-decision", payload, headers)


api_client = ApiClient()
