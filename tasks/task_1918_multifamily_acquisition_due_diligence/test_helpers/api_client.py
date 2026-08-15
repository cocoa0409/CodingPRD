"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.7)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Acquisition lifecycle (PRD §3.1)
    # ------------------------------------------------------------------
    def create_acquisition(self, payload, headers):
        return self._request("POST", "/acquisitions", payload, headers)

    def list_acquisitions(self, headers, params=None):
        return self._request("GET", "/acquisitions", headers=headers, params=params)

    def get_acquisition(self, acquisition_id, headers):
        return self._request("GET", f"/acquisitions/{acquisition_id}", headers=headers)

    def patch_acquisition(self, acquisition_id, payload, headers):
        return self._request("PATCH", f"/acquisitions/{acquisition_id}", payload, headers)

    def kickoff_acquisition(self, acquisition_id, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/kickoff", {}, headers)

    def complete_diligence(self, acquisition_id, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/complete-diligence", {}, headers)

    def advance_to_pre_closing(self, acquisition_id, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/advance-to-pre-closing", {}, headers)

    def execute_closing(self, acquisition_id, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/execute-closing", {}, headers)

    def settle_acquisition(self, acquisition_id, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/settle", {}, headers)

    def terminate_acquisition(self, acquisition_id, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Units (PRD §3.2)
    # ------------------------------------------------------------------
    def create_unit(self, payload, headers):
        return self._request("POST", "/acquisitions/units", payload, headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/acquisitions/units", headers=headers, params=params)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/acquisitions/units/{unit_id}", headers=headers)

    def exclude_unit(self, unit_id, headers):
        return self._request("POST", f"/acquisitions/units/{unit_id}/exclude", {}, headers)

    # ------------------------------------------------------------------
    # Lease files & rent roll (PRD §3.3)
    # ------------------------------------------------------------------
    def create_lease_file(self, payload, headers):
        return self._request("POST", "/acquisitions/lease-files", payload, headers)

    def list_lease_files(self, headers, params=None):
        return self._request("GET", "/acquisitions/lease-files", headers=headers, params=params)

    def get_lease_file(self, lease_file_id, headers):
        return self._request("GET", f"/acquisitions/lease-files/{lease_file_id}", headers=headers)

    def list_unit_lease_files(self, unit_id, headers, params=None):
        return self._request("GET", f"/acquisitions/units/{unit_id}/lease-files",
                             headers=headers, params=params)

    def audit_lease_file(self, lease_file_id, headers):
        return self._request("POST", f"/acquisitions/lease-files/{lease_file_id}/audit", {}, headers)

    def flag_lease_file(self, lease_file_id, reason, headers):
        return self._request("POST", f"/acquisitions/lease-files/{lease_file_id}/flag",
                             {"reason": reason}, headers)

    def resolve_lease_file(self, lease_file_id, payload, headers):
        return self._request("POST", f"/acquisitions/lease-files/{lease_file_id}/resolve",
                             payload, headers)

    def waive_lease_file(self, lease_file_id, waiver_note, headers):
        return self._request("POST", f"/acquisitions/lease-files/{lease_file_id}/waive",
                             {"waiver_note": waiver_note}, headers)

    def create_rent_roll_entry(self, payload, headers):
        return self._request("POST", "/acquisitions/rent-roll-entries", payload, headers)

    def list_unit_rent_roll_entries(self, unit_id, headers, params=None):
        return self._request("GET", f"/acquisitions/units/{unit_id}/rent-roll-entries",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Concessions (PRD §3.3)
    # ------------------------------------------------------------------
    def create_concession(self, payload, headers):
        return self._request("POST", "/acquisitions/concessions", payload, headers)

    def list_lease_concessions(self, lease_file_id, headers, params=None):
        return self._request("GET", f"/acquisitions/lease-files/{lease_file_id}/concessions",
                             headers=headers, params=params)

    def verify_concession(self, concession_id, verified_value_cents, headers):
        return self._request("POST", f"/acquisitions/concessions/{concession_id}/verify",
                             {"verified_value_cents": verified_value_cents}, headers)

    def reject_concession(self, concession_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/acquisitions/concessions/{concession_id}/reject",
                             payload, headers)

    # ------------------------------------------------------------------
    # Unit walk inspections & findings (PRD §3.4)
    # ------------------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/acquisitions/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/acquisitions/inspections/{inspection_id}", headers=headers)

    def list_unit_inspections(self, unit_id, headers, params=None):
        return self._request("GET", f"/acquisitions/units/{unit_id}/inspections",
                             headers=headers, params=params)

    def complete_inspection(self, inspection_id, condition_rating, no_findings_declared, headers):
        return self._request("POST", f"/acquisitions/inspections/{inspection_id}/complete",
                             {"condition_rating": condition_rating,
                              "no_findings_declared": no_findings_declared}, headers)

    def qa_accept_inspection(self, inspection_id, headers):
        return self._request("POST", f"/acquisitions/inspections/{inspection_id}/qa-accept",
                             {}, headers)

    def qa_reject_inspection(self, inspection_id, reason, headers):
        return self._request("POST", f"/acquisitions/inspections/{inspection_id}/qa-reject",
                             {"reason": reason}, headers)

    def reschedule_inspection(self, inspection_id, walk_start, walk_end, headers):
        return self._request("POST", f"/acquisitions/inspections/{inspection_id}/reschedule",
                             {"walk_start": walk_start, "walk_end": walk_end}, headers)

    def create_finding(self, payload, headers):
        return self._request("POST", "/acquisitions/findings", payload, headers)

    def list_inspection_findings(self, inspection_id, headers, params=None):
        return self._request("GET", f"/acquisitions/inspections/{inspection_id}/findings",
                             headers=headers, params=params)

    def verify_finding(self, finding_id, headers):
        return self._request("POST", f"/acquisitions/findings/{finding_id}/verify", {}, headers)

    def dispute_finding(self, finding_id, reason, headers):
        return self._request("POST", f"/acquisitions/findings/{finding_id}/dispute",
                             {"reason": reason}, headers)

    def exclude_finding(self, finding_id, reason, headers):
        return self._request("POST", f"/acquisitions/findings/{finding_id}/exclude",
                             {"reason": reason}, headers)

    # ------------------------------------------------------------------
    # Utility records & expense summary (PRD §3.5)
    # ------------------------------------------------------------------
    def create_utility_record(self, payload, headers):
        return self._request("POST", "/acquisitions/utility-records", payload, headers)

    def list_utility_records(self, headers, params=None):
        return self._request("GET", "/acquisitions/utility-records", headers=headers, params=params)

    def get_utility_record(self, record_id, headers):
        return self._request("GET", f"/acquisitions/utility-records/{record_id}", headers=headers)

    def get_expense_summary(self, acquisition_id, headers):
        return self._request("GET", f"/acquisitions/{acquisition_id}/expense-summary",
                             headers=headers)

    # ------------------------------------------------------------------
    # Tax reassessment projections (PRD §3.6)
    # ------------------------------------------------------------------
    def create_tax_projection(self, acquisition_id, payload, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/tax-projections",
                             payload, headers)

    def list_tax_projections(self, headers, params=None):
        return self._request("GET", "/acquisitions/tax-projections", headers=headers, params=params)

    def get_tax_projection(self, projection_id, headers):
        return self._request("GET", f"/acquisitions/tax-projections/{projection_id}",
                             headers=headers)

    def compute_tax_projection(self, projection_id, headers):
        return self._request("POST", f"/acquisitions/tax-projections/{projection_id}/compute",
                             {}, headers)

    def approve_tax_projection(self, projection_id, headers):
        return self._request("POST", f"/acquisitions/tax-projections/{projection_id}/approve",
                             {}, headers)

    def revise_tax_projection(self, projection_id, headers):
        return self._request("POST", f"/acquisitions/tax-projections/{projection_id}/revise",
                             {}, headers)

    # ------------------------------------------------------------------
    # Security deposits (PRD §3.10)
    # ------------------------------------------------------------------
    def create_deposit(self, payload, headers):
        return self._request("POST", "/acquisitions/deposits", payload, headers)

    def list_lease_deposits(self, lease_file_id, headers, params=None):
        return self._request("GET", f"/acquisitions/lease-files/{lease_file_id}/deposits",
                             headers=headers, params=params)

    def reconcile_deposit(self, deposit_id, headers):
        return self._request("POST", f"/acquisitions/deposits/{deposit_id}/reconcile", {}, headers)

    def resolve_deposit_dispute(self, deposit_id, payload, headers):
        return self._request("POST", f"/acquisitions/deposits/{deposit_id}/resolve-dispute",
                             payload, headers)

    def queue_deposit_escrow(self, deposit_id, headers):
        return self._request("POST", f"/acquisitions/deposits/{deposit_id}/queue-escrow",
                             {}, headers)

    # ------------------------------------------------------------------
    # Employee decisions (PRD §3.11)
    # ------------------------------------------------------------------
    def create_employee_decision(self, payload, headers):
        return self._request("POST", "/acquisitions/employee-decisions", payload, headers)

    def list_employee_decisions(self, headers, params=None):
        return self._request("GET", "/acquisitions/employee-decisions",
                             headers=headers, params=params)

    def get_employee_decision(self, decision_id, headers):
        return self._request("GET", f"/acquisitions/employee-decisions/{decision_id}",
                             headers=headers)

    def approve_employee_decision(self, decision_id, headers):
        return self._request("POST", f"/acquisitions/employee-decisions/{decision_id}/approve",
                             {}, headers)

    def reject_employee_decision(self, decision_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/acquisitions/employee-decisions/{decision_id}/reject",
                             payload, headers)

    def notify_employee_decision(self, decision_id, headers):
        return self._request("POST", f"/acquisitions/employee-decisions/{decision_id}/notify",
                             {}, headers)

    def mark_employee_decision_effective(self, decision_id, headers):
        return self._request("POST",
                             f"/acquisitions/employee-decisions/{decision_id}/mark-effective",
                             {}, headers)

    def rescind_employee_decision(self, decision_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/acquisitions/employee-decisions/{decision_id}/rescind",
                             payload, headers)

    # ------------------------------------------------------------------
    # Service contracts (PRD §3.7)
    # ------------------------------------------------------------------
    def create_service_contract(self, payload, headers):
        return self._request("POST", "/acquisitions/service-contracts", payload, headers)

    def list_service_contracts(self, headers, params=None):
        return self._request("GET", "/acquisitions/service-contracts", headers=headers,
                             params=params)

    def get_service_contract(self, contract_id, headers):
        return self._request("GET", f"/acquisitions/service-contracts/{contract_id}",
                             headers=headers)

    def begin_review_service_contract(self, contract_id, headers):
        return self._request("POST",
                             f"/acquisitions/service-contracts/{contract_id}/begin-review",
                             {}, headers)

    def assume_service_contract(self, contract_id, headers):
        return self._request("POST", f"/acquisitions/service-contracts/{contract_id}/assume",
                             {}, headers)

    def send_notice_service_contract(self, contract_id, cancellation_effective_date, headers):
        return self._request("POST",
                             f"/acquisitions/service-contracts/{contract_id}/send-notice",
                             {"cancellation_effective_date": cancellation_effective_date},
                             headers)

    def mark_cancelled_service_contract(self, contract_id, headers):
        return self._request("POST",
                             f"/acquisitions/service-contracts/{contract_id}/mark-cancelled",
                             {}, headers)

    def renew_service_contract(self, contract_id, headers):
        return self._request("POST", f"/acquisitions/service-contracts/{contract_id}/renew",
                             {}, headers)

    # ------------------------------------------------------------------
    # Insurance policies (PRD §3.7)
    # ------------------------------------------------------------------
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/acquisitions/insurance-policies", payload, headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/acquisitions/insurance-policies", headers=headers,
                             params=params)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/acquisitions/insurance-policies/{policy_id}",
                             headers=headers)

    def review_loss_runs(self, policy_id, headers):
        return self._request("POST",
                             f"/acquisitions/insurance-policies/{policy_id}/review-loss-runs",
                             {}, headers)

    def assume_insurance_policy(self, policy_id, headers, override_high_risk=None):
        payload = {} if override_high_risk is None else {"override_high_risk": override_high_risk}
        return self._request("POST", f"/acquisitions/insurance-policies/{policy_id}/assume",
                             payload, headers)

    def exclude_insurance_policy(self, policy_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST", f"/acquisitions/insurance-policies/{policy_id}/exclude",
                             payload, headers)

    # ------------------------------------------------------------------
    # Proration statements & lines (PRD §3.8)
    # ------------------------------------------------------------------
    def generate_proration_statement(self, acquisition_id, payload, headers):
        return self._request("POST", f"/acquisitions/{acquisition_id}/proration-statements",
                             payload, headers)

    def list_proration_statements(self, headers, params=None):
        return self._request("GET", "/acquisitions/proration-statements", headers=headers,
                             params=params)

    def get_proration_statement(self, statement_id, headers):
        return self._request("GET", f"/acquisitions/proration-statements/{statement_id}",
                             headers=headers)

    def add_statement_line(self, statement_id, payload, headers):
        return self._request("POST", f"/acquisitions/proration-statements/{statement_id}/lines",
                             payload, headers)

    def list_statement_lines(self, statement_id, headers, params=None):
        return self._request("GET", f"/acquisitions/proration-statements/{statement_id}/lines",
                             headers=headers, params=params)

    def submit_statement_review(self, statement_id, headers):
        return self._request("POST",
                             f"/acquisitions/proration-statements/{statement_id}/submit-review",
                             {}, headers)

    def send_back_statement(self, statement_id, headers, reason=None):
        payload = {} if reason is None else {"reason": reason}
        return self._request("POST",
                             f"/acquisitions/proration-statements/{statement_id}/send-back",
                             payload, headers)

    def approve_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/acquisitions/proration-statements/{statement_id}/approve",
                             {}, headers)

    def settle_statement(self, statement_id, headers):
        return self._request("POST",
                             f"/acquisitions/proration-statements/{statement_id}/settle",
                             {}, headers)

    # ------------------------------------------------------------------
    # Post-closing adjustments (PRD §3.12)
    # ------------------------------------------------------------------
    def create_adjustment(self, payload, headers):
        return self._request("POST", "/acquisitions/adjustments", payload, headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/acquisitions/adjustments", headers=headers, params=params)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/acquisitions/adjustments/{adjustment_id}", headers=headers)

    def evidence_adjustment(self, adjustment_id, payload, headers):
        return self._request("POST", f"/acquisitions/adjustments/{adjustment_id}/evidence",
                             payload, headers)

    def accept_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/acquisitions/adjustments/{adjustment_id}/accept",
                             {}, headers)

    def dispute_adjustment(self, adjustment_id, reason, headers):
        return self._request("POST", f"/acquisitions/adjustments/{adjustment_id}/dispute",
                             {"reason": reason}, headers)

    def resolve_adjustment(self, adjustment_id, resolved_amount_cents, headers):
        return self._request("POST", f"/acquisitions/adjustments/{adjustment_id}/resolve",
                             {"resolved_amount_cents": resolved_amount_cents}, headers)

    def apply_adjustment(self, adjustment_id, headers):
        return self._request("POST", f"/acquisitions/adjustments/{adjustment_id}/apply",
                             {}, headers)


api_client = ApiClient()
