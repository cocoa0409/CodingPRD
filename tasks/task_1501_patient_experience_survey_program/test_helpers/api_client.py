"""API client: one method per endpoint defined in the PRD (§4).

All resource collections are mounted under /api; only the logical-clock
control lives at the server root (PRD §2: "the only capability mounted
elsewhere is the logical-clock control described in §2.4").
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- programs ---
    def create_program(self, payload, headers):
        return self._request("POST", "/api/survey-programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request(
            "GET", f"/api/survey-programs/{program_id}", headers=headers
        )

    # --- vendors ---
    def create_vendor(self, payload, headers):
        return self._request("POST", "/api/vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/api/vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/api/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request(
            "POST", f"/api/vendors/{vendor_id}/suspend", headers=headers
        )

    # --- care units ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/api/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/api/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/api/units/{unit_id}", headers=headers)

    # --- providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/api/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/api/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/api/providers/{provider_id}", headers=headers)

    # --- discharges ---
    def create_discharge(self, payload, headers):
        return self._request("POST", "/api/discharges", payload, headers)

    def import_discharges(self, payload, headers):
        return self._request("POST", "/api/discharges/import", payload, headers)

    def list_discharges(self, headers, params=None):
        return self._request("GET", "/api/discharges", headers=headers, params=params)

    def get_discharge(self, discharge_id, headers):
        return self._request(
            "GET", f"/api/discharges/{discharge_id}", headers=headers
        )

    def evaluate_discharge(self, discharge_id, payload, headers):
        return self._request(
            "POST", f"/api/discharges/{discharge_id}/evaluate", payload, headers
        )

    # --- cycles ---
    def create_cycle(self, payload, headers):
        return self._request("POST", "/api/cycles", payload, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/api/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/cycles/{cycle_id}", headers=headers)

    def open_sampling(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/open-sampling", headers=headers
        )

    def start_fielding(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/start-fielding", headers=headers
        )

    def close_fielding(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/close-fielding", headers=headers
        )

    def reopen_fielding(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/reopen-fielding", headers=headers
        )

    def begin_scoring(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/begin-scoring", headers=headers
        )

    def publish_cycle(self, cycle_id, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/publish", headers=headers
        )

    def void_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/cycles/{cycle_id}/void", headers=headers)

    def get_star_rating(self, cycle_id, headers):
        return self._request(
            "GET", f"/api/cycles/{cycle_id}/star-rating", headers=headers
        )

    def get_attribution_report(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/api/cycles/{cycle_id}/attribution-report",
            headers=headers, params=params,
        )

    def create_vbp_projection(self, cycle_id, payload, headers):
        return self._request(
            "POST", f"/api/cycles/{cycle_id}/vbp-projection", payload, headers
        )

    def get_mode_transition_analysis(self, cycle_id, headers, params=None):
        return self._request(
            "GET", f"/api/cycles/{cycle_id}/mode-transition-analysis",
            headers=headers, params=params,
        )

    # --- sample cases ---
    def create_sample_case(self, payload, headers):
        return self._request("POST", "/api/sample-cases", payload, headers)

    def import_sample_cases(self, payload, headers):
        return self._request("POST", "/api/sample-cases/import", payload, headers)

    def list_sample_cases(self, headers, params=None):
        return self._request(
            "GET", "/api/sample-cases", headers=headers, params=params
        )

    def get_sample_case(self, case_id, headers):
        return self._request("GET", f"/api/sample-cases/{case_id}", headers=headers)

    def list_case_responses(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/sample-cases/{case_id}/responses",
            headers=headers, params=params,
        )

    def mark_undeliverable(self, case_id, headers):
        return self._request(
            "POST", f"/api/sample-cases/{case_id}/mark-undeliverable",
            headers=headers,
        )

    # --- responses ---
    def create_response(self, payload, headers):
        return self._request("POST", "/api/responses", payload, headers)

    def import_responses(self, payload, headers):
        return self._request("POST", "/api/responses/import", payload, headers)

    def list_responses(self, headers, params=None):
        return self._request("GET", "/api/responses", headers=headers, params=params)

    def get_response(self, response_id, headers):
        return self._request("GET", f"/api/responses/{response_id}", headers=headers)

    def adjudicate_response(self, response_id, payload, headers):
        return self._request(
            "POST", f"/api/responses/{response_id}/adjudicate", payload, headers
        )

    def void_response(self, response_id, payload, headers):
        return self._request(
            "POST", f"/api/responses/{response_id}/void", payload, headers
        )

    # --- improvement initiatives ---
    def create_initiative(self, payload, headers):
        return self._request("POST", "/api/initiatives", payload, headers)

    def list_initiatives(self, headers, params=None):
        return self._request("GET", "/api/initiatives", headers=headers, params=params)

    def get_initiative(self, initiative_id, headers):
        return self._request(
            "GET", f"/api/initiatives/{initiative_id}", headers=headers
        )

    def activate_initiative(self, initiative_id, headers):
        return self._request(
            "POST", f"/api/initiatives/{initiative_id}/activate", headers=headers
        )

    def replan_initiative(self, initiative_id, payload, headers):
        return self._request(
            "POST", f"/api/initiatives/{initiative_id}/replan", payload, headers
        )

    def cancel_initiative(self, initiative_id, headers):
        return self._request(
            "POST", f"/api/initiatives/{initiative_id}/cancel", headers=headers
        )

    # --- service recovery tickets ---
    def create_ticket(self, payload, headers):
        return self._request("POST", "/api/service-recovery-tickets", payload, headers)

    def list_tickets(self, headers, params=None):
        return self._request(
            "GET", "/api/service-recovery-tickets", headers=headers, params=params
        )

    def get_ticket(self, ticket_id, headers):
        return self._request(
            "GET", f"/api/service-recovery-tickets/{ticket_id}", headers=headers
        )

    def acknowledge_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/api/service-recovery-tickets/{ticket_id}/acknowledge",
            headers=headers,
        )

    def resolve_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"/api/service-recovery-tickets/{ticket_id}/resolve",
            payload, headers,
        )

    # --- logical clock (mounted at server root, PRD §2.4 / §4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
