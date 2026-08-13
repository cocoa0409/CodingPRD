"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Coordinators / Agents ---
    def create_coordinator(self, payload, headers):
        return self._request("POST", "/tc/coordinators", payload, headers)

    def get_coordinator(self, coordinator_id, headers):
        return self._request("GET", f"/tc/coordinators/{coordinator_id}", headers=headers)

    def create_agent(self, payload, headers):
        return self._request("POST", "/tc/agents", payload, headers)

    def get_agent(self, agent_id, headers):
        return self._request("GET", f"/tc/agents/{agent_id}", headers=headers)

    def list_agents(self, headers, params=None):
        return self._request("GET", "/tc/agents", headers=headers, params=params)

    # --- Checklist templates ---
    def create_template(self, payload, headers):
        return self._request("POST", "/tc/checklist-templates", payload, headers)

    def get_template(self, template_id, headers):
        return self._request("GET", f"/tc/checklist-templates/{template_id}", headers=headers)

    def list_templates(self, headers, params=None):
        return self._request("GET", "/tc/checklist-templates", headers=headers, params=params)

    def publish_template(self, template_id, headers):
        return self._request("POST", f"/tc/checklist-templates/{template_id}/publish", {}, headers)

    def retire_template(self, template_id, headers):
        return self._request("POST", f"/tc/checklist-templates/{template_id}/retire", {}, headers)

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/tc/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/tc/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/tc/subscriptions", headers=headers, params=params)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/tc/subscriptions/{subscription_id}/cancel", {}, headers)

    # --- Transaction files ---
    def create_file(self, payload, headers):
        return self._request("POST", "/tc/files", payload, headers)

    def get_file(self, file_id, headers):
        return self._request("GET", f"/tc/files/{file_id}", headers=headers)

    def list_files(self, headers, params=None):
        return self._request("GET", "/tc/files", headers=headers, params=params)

    def activate_file(self, file_id, headers):
        return self._request("POST", f"/tc/files/{file_id}/activate", {}, headers)

    def terminate_file(self, file_id, headers, payload=None):
        return self._request("POST", f"/tc/files/{file_id}/terminate", payload or {}, headers)

    def request_close_file(self, file_id, headers):
        return self._request("POST", f"/tc/files/{file_id}/request-close", {}, headers)

    def close_file(self, file_id, headers):
        return self._request("POST", f"/tc/files/{file_id}/close", {}, headers)

    def archive_file(self, file_id, headers):
        return self._request("POST", f"/tc/files/{file_id}/archive", {}, headers)

    def run_compliance_audit(self, file_id, headers):
        return self._request("POST", f"/tc/files/{file_id}/compliance-audit", {}, headers)

    # --- Milestones ---
    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/tc/milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/tc/milestones", headers=headers, params=params)

    def start_milestone(self, milestone_id, headers):
        return self._request("POST", f"/tc/milestones/{milestone_id}/start", {}, headers)

    def complete_milestone(self, milestone_id, headers):
        return self._request("POST", f"/tc/milestones/{milestone_id}/complete", {}, headers)

    def waive_milestone(self, milestone_id, headers):
        return self._request("POST", f"/tc/milestones/{milestone_id}/waive", {}, headers)

    # --- Deadlines ---
    def get_deadline(self, deadline_id, headers):
        return self._request("GET", f"/tc/deadlines/{deadline_id}", headers=headers)

    def list_deadlines(self, headers, params=None):
        return self._request("GET", "/tc/deadlines", headers=headers, params=params)

    def mark_deadline_met(self, deadline_id, headers):
        return self._request("POST", f"/tc/deadlines/{deadline_id}/mark-met", {}, headers)

    def waive_deadline(self, deadline_id, headers):
        return self._request("POST", f"/tc/deadlines/{deadline_id}/waive", {}, headers)

    # --- Reminders ---
    def get_reminder(self, reminder_id, headers):
        return self._request("GET", f"/tc/reminders/{reminder_id}", headers=headers)

    def list_reminders(self, headers, params=None):
        return self._request("GET", "/tc/reminders", headers=headers, params=params)

    # --- Documents ---
    def create_document(self, payload, headers):
        return self._request("POST", "/tc/documents", payload, headers)

    def get_document(self, document_id, headers):
        return self._request("GET", f"/tc/documents/{document_id}", headers=headers)

    def list_documents(self, headers, params=None):
        return self._request("GET", "/tc/documents", headers=headers, params=params)

    def submit_document(self, document_id, headers):
        return self._request("POST", f"/tc/documents/{document_id}/submit", {}, headers)

    def accept_document(self, document_id, headers):
        return self._request("POST", f"/tc/documents/{document_id}/accept", {}, headers)

    def reject_document(self, document_id, headers, payload=None):
        return self._request("POST", f"/tc/documents/{document_id}/reject", payload or {}, headers)

    # --- Communications ---
    def create_communication(self, payload, headers):
        return self._request("POST", "/tc/communications", payload, headers)

    def get_communication(self, communication_id, headers):
        return self._request("GET", f"/tc/communications/{communication_id}", headers=headers)

    def list_communications(self, headers, params=None):
        return self._request("GET", "/tc/communications", headers=headers, params=params)

    def resolve_communication(self, communication_id, headers):
        return self._request("POST", f"/tc/communications/{communication_id}/resolve", {}, headers)

    # --- Amendments ---
    def create_amendment(self, payload, headers):
        return self._request("POST", "/tc/amendments", payload, headers)

    def get_amendment(self, amendment_id, headers):
        return self._request("GET", f"/tc/amendments/{amendment_id}", headers=headers)

    def list_amendments(self, headers, params=None):
        return self._request("GET", "/tc/amendments", headers=headers, params=params)

    def route_amendment(self, amendment_id, headers):
        return self._request("POST", f"/tc/amendments/{amendment_id}/route", {}, headers)

    def revise_amendment(self, amendment_id, headers):
        return self._request("POST", f"/tc/amendments/{amendment_id}/revise", {}, headers)

    def apply_amendment(self, amendment_id, headers):
        return self._request("POST", f"/tc/amendments/{amendment_id}/apply", {}, headers)

    def void_amendment(self, amendment_id, headers):
        return self._request("POST", f"/tc/amendments/{amendment_id}/void", {}, headers)

    # --- Signature requests ---
    def get_signature_request(self, signature_request_id, headers):
        return self._request("GET", f"/tc/signature-requests/{signature_request_id}", headers=headers)

    def list_signature_requests(self, headers, params=None):
        return self._request("GET", "/tc/signature-requests", headers=headers, params=params)

    def sign_signature_request(self, signature_request_id, headers, payload=None):
        return self._request("POST", f"/tc/signature-requests/{signature_request_id}/sign", payload or {}, headers)

    def decline_signature_request(self, signature_request_id, headers, payload=None):
        return self._request("POST", f"/tc/signature-requests/{signature_request_id}/decline", payload or {}, headers)

    # --- Closing verifications ---
    def get_closing_verification(self, closing_verification_id, headers):
        return self._request("GET", f"/tc/closing-verifications/{closing_verification_id}", headers=headers)

    def list_closing_verifications(self, headers, params=None):
        return self._request("GET", "/tc/closing-verifications", headers=headers, params=params)

    def confirm_title(self, closing_verification_id, headers):
        return self._request("POST", f"/tc/closing-verifications/{closing_verification_id}/confirm-title", {}, headers)

    def confirm_lender(self, closing_verification_id, headers):
        return self._request("POST", f"/tc/closing-verifications/{closing_verification_id}/confirm-lender", {}, headers)

    # --- Invoices ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/tc/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/tc/invoices", headers=headers, params=params)

    def issue_invoice(self, invoice_id, headers):
        return self._request("POST", f"/tc/invoices/{invoice_id}/issue", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/tc/invoices/{invoice_id}/mark-paid", {}, headers)

    # --- Logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/tc/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
