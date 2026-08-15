"""API client: one method per endpoint defined in the PRD endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Assessment programs
    # ------------------------------------------------------------------
    def create_assessment_program(self, payload, headers):
        return self._request("POST", "/api/assessment-programs", payload, headers)

    def list_assessment_programs(self, headers, params=None):
        return self._request("GET", "/api/assessment-programs", headers=headers, params=params)

    def get_assessment_program(self, program_id, headers):
        return self._request("GET", f"/api/assessment-programs/{program_id}", headers=headers)

    def advance_clock(self, program_id, by_seconds, headers):
        return self._request("POST", f"/api/assessment-programs/{program_id}/clock/advance",
                             {"by_seconds": by_seconds}, headers)

    # ------------------------------------------------------------------
    # Content standards
    # ------------------------------------------------------------------
    def create_content_standard(self, payload, headers):
        return self._request("POST", "/api/content-standards", payload, headers)

    def list_content_standards(self, headers, params=None):
        return self._request("GET", "/api/content-standards", headers=headers, params=params)

    def get_content_standard(self, standard_id, headers):
        return self._request("GET", f"/api/content-standards/{standard_id}", headers=headers)

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------
    def create_item(self, payload, headers):
        return self._request("POST", "/api/items", payload, headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/api/items", headers=headers, params=params)

    def get_item(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}", headers=headers)

    def update_item(self, item_id, payload, headers):
        return self._request("PUT", f"/api/items/{item_id}", payload, headers)

    def submit_item(self, item_id, expected_item_version, headers):
        return self._request("POST", f"/api/items/{item_id}/submit",
                             {"expected_item_version": expected_item_version}, headers)

    def discard_item(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/discard", {}, headers)

    def approve_operational_item(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/approve-operational", {}, headers)

    def retire_item(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/retire", {}, headers)

    def mark_item_compromised(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/mark-compromised", {}, headers)

    # ------------------------------------------------------------------
    # Item variants
    # ------------------------------------------------------------------
    def create_item_variant(self, payload, headers):
        return self._request("POST", "/api/item-variants", payload, headers)

    def list_item_variants(self, headers, params=None):
        return self._request("GET", "/api/item-variants", headers=headers, params=params)

    def get_item_variant(self, variant_id, headers):
        return self._request("GET", f"/api/item-variants/{variant_id}", headers=headers)

    def approve_item_variant(self, variant_id, headers):
        return self._request("POST", f"/api/item-variants/{variant_id}/approve", {}, headers)

    def reject_item_variant(self, variant_id, headers):
        return self._request("POST", f"/api/item-variants/{variant_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Review committees
    # ------------------------------------------------------------------
    def create_review_committee(self, payload, headers):
        return self._request("POST", "/api/review-committees", payload, headers)

    def list_review_committees(self, headers, params=None):
        return self._request("GET", "/api/review-committees", headers=headers, params=params)

    def get_review_committee(self, committee_id, headers):
        return self._request("GET", f"/api/review-committees/{committee_id}", headers=headers)

    # ------------------------------------------------------------------
    # Review sessions
    # ------------------------------------------------------------------
    def create_review_session(self, payload, headers):
        return self._request("POST", "/api/review-sessions", payload, headers)

    def list_review_sessions(self, headers, params=None):
        return self._request("GET", "/api/review-sessions", headers=headers, params=params)

    def get_review_session(self, session_id, headers):
        return self._request("GET", f"/api/review-sessions/{session_id}", headers=headers)

    def open_review_session(self, session_id, headers):
        return self._request("POST", f"/api/review-sessions/{session_id}/open", {}, headers)

    def close_review_session(self, session_id, headers):
        return self._request("POST", f"/api/review-sessions/{session_id}/close", {}, headers)

    def cancel_review_session(self, session_id, headers):
        return self._request("POST", f"/api/review-sessions/{session_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Review verdicts
    # ------------------------------------------------------------------
    def submit_verdict(self, session_id, payload, headers):
        return self._request("POST", f"/api/review-sessions/{session_id}/verdicts", payload, headers)

    def list_review_verdicts(self, headers, params=None):
        return self._request("GET", "/api/review-verdicts", headers=headers, params=params)

    def get_review_verdict(self, verdict_id, headers):
        return self._request("GET", f"/api/review-verdicts/{verdict_id}", headers=headers)

    # ------------------------------------------------------------------
    # Field test windows
    # ------------------------------------------------------------------
    def create_field_test_window(self, payload, headers):
        return self._request("POST", "/api/field-test-windows", payload, headers)

    def list_field_test_windows(self, headers, params=None):
        return self._request("GET", "/api/field-test-windows", headers=headers, params=params)

    def get_field_test_window(self, window_id, headers):
        return self._request("GET", f"/api/field-test-windows/{window_id}", headers=headers)

    def open_field_test_window(self, window_id, headers):
        return self._request("POST", f"/api/field-test-windows/{window_id}/open", {}, headers)

    def close_field_test_window(self, window_id, headers):
        return self._request("POST", f"/api/field-test-windows/{window_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Item responses
    # ------------------------------------------------------------------
    def ingest_item_response(self, window_id, payload, headers):
        return self._request("POST", f"/api/field-test-windows/{window_id}/responses",
                             payload, headers)

    def list_item_responses(self, headers, params=None):
        return self._request("GET", "/api/item-responses", headers=headers, params=params)

    def get_item_response(self, response_id, headers):
        return self._request("GET", f"/api/item-responses/{response_id}", headers=headers)

    def exclude_item_response(self, response_id, headers):
        return self._request("POST", f"/api/item-responses/{response_id}/exclude", {}, headers)

    # ------------------------------------------------------------------
    # Item statistics
    # ------------------------------------------------------------------
    def list_item_statistics(self, headers, params=None):
        return self._request("GET", "/api/item-statistics", headers=headers, params=params)

    def get_item_statistic(self, statistic_id, headers):
        return self._request("GET", f"/api/item-statistics/{statistic_id}", headers=headers)

    # ------------------------------------------------------------------
    # Test blueprints
    # ------------------------------------------------------------------
    def create_test_blueprint(self, payload, headers):
        return self._request("POST", "/api/test-blueprints", payload, headers)

    def list_test_blueprints(self, headers, params=None):
        return self._request("GET", "/api/test-blueprints", headers=headers, params=params)

    def get_test_blueprint(self, blueprint_id, headers):
        return self._request("GET", f"/api/test-blueprints/{blueprint_id}", headers=headers)

    def lock_test_blueprint(self, blueprint_id, headers):
        return self._request("POST", f"/api/test-blueprints/{blueprint_id}/lock", {}, headers)

    def supersede_test_blueprint(self, blueprint_id, headers):
        return self._request("POST", f"/api/test-blueprints/{blueprint_id}/supersede", {}, headers)

    # ------------------------------------------------------------------
    # Test forms
    # ------------------------------------------------------------------
    def create_test_form(self, payload, headers):
        return self._request("POST", "/api/test-forms", payload, headers)

    def list_test_forms(self, headers, params=None):
        return self._request("GET", "/api/test-forms", headers=headers, params=params)

    def get_test_form(self, form_id, headers):
        return self._request("GET", f"/api/test-forms/{form_id}", headers=headers)

    def assemble_test_form(self, form_id, expected_form_version, headers):
        return self._request("POST", f"/api/test-forms/{form_id}/assemble",
                             {"expected_form_version": expected_form_version}, headers)

    def publish_test_form(self, form_id, headers):
        return self._request("POST", f"/api/test-forms/{form_id}/publish", {}, headers)

    def archive_test_form(self, form_id, headers):
        return self._request("POST", f"/api/test-forms/{form_id}/archive", {}, headers)

    # ------------------------------------------------------------------
    # Form item slots
    # ------------------------------------------------------------------
    def add_form_item_slot(self, form_id, payload, headers):
        return self._request("POST", f"/api/test-forms/{form_id}/slots", payload, headers)

    def list_form_item_slots(self, headers, params=None):
        return self._request("GET", "/api/form-item-slots", headers=headers, params=params)

    def get_form_item_slot(self, slot_id, headers):
        return self._request("GET", f"/api/form-item-slots/{slot_id}", headers=headers)

    def delete_form_item_slot(self, slot_id, headers):
        return self._request("DELETE", f"/api/form-item-slots/{slot_id}", headers=headers)

    # ------------------------------------------------------------------
    # Equating links
    # ------------------------------------------------------------------
    def create_equating_link(self, payload, headers):
        return self._request("POST", "/api/equating-links", payload, headers)

    def list_equating_links(self, headers, params=None):
        return self._request("GET", "/api/equating-links", headers=headers, params=params)

    def get_equating_link(self, link_id, headers):
        return self._request("GET", f"/api/equating-links/{link_id}", headers=headers)

    # ------------------------------------------------------------------
    # Access grants
    # ------------------------------------------------------------------
    def create_access_grant(self, payload, headers):
        return self._request("POST", "/api/access-grants", payload, headers)

    def list_access_grants(self, headers, params=None):
        return self._request("GET", "/api/access-grants", headers=headers, params=params)

    def get_access_grant(self, grant_id, headers):
        return self._request("GET", f"/api/access-grants/{grant_id}", headers=headers)

    def revoke_access_grant(self, grant_id, headers):
        return self._request("POST", f"/api/access-grants/{grant_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Validity dossiers
    # ------------------------------------------------------------------
    def create_validity_dossier(self, payload, headers):
        return self._request("POST", "/api/validity-dossiers", payload, headers)

    def list_validity_dossiers(self, headers, params=None):
        return self._request("GET", "/api/validity-dossiers", headers=headers, params=params)

    def get_validity_dossier(self, dossier_id, headers):
        return self._request("GET", f"/api/validity-dossiers/{dossier_id}", headers=headers)

    def publish_validity_dossier(self, dossier_id, headers):
        return self._request("POST", f"/api/validity-dossiers/{dossier_id}/publish", {}, headers)

    def supersede_validity_dossier(self, dossier_id, headers):
        return self._request("POST", f"/api/validity-dossiers/{dossier_id}/supersede", {}, headers)


api_client = ApiClient()
