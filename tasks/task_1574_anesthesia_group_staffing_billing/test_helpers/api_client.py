"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/anesthesia-ops"


class ApiClient(GenericApiClient):
    # --- Logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- Sites ---
    def create_site(self, payload, headers):
        return self._request("POST", f"{PREFIX}/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"{PREFIX}/sites/{site_id}", headers=headers)

    # --- Providers ---
    def create_provider(self, payload, headers):
        return self._request("POST", f"{PREFIX}/providers", payload, headers)

    def list_providers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/providers", headers=headers, params=params)

    def get_provider(self, provider_id, headers):
        return self._request("GET", f"{PREFIX}/providers/{provider_id}", headers=headers)

    def update_provider_credentials(self, provider_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/providers/{provider_id}/credentials",
                             payload, headers)

    # --- Procedure fee schedules ---
    def create_fee_schedule(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fee-schedules", payload, headers)

    def get_fee_schedule(self, fee_id, headers):
        return self._request("GET", f"{PREFIX}/fee-schedules/{fee_id}", headers=headers)

    def update_fee_schedule(self, fee_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/fee-schedules/{fee_id}", payload, headers)

    # --- Stipend agreements ---
    def create_stipend_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stipend-agreements", payload, headers)

    def list_stipend_agreements(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stipend-agreements", headers=headers, params=params)

    def get_stipend_agreement(self, agreement_id, headers):
        return self._request("GET", f"{PREFIX}/stipend-agreements/{agreement_id}", headers=headers)

    # --- Daily rosters ---
    def create_roster(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rosters", payload, headers)

    def list_rosters(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rosters", headers=headers, params=params)

    def get_roster(self, roster_id, headers):
        return self._request("GET", f"{PREFIX}/rosters/{roster_id}", headers=headers)

    def update_roster(self, roster_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/rosters/{roster_id}", payload, headers)

    def publish_roster(self, roster_id, headers):
        return self._request("POST", f"{PREFIX}/rosters/{roster_id}/publish", {}, headers)

    def unpublish_roster(self, roster_id, headers):
        return self._request("POST", f"{PREFIX}/rosters/{roster_id}/unpublish", {}, headers)

    def lock_roster(self, roster_id, headers):
        return self._request("POST", f"{PREFIX}/rosters/{roster_id}/lock", {}, headers)

    # --- Cases ---
    def create_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cases", payload, headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cases", headers=headers, params=params)

    def get_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/cases/{case_id}", headers=headers)

    def reschedule_case(self, case_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/cases/{case_id}", payload, headers)

    def start_case(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/start", {}, headers)

    def complete_case(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/complete", {}, headers)

    def cancel_case(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/cancel", payload, headers)

    # --- Case assignments ---
    def create_case_assignment(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/cases/{case_id}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers)

    def accept_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/accept", {}, headers)

    def decline_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/decline", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/cancel", {}, headers)

    # --- Call assignments ---
    def create_call_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/call-assignments", payload, headers)

    def list_call_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/call-assignments", headers=headers, params=params)

    def get_call_assignment(self, call_id, headers):
        return self._request("GET", f"{PREFIX}/call-assignments/{call_id}", headers=headers)

    def release_call_assignment(self, call_id, headers):
        return self._request("POST", f"{PREFIX}/call-assignments/{call_id}/release", {}, headers)

    # --- Direction attestations ---
    def create_attestation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/attestations", payload, headers)

    def list_attestations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/attestations", headers=headers, params=params)

    def get_attestation(self, attestation_id, headers):
        return self._request("GET", f"{PREFIX}/attestations/{attestation_id}", headers=headers)

    def submit_attestation(self, attestation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/attestations/{attestation_id}/submit",
                             payload, headers)

    def verify_attestation(self, attestation_id, headers):
        return self._request("POST", f"{PREFIX}/attestations/{attestation_id}/verify", {}, headers)

    def reject_attestation(self, attestation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/attestations/{attestation_id}/reject",
                             payload, headers)

    # --- Billing claims ---
    def create_claim(self, payload, headers):
        return self._request("POST", f"{PREFIX}/claims", payload, headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claims", headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"{PREFIX}/claims/{claim_id}", headers=headers)

    def mark_claim_ready(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/mark-ready", {}, headers)

    def submit_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/submit", {}, headers)

    def record_claim_payment(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/record-payment",
                             payload, headers)

    def record_claim_denial(self, claim_id, payload, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/record-denial",
                             payload, headers)

    def write_off_claim(self, claim_id, headers):
        return self._request("POST", f"{PREFIX}/claims/{claim_id}/write-off", {}, headers)

    # --- Stipend ledger entries ---
    def list_stipend_entries(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stipend-entries", headers=headers, params=params)

    def get_stipend_entry(self, entry_id, headers):
        return self._request("GET", f"{PREFIX}/stipend-entries/{entry_id}", headers=headers)

    def get_stipend_summary(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stipend-entries/summary",
                             headers=headers, params=params)

    def void_stipend_entry(self, entry_id, headers):
        return self._request("POST", f"{PREFIX}/stipend-entries/{entry_id}/void", {}, headers)

    # --- Compliance audits / findings ---
    def run_audit_scan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audits", payload, headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/audits", headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"{PREFIX}/audits/{audit_id}", headers=headers)

    def close_audit(self, audit_id, headers):
        return self._request("POST", f"{PREFIX}/audits/{audit_id}/close", {}, headers)

    def list_findings(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/findings", headers=headers, params=params)

    def get_finding(self, finding_id, headers):
        return self._request("GET", f"{PREFIX}/findings/{finding_id}", headers=headers)

    def resolve_finding(self, finding_id, payload, headers):
        return self._request("POST", f"{PREFIX}/findings/{finding_id}/resolve",
                             payload, headers)

    def dismiss_finding(self, finding_id, payload, headers):
        return self._request("POST", f"{PREFIX}/findings/{finding_id}/dismiss",
                             payload, headers)


api_client = ApiClient()
