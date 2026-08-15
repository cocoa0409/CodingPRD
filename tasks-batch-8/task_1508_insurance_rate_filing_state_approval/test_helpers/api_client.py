"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Product ---
    def create_product(self, payload, headers):
        return self._request("POST", "/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    # --- StateRegulatoryProfile ---
    def create_profile(self, payload, headers):
        return self._request("POST", "/state-profiles", payload, headers)

    def get_profile(self, profile_id, headers):
        return self._request("GET", f"/state-profiles/{profile_id}", headers=headers)

    def list_profiles(self, headers, params=None):
        return self._request("GET", "/state-profiles", headers=headers, params=params)

    def suspend_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/state-profiles/{profile_id}/suspend", headers=headers
        )

    def reactivate_profile(self, profile_id, headers):
        return self._request(
            "POST", f"/state-profiles/{profile_id}/reactivate", headers=headers
        )

    # --- RateIndication ---
    def create_indication(self, payload, headers):
        return self._request("POST", "/rate-indications", payload, headers)

    def get_indication(self, indication_id, headers):
        return self._request(
            "GET", f"/rate-indications/{indication_id}", headers=headers
        )

    def list_indications(self, headers, params=None):
        return self._request("GET", "/rate-indications", headers=headers, params=params)

    def submit_indication_review(self, indication_id, headers):
        return self._request(
            "POST", f"/rate-indications/{indication_id}/submit-review", headers=headers
        )

    def approve_indication(self, indication_id, headers):
        return self._request(
            "POST", f"/rate-indications/{indication_id}/approve", headers=headers
        )

    def return_indication(self, indication_id, headers):
        return self._request(
            "POST", f"/rate-indications/{indication_id}/return", headers=headers
        )

    def lock_indication(self, indication_id, headers):
        return self._request(
            "POST", f"/rate-indications/{indication_id}/lock", headers=headers
        )

    # --- RateFiling ---
    def create_filing(self, payload, headers):
        return self._request("POST", "/filings", payload, headers)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/filings", headers=headers, params=params)

    def mark_filing_ready(self, filing_id, headers):
        return self._request(
            "POST", f"/filings/{filing_id}/mark-ready", headers=headers
        )

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/submit", headers=headers)

    def withdraw_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/withdraw", headers=headers)

    def approve_filing(self, filing_id, headers):
        return self._request("POST", f"/filings/{filing_id}/approve", headers=headers)

    def disapprove_filing(self, filing_id, headers):
        return self._request(
            "POST", f"/filings/{filing_id}/disapprove", headers=headers
        )

    def mark_filing_effective(self, filing_id, headers):
        return self._request(
            "POST", f"/filings/{filing_id}/mark-effective", headers=headers
        )

    # --- FilingComponent ---
    def create_component(self, filing_id, payload, headers):
        return self._request(
            "POST", f"/filings/{filing_id}/components", payload, headers
        )

    def get_component(self, component_id, headers):
        return self._request("GET", f"/components/{component_id}", headers=headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/components", headers=headers, params=params)

    def finalize_component(self, component_id, headers):
        return self._request(
            "POST", f"/components/{component_id}/finalize", headers=headers
        )

    # --- Deviation ---
    def create_deviation(self, payload, headers):
        return self._request("POST", "/deviations", payload, headers)

    def get_deviation(self, deviation_id, headers):
        return self._request("GET", f"/deviations/{deviation_id}", headers=headers)

    def list_deviations(self, headers, params=None):
        return self._request("GET", "/deviations", headers=headers, params=params)

    def approve_deviation(self, deviation_id, headers):
        return self._request(
            "POST", f"/deviations/{deviation_id}/approve", headers=headers
        )

    def reject_deviation(self, deviation_id, headers):
        return self._request(
            "POST", f"/deviations/{deviation_id}/reject", headers=headers
        )

    def withdraw_deviation(self, deviation_id, headers):
        return self._request(
            "POST", f"/deviations/{deviation_id}/withdraw", headers=headers
        )

    # --- Objection / ObjectionResponse ---
    def create_objection(self, payload, headers):
        return self._request("POST", "/objections", payload, headers)

    def get_objection(self, objection_id, headers):
        return self._request("GET", f"/objections/{objection_id}", headers=headers)

    def list_objections(self, headers, params=None):
        return self._request("GET", "/objections", headers=headers, params=params)

    def draft_response(self, objection_id, payload, headers):
        return self._request(
            "POST", f"/objections/{objection_id}/responses", payload, headers
        )

    def get_response(self, response_id, headers):
        return self._request("GET", f"/responses/{response_id}", headers=headers)

    def list_responses(self, headers, params=None):
        return self._request("GET", "/responses", headers=headers, params=params)

    def submit_response(self, response_id, headers):
        return self._request(
            "POST", f"/responses/{response_id}/submit", headers=headers
        )

    def resolve_objection(self, objection_id, headers):
        return self._request(
            "POST", f"/objections/{objection_id}/resolve", headers=headers
        )

    def reopen_objection(self, objection_id, headers):
        return self._request(
            "POST", f"/objections/{objection_id}/reopen", headers=headers
        )

    def withdraw_objection(self, objection_id, headers):
        return self._request(
            "POST", f"/objections/{objection_id}/withdraw", headers=headers
        )

    # --- ImplementationWave ---
    def create_wave(self, payload, headers):
        return self._request("POST", "/waves", payload, headers)

    def get_wave(self, wave_id, headers):
        return self._request("GET", f"/waves/{wave_id}", headers=headers)

    def list_waves(self, headers, params=None):
        return self._request("GET", "/waves", headers=headers, params=params)

    def release_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/release", headers=headers)

    def reverse_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/reverse", headers=headers)

    def cancel_wave(self, wave_id, headers):
        return self._request("POST", f"/waves/{wave_id}/cancel", headers=headers)

    def get_disruption_analysis(self, wave_id, headers):
        return self._request(
            "GET", f"/waves/{wave_id}/disruption-analysis", headers=headers
        )

    # --- RenewalPolicy ---
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/policies", headers=headers, params=params)

    def send_policy_notice(self, policy_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/send-notice", headers=headers
        )

    def complete_policy_renewal(self, policy_id, headers):
        return self._request(
            "POST", f"/policies/{policy_id}/complete-renewal", headers=headers
        )

    # --- ComplianceCalendarEntry ---
    def get_calendar_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/calendar-entries/{entry_id}", headers=headers
        )

    def list_calendar_entries(self, headers, params=None):
        return self._request(
            "GET", "/calendar-entries", headers=headers, params=params
        )

    def waive_calendar_entry(self, entry_id, headers):
        return self._request(
            "POST", f"/calendar-entries/{entry_id}/waive", headers=headers
        )


api_client = ApiClient()
