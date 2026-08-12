"""API client: one method per endpoint defined in the PRD's endpoint table."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/econsult"


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- specialty tracks ---
    def create_specialty_track(self, payload, headers):
        return self._request("POST", f"{PREFIX}/specialty-tracks", payload, headers)

    def get_specialty_track(self, track_id, headers):
        return self._request("GET", f"{PREFIX}/specialty-tracks/{track_id}", headers=headers)

    # --- referring providers ---
    def create_referring_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/referring-providers", payload, headers)

    def get_referring_provider(self, provider_id, headers):
        return self._request("GET", f"{PREFIX}/referring-providers/{provider_id}", headers=headers)

    # --- specialists ---
    def create_specialist(self, payload, headers):
        return self._request("POST", f"{PREFIX}/specialists", payload, headers)

    def get_specialist(self, specialist_id, headers):
        return self._request("GET", f"{PREFIX}/specialists/{specialist_id}", headers=headers)

    def list_specialist_responses(self, specialist_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/specialists/{specialist_id}/consult-responses",
            headers=headers, params=params,
        )

    # --- panel memberships ---
    def create_panel_membership(self, payload, headers):
        return self._request("POST", f"{PREFIX}/panel-memberships", payload, headers)

    def list_panel_memberships(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/panel-memberships", headers=headers, params=params)

    def get_panel_membership(self, membership_id, headers):
        return self._request("GET", f"{PREFIX}/panel-memberships/{membership_id}", headers=headers)

    def reinstate_membership(self, membership_id, headers):
        return self._request(
            "POST", f"{PREFIX}/panel-memberships/{membership_id}/reinstate", headers=headers
        )

    def get_compensation_summary(self, membership_id, headers):
        return self._request(
            "GET", f"{PREFIX}/panel-memberships/{membership_id}/compensation-summary",
            headers=headers,
        )

    def list_membership_windows(self, membership_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/panel-memberships/{membership_id}/availability-windows",
            headers=headers, params=params,
        )

    # --- availability windows ---
    def create_availability_window(self, payload, headers):
        return self._request("POST", f"{PREFIX}/specialist-availability-windows", payload, headers)

    def cancel_availability_window(self, window_id, headers):
        return self._request(
            "POST", f"{PREFIX}/specialist-availability-windows/{window_id}/cancel", headers=headers
        )

    # --- consult requests ---
    def create_consult_request(self, payload, headers):
        return self._request("POST", f"{PREFIX}/consult-requests", payload, headers)

    def list_consult_requests(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/consult-requests", headers=headers, params=params)

    def get_consult_request(self, consult_id, headers):
        return self._request("GET", f"{PREFIX}/consult-requests/{consult_id}", headers=headers)

    def patch_consult_request(self, consult_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/consult-requests/{consult_id}", payload, headers)

    def reroute_consult(self, consult_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-requests/{consult_id}/reroute", payload, headers
        )

    def cancel_consult(self, consult_id, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-requests/{consult_id}/cancel", headers=headers
        )

    def close_consult(self, consult_id, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-requests/{consult_id}/close", headers=headers
        )

    def create_clarification(self, consult_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-requests/{consult_id}/clarifications", payload, headers
        )

    def list_clarifications(self, consult_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/consult-requests/{consult_id}/clarifications",
            headers=headers, params=params,
        )

    def list_routing_decisions(self, consult_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/consult-requests/{consult_id}/routing-decisions",
            headers=headers, params=params,
        )

    # --- consult responses ---
    def create_response(self, consult_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-requests/{consult_id}/responses", payload, headers
        )

    def list_consult_responses(self, consult_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/consult-requests/{consult_id}/responses",
            headers=headers, params=params,
        )

    def get_consult_response(self, response_id, headers):
        return self._request("GET", f"{PREFIX}/consult-responses/{response_id}", headers=headers)

    def mark_documentation(self, response_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-responses/{response_id}/documentation", payload, headers
        )

    def finalize_response(self, response_id, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-responses/{response_id}/finalize", headers=headers
        )

    def revise_response(self, response_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-responses/{response_id}/revise", payload, headers
        )

    # --- quality reviews ---
    def create_quality_review(self, payload, headers):
        return self._request("POST", f"{PREFIX}/quality-reviews", payload, headers)

    def complete_quality_review(self, review_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/quality-reviews/{review_id}/complete", payload, headers
        )

    def list_quality_reviews(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/quality-reviews", headers=headers, params=params)

    def get_quality_review(self, review_id, headers):
        return self._request("GET", f"{PREFIX}/quality-reviews/{review_id}", headers=headers)

    # --- in-person conversions ---
    def create_conversion(self, consult_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-requests/{consult_id}/conversions", payload, headers
        )

    def complete_conversion(self, conversion_id, headers):
        return self._request(
            "POST", f"{PREFIX}/in-person-conversions/{conversion_id}/complete", headers=headers
        )

    def cancel_conversion(self, conversion_id, headers):
        return self._request(
            "POST", f"{PREFIX}/in-person-conversions/{conversion_id}/cancel", headers=headers
        )

    def list_conversions(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/in-person-conversions", headers=headers, params=params
        )

    def get_conversion(self, conversion_id, headers):
        return self._request(
            "GET", f"{PREFIX}/in-person-conversions/{conversion_id}", headers=headers
        )

    # --- billing claims ---
    def create_billing_claim(self, consult_id, headers):
        return self._request(
            "POST", f"{PREFIX}/consult-requests/{consult_id}/billing-claims", {}, headers
        )

    def list_consult_claims(self, consult_id, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/consult-requests/{consult_id}/billing-claims",
            headers=headers, params=params,
        )

    def get_billing_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/billing-claims/{claim_id}", headers=headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/billing-claims/{claim_id}/submit", headers=headers)

    def mark_claim_paid(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-claims/{claim_id}/mark-paid", headers=headers
        )

    def deny_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/billing-claims/{claim_id}/deny", headers=headers)

    def write_off_claim(self, claim_id, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-claims/{claim_id}/write-off", headers=headers
        )

    # --- compensation ledger ---
    def list_compensation_entries(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/compensation-entries", headers=headers, params=params
        )

    def get_compensation_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/compensation-entries/{entry_id}", headers=headers)

    # --- avoided-visit measurements ---
    def create_measurement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/avoided-visit-measurements", payload, headers)

    def finalize_measurement(self, measurement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/avoided-visit-measurements/{measurement_id}/finalize",
            headers=headers,
        )

    def list_measurements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/avoided-visit-measurements", headers=headers, params=params
        )

    def get_measurement(self, measurement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/avoided-visit-measurements/{measurement_id}", headers=headers
        )


api_client = ApiClient()
