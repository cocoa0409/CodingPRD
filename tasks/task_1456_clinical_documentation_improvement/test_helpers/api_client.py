"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- CDI Programs ---
    def create_cdi_program(self, payload, headers):
        return self._request("POST", "/api/cdi-programs", payload, headers)

    def list_cdi_programs(self, headers, params=None):
        return self._request("GET", "/api/cdi-programs", headers=headers, params=params)

    def get_cdi_program(self, program_id, headers):
        return self._request("GET", f"/api/cdi-programs/{program_id}", headers=headers)

    def suspend_cdi_program(self, program_id, headers):
        return self._request("POST", f"/api/cdi-programs/{program_id}/suspend", {}, headers)

    def resume_cdi_program(self, program_id, headers):
        return self._request("POST", f"/api/cdi-programs/{program_id}/resume", {}, headers)

    def close_cdi_program(self, program_id, headers):
        return self._request("POST", f"/api/cdi-programs/{program_id}/close", {}, headers)

    def advance_clock(self, program_id, by_periods, headers):
        return self._request(
            "POST",
            f"/api/cdi-programs/{program_id}/clock/advance",
            {"by_periods": by_periods},
            headers,
        )

    def list_program_cmi_snapshots(self, program_id, headers, params=None):
        return self._request(
            "GET", f"/api/cdi-programs/{program_id}/cmi-snapshots", headers=headers, params=params
        )

    def create_cmi_snapshot(self, program_id, headers):
        return self._request("POST", f"/api/cdi-programs/{program_id}/cmi-snapshots", {}, headers)

    # --- Escalation Policies ---
    def create_escalation_policy(self, payload, headers):
        return self._request("POST", "/api/escalation-policies", payload, headers)

    def list_escalation_policies(self, headers, params=None):
        return self._request("GET", "/api/escalation-policies", headers=headers, params=params)

    def get_escalation_policy(self, policy_id, headers):
        return self._request("GET", f"/api/escalation-policies/{policy_id}", headers=headers)

    def update_escalation_policy(self, policy_id, payload, headers):
        return self._request("PUT", f"/api/escalation-policies/{policy_id}", payload, headers)

    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", "/api/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", "/api/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"/api/providers/{provider_id}", headers=headers)

    def list_provider_education_events(self, provider_id, headers, params=None):
        return self._request(
            "GET", f"/api/providers/{provider_id}/education-events", headers=headers, params=params
        )

    # --- Patient Cases ---
    def create_patient_case(self, payload, headers):
        return self._request("POST", "/api/patient-cases", payload, headers)

    def list_patient_cases(self, headers, params=None):
        return self._request("GET", "/api/patient-cases", headers=headers, params=params)

    def get_patient_case(self, case_id, headers):
        return self._request("GET", f"/api/patient-cases/{case_id}", headers=headers)

    def list_case_reviews(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/patient-cases/{case_id}/reviews", headers=headers, params=params
        )

    def list_case_reconciliations(self, case_id, headers, params=None):
        return self._request(
            "GET", f"/api/patient-cases/{case_id}/reconciliations", headers=headers, params=params
        )

    def finalize_coding(self, case_id, payload, headers):
        return self._request(
            "POST", f"/api/patient-cases/{case_id}/finalize-coding", payload, headers
        )

    def close_patient_case(self, case_id, headers):
        return self._request("POST", f"/api/patient-cases/{case_id}/close", {}, headers)

    # --- CDI Reviews ---
    def create_cdi_review(self, payload, headers):
        return self._request("POST", "/api/cdi-reviews", payload, headers)

    def list_cdi_reviews(self, headers, params=None):
        return self._request("GET", "/api/cdi-reviews", headers=headers, params=params)

    def get_cdi_review(self, review_id, headers):
        return self._request("GET", f"/api/cdi-reviews/{review_id}", headers=headers)

    def list_review_queries(self, review_id, headers, params=None):
        return self._request(
            "GET", f"/api/cdi-reviews/{review_id}/queries", headers=headers, params=params
        )

    def activate_cdi_review(self, review_id, headers):
        return self._request("POST", f"/api/cdi-reviews/{review_id}/activate", {}, headers)

    def hold_cdi_review(self, review_id, headers):
        return self._request("POST", f"/api/cdi-reviews/{review_id}/hold", {}, headers)

    def resume_cdi_review(self, review_id, headers):
        return self._request("POST", f"/api/cdi-reviews/{review_id}/resume", {}, headers)

    def close_cdi_review(self, review_id, payload, headers):
        return self._request("POST", f"/api/cdi-reviews/{review_id}/close", payload, headers)

    # --- CDI Queries ---
    def create_cdi_query(self, payload, headers):
        return self._request("POST", "/api/cdi-queries", payload, headers)

    def list_cdi_queries(self, headers, params=None):
        return self._request("GET", "/api/cdi-queries", headers=headers, params=params)

    def get_cdi_query(self, query_id, headers):
        return self._request("GET", f"/api/cdi-queries/{query_id}", headers=headers)

    def update_cdi_query(self, query_id, payload, headers):
        return self._request("PUT", f"/api/cdi-queries/{query_id}", payload, headers)

    def send_cdi_query(self, query_id, payload, headers):
        return self._request("POST", f"/api/cdi-queries/{query_id}/send", payload, headers)

    def cancel_cdi_query(self, query_id, headers):
        return self._request("POST", f"/api/cdi-queries/{query_id}/cancel", {}, headers)

    # --- Query Responses ---
    def create_query_response(self, query_id, payload, headers):
        return self._request("POST", f"/api/cdi-queries/{query_id}/responses", payload, headers)

    def get_query_responses(self, query_id, headers):
        return self._request("GET", f"/api/cdi-queries/{query_id}/responses", headers=headers)

    # --- Reconciliation Events ---
    def list_reconciliation_events(self, headers, params=None):
        return self._request("GET", "/api/reconciliation-events", headers=headers, params=params)

    def get_reconciliation_event(self, event_id, headers):
        return self._request("GET", f"/api/reconciliation-events/{event_id}", headers=headers)

    def resolve_reconciliation_event(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/reconciliation-events/{event_id}/resolve", payload, headers
        )

    def escalate_reconciliation_event(self, event_id, headers):
        return self._request(
            "POST", f"/api/reconciliation-events/{event_id}/escalate", {}, headers
        )

    # --- Denial Risk Targets ---
    def create_denial_risk_target(self, payload, headers):
        return self._request("POST", "/api/denial-risk-targets", payload, headers)

    def list_denial_risk_targets(self, headers, params=None):
        return self._request("GET", "/api/denial-risk-targets", headers=headers, params=params)

    def get_denial_risk_target(self, target_id, headers):
        return self._request("GET", f"/api/denial-risk-targets/{target_id}", headers=headers)

    # --- Provider Education Events ---
    def create_provider_education_event(self, payload, headers):
        return self._request("POST", "/api/provider-education-events", payload, headers)

    def list_provider_education_events_all(self, headers, params=None):
        return self._request(
            "GET", "/api/provider-education-events", headers=headers, params=params
        )

    # --- CMI Snapshots ---
    def list_cmi_snapshots(self, headers, params=None):
        return self._request("GET", "/api/cmi-snapshots", headers=headers, params=params)

    def get_cmi_snapshot(self, snapshot_id, headers):
        return self._request("GET", f"/api/cmi-snapshots/{snapshot_id}", headers=headers)

    # --- Test-driving clock ---
    def set_current_utc(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
