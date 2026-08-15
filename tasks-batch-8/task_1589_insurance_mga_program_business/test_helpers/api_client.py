"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Per-test-server isolation kills and restarts the server process on
        # the same port before every test. A pooled keep-alive connection to
        # the previous (now-dead) process is reused by requests/urllib3 and
        # fails with ConnectionResetError. Sending Connection: close disables
        # connection reuse so every request opens a fresh socket to the
        # currently-live server. Per-request role headers still merge over
        # this session default.
        self.session.headers.update({"Connection": "close"})

    # ------------------------------------------------------------------
    # Logical clock / ops checkpoint (test-driving endpoints)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/mga/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily(self, headers):
        return self._request("POST", "/mga/_ops/run-daily", {}, headers)

    # ------------------------------------------------------------------
    # Carriers
    # ------------------------------------------------------------------
    def create_carrier(self, payload, headers):
        return self._request("POST", "/mga/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"/mga/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", "/mga/carriers", headers=headers, params=params)

    def suspend_carrier(self, carrier_id, headers):
        return self._request("POST", f"/mga/carriers/{carrier_id}/suspend", {}, headers)

    # ------------------------------------------------------------------
    # TPAs
    # ------------------------------------------------------------------
    def create_tpa(self, payload, headers):
        return self._request("POST", "/mga/tpas", payload, headers)

    def get_tpa(self, tpa_id, headers):
        return self._request("GET", f"/mga/tpas/{tpa_id}", headers=headers)

    def list_tpas(self, headers, params=None):
        return self._request("GET", "/mga/tpas", headers=headers, params=params)

    def suspend_tpa(self, tpa_id, headers):
        return self._request("POST", f"/mga/tpas/{tpa_id}/suspend", {}, headers)

    # ------------------------------------------------------------------
    # Programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/mga/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/mga/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/mga/programs", headers=headers, params=params)

    def activate_program(self, program_id, headers):
        return self._request("POST", f"/mga/programs/{program_id}/activate", {}, headers)

    def suspend_program(self, program_id, headers):
        return self._request("POST", f"/mga/programs/{program_id}/suspend", {}, headers)

    def resume_program(self, program_id, headers):
        return self._request("POST", f"/mga/programs/{program_id}/resume", {}, headers)

    def enter_runoff_program(self, program_id, headers):
        return self._request("POST", f"/mga/programs/{program_id}/enter-runoff", {}, headers)

    def terminate_program(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/terminate", payload, headers)

    def decline_program(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/decline", payload, headers)

    # ------------------------------------------------------------------
    # Underwriting guidelines
    # ------------------------------------------------------------------
    def create_guideline(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/guidelines", payload, headers)

    def list_program_guidelines(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/guidelines",
                             headers=headers, params=params)

    def get_guideline(self, guideline_id, headers):
        return self._request("GET", f"/mga/guidelines/{guideline_id}", headers=headers)

    def list_guidelines(self, headers, params=None):
        return self._request("GET", "/mga/guidelines", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Capacity allocations
    # ------------------------------------------------------------------
    def create_capacity_allocation(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/capacity-allocations",
                             payload, headers)

    def list_program_allocations(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/capacity-allocations",
                             headers=headers, params=params)

    def get_allocation(self, allocation_id, headers):
        return self._request("GET", f"/mga/capacity-allocations/{allocation_id}",
                             headers=headers)

    def list_allocations(self, headers, params=None):
        return self._request("GET", "/mga/capacity-allocations", headers=headers, params=params)

    def release_allocation(self, allocation_id, headers):
        return self._request("POST", f"/mga/capacity-allocations/{allocation_id}/release",
                             {}, headers)

    # ------------------------------------------------------------------
    # Rate filings
    # ------------------------------------------------------------------
    def create_rate_filing(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/rate-filings",
                             payload, headers)

    def list_program_filings(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/rate-filings",
                             headers=headers, params=params)

    def get_filing(self, filing_id, headers):
        return self._request("GET", f"/mga/rate-filings/{filing_id}", headers=headers)

    def list_filings(self, headers, params=None):
        return self._request("GET", "/mga/rate-filings", headers=headers, params=params)

    def submit_filing(self, filing_id, headers):
        return self._request("POST", f"/mga/rate-filings/{filing_id}/submit", {}, headers)

    def approve_filing(self, filing_id, headers):
        return self._request("POST", f"/mga/rate-filings/{filing_id}/approve", {}, headers)

    def disapprove_filing(self, filing_id, headers):
        return self._request("POST", f"/mga/rate-filings/{filing_id}/disapprove", {}, headers)

    def revise_filing(self, filing_id, headers):
        return self._request("POST", f"/mga/rate-filings/{filing_id}/revise", {}, headers)

    def mark_effective_filing(self, filing_id, headers):
        return self._request("POST", f"/mga/rate-filings/{filing_id}/mark-effective",
                             {}, headers)

    # ------------------------------------------------------------------
    # Policies
    # ------------------------------------------------------------------
    def create_policy(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/policies", payload, headers)

    def list_program_policies(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/policies",
                             headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/mga/policies/{policy_id}", headers=headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/mga/policies", headers=headers, params=params)

    def bind_policy(self, policy_id, headers):
        return self._request("POST", f"/mga/policies/{policy_id}/bind", {}, headers)

    def issue_policy(self, policy_id, headers):
        return self._request("POST", f"/mga/policies/{policy_id}/issue", {}, headers)

    def cancel_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/mga/policies/{policy_id}/cancel", payload, headers)

    def reinstate_policy(self, policy_id, headers):
        return self._request("POST", f"/mga/policies/{policy_id}/reinstate", {}, headers)

    def final_audit_policy(self, policy_id, payload, headers):
        return self._request("POST", f"/mga/policies/{policy_id}/final-audit",
                             payload, headers)

    # ------------------------------------------------------------------
    # Premium trust accounting
    # ------------------------------------------------------------------
    def record_collection(self, policy_id, payload, headers):
        return self._request("POST", f"/mga/policies/{policy_id}/collections",
                             payload, headers)

    def record_remittance(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/remittances",
                             payload, headers)

    def list_program_ledger(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/trust-ledger",
                             headers=headers, params=params)

    def get_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/mga/trust-ledger-entries/{entry_id}",
                             headers=headers)

    def list_ledger_entries(self, headers, params=None):
        return self._request("GET", "/mga/trust-ledger-entries", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Claims
    # ------------------------------------------------------------------
    def report_claim(self, policy_id, payload, headers):
        return self._request("POST", f"/mga/policies/{policy_id}/claims", payload, headers)

    def list_policy_claims(self, policy_id, headers, params=None):
        return self._request("GET", f"/mga/policies/{policy_id}/claims",
                             headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/mga/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/mga/claims", headers=headers, params=params)

    def start_claim_review(self, claim_id, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/start-review", {}, headers)

    def set_claim_reserve(self, claim_id, payload, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/set-reserve", payload, headers)

    def refer_claim(self, claim_id, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/refer", {}, headers)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/approve", payload, headers)

    def deny_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/deny", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/pay", {}, headers)

    def reopen_claim(self, claim_id, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/reopen", {}, headers)

    def resume_claim_review(self, claim_id, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/resume-review", {}, headers)

    def close_claim(self, claim_id, headers):
        return self._request("POST", f"/mga/claims/{claim_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # TPA appointments
    # ------------------------------------------------------------------
    def create_appointment(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/tpa-appointments",
                             payload, headers)

    def list_program_appointments(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/tpa-appointments",
                             headers=headers, params=params)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/mga/tpa-appointments/{appointment_id}",
                             headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/mga/tpa-appointments", headers=headers, params=params)

    def activate_appointment(self, appointment_id, headers):
        return self._request("POST", f"/mga/tpa-appointments/{appointment_id}/activate",
                             {}, headers)

    def suspend_appointment(self, appointment_id, headers):
        return self._request("POST", f"/mga/tpa-appointments/{appointment_id}/suspend",
                             {}, headers)

    def reinstate_appointment(self, appointment_id, headers):
        return self._request("POST", f"/mga/tpa-appointments/{appointment_id}/reinstate",
                             {}, headers)

    def revoke_appointment(self, appointment_id, headers):
        return self._request("POST", f"/mga/tpa-appointments/{appointment_id}/revoke",
                             {}, headers)

    # ------------------------------------------------------------------
    # Bordereaux
    # ------------------------------------------------------------------
    def create_bordereau(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/bordereaux",
                             payload, headers)

    def list_program_bordereaux(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/bordereaux",
                             headers=headers, params=params)

    def get_bordereau(self, bordereau_id, headers):
        return self._request("GET", f"/mga/bordereaux/{bordereau_id}", headers=headers)

    def list_bordereaux(self, headers, params=None):
        return self._request("GET", "/mga/bordereaux", headers=headers, params=params)

    def submit_bordereau(self, bordereau_id, headers):
        return self._request("POST", f"/mga/bordereaux/{bordereau_id}/submit", {}, headers)

    def accept_bordereau(self, bordereau_id, headers):
        return self._request("POST", f"/mga/bordereaux/{bordereau_id}/accept", {}, headers)

    def reject_bordereau(self, bordereau_id, payload, headers):
        return self._request("POST", f"/mga/bordereaux/{bordereau_id}/reject",
                             payload, headers)

    def revise_bordereau(self, bordereau_id, headers):
        return self._request("POST", f"/mga/bordereaux/{bordereau_id}/revise", {}, headers)

    def cancel_bordereau(self, bordereau_id, headers):
        return self._request("POST", f"/mga/bordereaux/{bordereau_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Carrier audits
    # ------------------------------------------------------------------
    def create_audit(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/audits", payload, headers)

    def list_program_audits(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/audits",
                             headers=headers, params=params)

    def get_audit(self, audit_id, headers):
        return self._request("GET", f"/mga/audits/{audit_id}", headers=headers)

    def list_audits(self, headers, params=None):
        return self._request("GET", "/mga/audits", headers=headers, params=params)

    def start_audit(self, audit_id, headers):
        return self._request("POST", f"/mga/audits/{audit_id}/start", {}, headers)

    def issue_findings(self, audit_id, payload, headers):
        return self._request("POST", f"/mga/audits/{audit_id}/issue-findings",
                             payload, headers)

    def submit_remediation(self, audit_id, payload, headers):
        return self._request("POST", f"/mga/audits/{audit_id}/submit-remediation",
                             payload, headers)

    def close_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/mga/audits/{audit_id}/close", payload, headers)

    def escalate_audit(self, audit_id, headers):
        return self._request("POST", f"/mga/audits/{audit_id}/escalate", {}, headers)

    # ------------------------------------------------------------------
    # Loss evaluations
    # ------------------------------------------------------------------
    def create_loss_evaluation(self, program_id, payload, headers):
        return self._request("POST", f"/mga/programs/{program_id}/loss-evaluations",
                             payload, headers)

    def list_program_loss_evaluations(self, program_id, headers, params=None):
        return self._request("GET", f"/mga/programs/{program_id}/loss-evaluations",
                             headers=headers, params=params)

    def get_loss_evaluation(self, evaluation_id, headers):
        return self._request("GET", f"/mga/loss-evaluations/{evaluation_id}",
                             headers=headers)

    def list_loss_evaluations(self, headers, params=None):
        return self._request("GET", "/mga/loss-evaluations", headers=headers, params=params)


api_client = ApiClient()
