"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CapTable ----
    def create_cap_table(self, payload, headers):
        return self._request("POST", "/cap-tables", payload, headers)

    def get_cap_table(self, cap_table_id, headers):
        return self._request("GET", f"/cap-tables/{cap_table_id}", headers=headers)

    def list_cap_tables(self, headers, params=None):
        return self._request("GET", "/cap-tables", headers=headers, params=params)

    def lock_cap_table(self, cap_table_id, payload, headers):
        return self._request("POST", f"/cap-tables/{cap_table_id}/lock", payload, headers)

    def unlock_cap_table(self, cap_table_id, payload, headers):
        return self._request("POST", f"/cap-tables/{cap_table_id}/unlock", payload, headers)

    def dissolve_cap_table(self, cap_table_id, headers):
        return self._request("POST", f"/cap-tables/{cap_table_id}/dissolve", {}, headers)

    # ---- SecurityClass ----
    def create_security_class(self, payload, headers):
        return self._request("POST", "/security-classes", payload, headers)

    def get_security_class(self, security_class_id, headers):
        return self._request("GET", f"/security-classes/{security_class_id}", headers=headers)

    def list_security_classes(self, headers, params=None):
        return self._request("GET", "/security-classes", headers=headers, params=params)

    # ---- Shareholder ----
    def create_shareholder(self, payload, headers):
        return self._request("POST", "/shareholders", payload, headers)

    def get_shareholder(self, shareholder_id, headers):
        return self._request("GET", f"/shareholders/{shareholder_id}", headers=headers)

    def list_shareholders(self, headers, params=None):
        return self._request("GET", "/shareholders", headers=headers, params=params)

    # ---- ShareIssuance ----
    def create_share_issuance(self, payload, headers):
        return self._request("POST", "/share-issuances", payload, headers)

    def get_share_issuance(self, issuance_id, headers):
        return self._request("GET", f"/share-issuances/{issuance_id}", headers=headers)

    def list_share_issuances(self, headers, params=None):
        return self._request("GET", "/share-issuances", headers=headers, params=params)

    # ---- Valuation ----
    def create_valuation(self, payload, headers):
        return self._request("POST", "/valuations", payload, headers)

    def get_valuation(self, valuation_id, headers):
        return self._request("GET", f"/valuations/{valuation_id}", headers=headers)

    def list_valuations(self, headers, params=None):
        return self._request("GET", "/valuations", headers=headers, params=params)

    def approve_valuation(self, valuation_id, headers):
        return self._request("POST", f"/valuations/{valuation_id}/approve", {}, headers)

    # ---- OptionPool ----
    def create_option_pool(self, payload, headers):
        return self._request("POST", "/option-pools", payload, headers)

    def get_option_pool(self, pool_id, headers):
        return self._request("GET", f"/option-pools/{pool_id}", headers=headers)

    def list_option_pools(self, headers, params=None):
        return self._request("GET", "/option-pools", headers=headers, params=params)

    def refresh_option_pool(self, pool_id, payload, headers):
        return self._request("POST", f"/option-pools/{pool_id}/refresh", payload, headers)

    # ---- OptionGrant ----
    def create_option_grant(self, payload, headers):
        return self._request("POST", "/option-grants", payload, headers)

    def get_option_grant(self, grant_id, headers):
        return self._request("GET", f"/option-grants/{grant_id}", headers=headers)

    def list_option_grants(self, headers, params=None):
        return self._request("GET", "/option-grants", headers=headers, params=params)

    def approve_option_grant(self, grant_id, headers):
        return self._request("POST", f"/option-grants/{grant_id}/approve", {}, headers)

    def cancel_option_grant(self, grant_id, headers):
        return self._request("POST", f"/option-grants/{grant_id}/cancel", {}, headers)

    def expire_option_grant(self, grant_id, headers):
        return self._request("POST", f"/option-grants/{grant_id}/expire", {}, headers)

    # ---- Exercise ----
    def create_exercise(self, payload, headers):
        return self._request("POST", "/exercises", payload, headers)

    def get_exercise(self, exercise_id, headers):
        return self._request("GET", f"/exercises/{exercise_id}", headers=headers)

    def list_exercises(self, headers, params=None):
        return self._request("GET", "/exercises", headers=headers, params=params)

    def settle_exercise(self, exercise_id, headers):
        return self._request("POST", f"/exercises/{exercise_id}/settle", {}, headers)

    def reverse_exercise(self, exercise_id, headers):
        return self._request("POST", f"/exercises/{exercise_id}/reverse", {}, headers)

    def generate_form_3921(self, exercise_id, headers):
        return self._request("POST", f"/exercises/{exercise_id}/form-3921", {}, headers)

    # ---- Form3921 ----
    def get_form_3921(self, form_id, headers):
        return self._request("GET", f"/forms-3921/{form_id}", headers=headers)

    def list_forms_3921(self, headers, params=None):
        return self._request("GET", "/forms-3921", headers=headers, params=params)

    # ---- Section83bElection ----
    def create_section_83b_election(self, payload, headers):
        return self._request("POST", "/section-83b-elections", payload, headers)

    def get_section_83b_election(self, election_id, headers):
        return self._request("GET", f"/section-83b-elections/{election_id}", headers=headers)

    def list_section_83b_elections(self, headers, params=None):
        return self._request("GET", "/section-83b-elections", headers=headers, params=params)

    def process_section_83b_election(self, election_id, headers):
        return self._request("POST", f"/section-83b-elections/{election_id}/process", {}, headers)

    # ---- SafeNote ----
    def create_safe_note(self, payload, headers):
        return self._request("POST", "/safe-notes", payload, headers)

    def get_safe_note(self, note_id, headers):
        return self._request("GET", f"/safe-notes/{note_id}", headers=headers)

    def list_safe_notes(self, headers, params=None):
        return self._request("GET", "/safe-notes", headers=headers, params=params)

    def submit_terms_safe_note(self, note_id, headers):
        return self._request("POST", f"/safe-notes/{note_id}/submit-terms", {}, headers)

    def revise_safe_note(self, note_id, headers):
        return self._request("POST", f"/safe-notes/{note_id}/revise", {}, headers)

    def execute_safe_note(self, note_id, headers):
        return self._request("POST", f"/safe-notes/{note_id}/execute", {}, headers)

    def convert_safe_note(self, note_id, payload, headers):
        return self._request("POST", f"/safe-notes/{note_id}/convert", payload, headers)

    def repay_safe_note(self, note_id, headers):
        return self._request("POST", f"/safe-notes/{note_id}/repay", {}, headers)

    # ---- LiquidationEvent / Waterfall ----
    def create_liquidation_event(self, payload, headers):
        return self._request("POST", "/liquidation-events", payload, headers)

    def get_liquidation_event(self, event_id, headers):
        return self._request("GET", f"/liquidation-events/{event_id}", headers=headers)

    def list_liquidation_events(self, headers, params=None):
        return self._request("GET", "/liquidation-events", headers=headers, params=params)

    def compute_liquidation_event(self, event_id, headers):
        return self._request("POST", f"/liquidation-events/{event_id}/compute", {}, headers)

    def recompute_liquidation_event(self, event_id, headers):
        return self._request("POST", f"/liquidation-events/{event_id}/recompute", {}, headers)

    def finalize_liquidation_event(self, event_id, headers):
        return self._request("POST", f"/liquidation-events/{event_id}/finalize", {}, headers)

    def list_event_distributions(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/liquidation-events/{event_id}/distributions", headers=headers, params=params
        )

    def get_waterfall_distribution(self, distribution_id, headers):
        return self._request("GET", f"/waterfall-distributions/{distribution_id}", headers=headers)

    def list_waterfall_distributions(self, headers, params=None):
        return self._request("GET", "/waterfall-distributions", headers=headers, params=params)

    # ---- BlackoutWindow ----
    def create_blackout_window(self, payload, headers):
        return self._request("POST", "/blackout-windows", payload, headers)

    def get_blackout_window(self, window_id, headers):
        return self._request("GET", f"/blackout-windows/{window_id}", headers=headers)

    def list_blackout_windows(self, headers, params=None):
        return self._request("GET", "/blackout-windows", headers=headers, params=params)

    def lift_blackout_window(self, window_id, headers):
        return self._request("POST", f"/blackout-windows/{window_id}/lift", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
