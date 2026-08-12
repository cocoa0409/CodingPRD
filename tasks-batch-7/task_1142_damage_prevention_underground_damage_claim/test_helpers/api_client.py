"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/damage-recovery"


class ApiClient(GenericApiClient):
    # --- Test-driving clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/_clock/set_current_utc", payload, headers)

    # --- Excavator ---
    def create_excavator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/excavators", payload, headers)

    def get_excavator(self, excavator_id, headers):
        return self._request("GET", f"{PREFIX}/excavators/{excavator_id}", headers=headers)

    def list_excavators(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/excavators", headers=headers, params=params)

    def evaluate_program(self, excavator_id, headers):
        return self._request("POST", f"{PREFIX}/excavators/{excavator_id}/evaluate-program", {}, headers)

    # --- Locator ---
    def create_locator(self, payload, headers):
        return self._request("POST", f"{PREFIX}/locators", payload, headers)

    def list_locators(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/locators", headers=headers, params=params)

    def suspend_locator(self, locator_id, headers):
        return self._request("POST", f"{PREFIX}/locators/{locator_id}/suspend", {}, headers)

    # --- LocateTicket ---
    def create_locate_ticket(self, payload, headers):
        return self._request("POST", f"{PREFIX}/locate-tickets", payload, headers)

    def get_locate_ticket(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/locate-tickets/{ticket_id}", headers=headers)

    def list_locate_tickets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/locate-tickets", headers=headers, params=params)

    def renew_locate_ticket(self, ticket_id, payload, headers):
        return self._request("POST", f"{PREFIX}/locate-tickets/{ticket_id}/renew", payload, headers)

    # --- LocateResponse ---
    def create_locate_response(self, payload, headers):
        return self._request("POST", f"{PREFIX}/locate-responses", payload, headers)

    def get_locate_response(self, response_id, headers):
        return self._request("GET", f"{PREFIX}/locate-responses/{response_id}", headers=headers)

    def list_locate_responses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/locate-responses", headers=headers, params=params)

    def audit_locate_response(self, response_id, payload, headers):
        return self._request("POST", f"{PREFIX}/locate-responses/{response_id}/audit", payload, headers)

    # --- DamageCase ---
    def create_damage_case(self, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-cases", payload, headers)

    def get_damage_case(self, case_id, headers):
        return self._request("GET", f"{PREFIX}/damage-cases/{case_id}", headers=headers)

    def list_damage_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/damage-cases", headers=headers, params=params)

    def link_ticket(self, case_id, payload, headers):
        return self._request("POST", f"{PREFIX}/damage-cases/{case_id}/link-ticket", payload, headers)

    def begin_investigation(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/damage-cases/{case_id}/begin-investigation", {}, headers)

    def reconstruct_timeline(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/damage-cases/{case_id}/reconstruct-timeline", {}, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"{PREFIX}/damage-cases/{case_id}/close", {}, headers)

    # --- EvidenceItem ---
    def create_evidence_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/evidence-items", payload, headers)

    def get_evidence_item(self, evidence_id, headers):
        return self._request("GET", f"{PREFIX}/evidence-items/{evidence_id}", headers=headers)

    def list_evidence_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/evidence-items", headers=headers, params=params)

    # --- TimelineEvent ---
    def get_timeline_event(self, event_id, headers):
        return self._request("GET", f"{PREFIX}/timeline-events/{event_id}", headers=headers)

    def list_timeline_events(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/timeline-events", headers=headers, params=params)

    # --- FaultAllocation ---
    def create_fault_allocation(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fault-allocations", payload, headers)

    def get_fault_allocation(self, allocation_id, headers):
        return self._request("GET", f"{PREFIX}/fault-allocations/{allocation_id}", headers=headers)

    def list_fault_allocations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fault-allocations", headers=headers, params=params)

    def propose_fault_allocation(self, allocation_id, headers):
        return self._request("POST", f"{PREFIX}/fault-allocations/{allocation_id}/propose", {}, headers)

    def contest_fault_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fault-allocations/{allocation_id}/contest", payload, headers)

    def revise_fault_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fault-allocations/{allocation_id}/revise", payload, headers)

    def finalize_fault_allocation(self, allocation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fault-allocations/{allocation_id}/finalize", payload, headers)

    # --- CostLineItem ---
    def create_cost_line_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/cost-line-items", payload, headers)

    def get_cost_line_item(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/cost-line-items/{line_id}", headers=headers)

    def list_cost_line_items(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/cost-line-items", headers=headers, params=params)

    def delete_cost_line_item(self, line_id, headers):
        return self._request("DELETE", f"{PREFIX}/cost-line-items/{line_id}", headers=headers)

    # --- ClaimInvoice ---
    def get_claim_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/claim-invoices/{invoice_id}", headers=headers)

    def list_claim_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/claim-invoices", headers=headers, params=params)

    def issue_claim_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/claim-invoices/{invoice_id}/issue", {}, headers)

    def write_off_claim_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/claim-invoices/{invoice_id}/write-off", {}, headers)

    # --- Payment ---
    def create_payment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"{PREFIX}/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/payments", headers=headers, params=params)

    def reverse_payment(self, payment_id, headers):
        return self._request("POST", f"{PREFIX}/payments/{payment_id}/reverse", {}, headers)

    # --- Dispute ---
    def create_dispute(self, payload, headers):
        return self._request("POST", f"{PREFIX}/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"{PREFIX}/disputes/{dispute_id}", headers=headers)

    def list_disputes(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/disputes", headers=headers, params=params)

    def respond_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"{PREFIX}/disputes/{dispute_id}/respond", payload, headers)

    def counter_dispute(self, dispute_id, payload, headers):
        return self._request("POST", f"{PREFIX}/disputes/{dispute_id}/counter", payload, headers)

    def accept_resolution(self, dispute_id, headers):
        return self._request("POST", f"{PREFIX}/disputes/{dispute_id}/accept-resolution", {}, headers)

    def escalate_dispute(self, dispute_id, headers):
        return self._request("POST", f"{PREFIX}/disputes/{dispute_id}/escalate", {}, headers)

    # --- SubrogationCase ---
    def get_subrogation_case(self, subrogation_id, headers):
        return self._request("GET", f"{PREFIX}/subrogation-cases/{subrogation_id}", headers=headers)

    def list_subrogation_cases(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/subrogation-cases", headers=headers, params=params)

    def record_settlement(self, subrogation_id, payload, headers):
        return self._request("POST", f"{PREFIX}/subrogation-cases/{subrogation_id}/record-settlement", payload, headers)

    def close_subrogation_case(self, subrogation_id, headers):
        return self._request("POST", f"{PREFIX}/subrogation-cases/{subrogation_id}/close", {}, headers)

    # --- RegulatoryReport ---
    def create_regulatory_report(self, payload, headers):
        return self._request("POST", f"{PREFIX}/regulatory-reports", payload, headers)

    def get_regulatory_report(self, report_id, headers):
        return self._request("GET", f"{PREFIX}/regulatory-reports/{report_id}", headers=headers)

    def list_regulatory_reports(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/regulatory-reports", headers=headers, params=params)

    def file_regulatory_report(self, report_id, headers):
        return self._request("POST", f"{PREFIX}/regulatory-reports/{report_id}/file", {}, headers)

    def amend_regulatory_report(self, report_id, payload, headers):
        return self._request("POST", f"{PREFIX}/regulatory-reports/{report_id}/amend", payload, headers)

    # --- ViolationRecord ---
    def create_violation_record(self, payload, headers):
        return self._request("POST", f"{PREFIX}/violation-records", payload, headers)

    def get_violation_record(self, violation_id, headers):
        return self._request("GET", f"{PREFIX}/violation-records/{violation_id}", headers=headers)

    def list_violation_records(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/violation-records", headers=headers, params=params)

    def overturn_violation(self, violation_id, headers):
        return self._request("POST", f"{PREFIX}/violation-records/{violation_id}/overturn", {}, headers)

    # --- TrainingCourse ---
    def create_training_course(self, payload, headers):
        return self._request("POST", f"{PREFIX}/training-courses", payload, headers)

    def get_training_course(self, course_id, headers):
        return self._request("GET", f"{PREFIX}/training-courses/{course_id}", headers=headers)

    def list_training_courses(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/training-courses", headers=headers, params=params)

    # --- TrainingAssignment ---
    def create_training_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/training-assignments", payload, headers)

    def get_training_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/training-assignments/{assignment_id}", headers=headers)

    def list_training_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/training-assignments", headers=headers, params=params)

    def complete_training_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/training-assignments/{assignment_id}/complete", {}, headers)


api_client = ApiClient()
