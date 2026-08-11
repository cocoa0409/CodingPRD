"""API client: one method per endpoint defined in the PRD.

All paths include the /v1 prefix. Methods return raw requests.Response so
tests can assert on status codes and envelopes via the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # --- rate cards ---
    def create_rate_card(self, payload, headers):
        return self._request("POST", "/v1/rate-cards", payload, headers)

    def list_rate_cards(self, headers, params=None):
        return self._request("GET", "/v1/rate-cards", headers=headers, params=params)

    def get_rate_card(self, card_id, headers):
        return self._request("GET", f"/v1/rate-cards/{card_id}", headers=headers)

    def activate_rate_card(self, card_id, headers):
        return self._request("POST", f"/v1/rate-cards/{card_id}/activate", {}, headers)

    def retire_rate_card(self, card_id, headers):
        return self._request("POST", f"/v1/rate-cards/{card_id}/retire", {}, headers)

    def create_rate_card_revision(self, card_id, payload, headers):
        return self._request("POST", f"/v1/rate-cards/{card_id}/revisions", payload, headers)

    # --- suppliers ---
    def create_supplier(self, payload, headers):
        return self._request("POST", "/v1/suppliers", payload, headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/v1/suppliers", headers=headers, params=params)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/v1/suppliers/{supplier_id}", headers=headers)

    def suspend_supplier(self, supplier_id, headers):
        return self._request("POST", f"/v1/suppliers/{supplier_id}/suspend", {}, headers)

    def reinstate_supplier(self, supplier_id, headers):
        return self._request("POST", f"/v1/suppliers/{supplier_id}/reinstate", {}, headers)

    def evaluate_supplier_tier(self, supplier_id, headers):
        return self._request("POST", f"/v1/suppliers/{supplier_id}/tier-evaluation", {}, headers)

    # --- engagements ---
    def create_engagement(self, payload, headers):
        return self._request("POST", "/v1/engagements", payload, headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/v1/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/v1/engagements/{engagement_id}", headers=headers)

    def submit_engagement_review(self, engagement_id, headers):
        return self._request("POST", f"/v1/engagements/{engagement_id}/submit-review", {}, headers)

    def classification_decision(self, engagement_id, payload, headers):
        return self._request(
            "POST", f"/v1/engagements/{engagement_id}/classification-decision", payload, headers
        )

    def distribute_engagement(self, engagement_id, headers):
        return self._request("POST", f"/v1/engagements/{engagement_id}/distribute", {}, headers)

    def amend_engagement(self, engagement_id, payload, headers):
        return self._request("POST", f"/v1/engagements/{engagement_id}/amendments", payload, headers)

    def close_engagement(self, engagement_id, headers):
        return self._request("POST", f"/v1/engagements/{engagement_id}/close", {}, headers)

    # --- distribution offers ---
    def list_distribution_offers(self, headers, params=None):
        return self._request("GET", "/v1/distribution-offers", headers=headers, params=params)

    def get_distribution_offer(self, offer_id, headers):
        return self._request("GET", f"/v1/distribution-offers/{offer_id}", headers=headers)

    def respond_to_offer(self, offer_id, payload, headers):
        return self._request("POST", f"/v1/distribution-offers/{offer_id}/respond", payload, headers)

    def withdraw_offer(self, offer_id, headers):
        return self._request("POST", f"/v1/distribution-offers/{offer_id}/withdraw", {}, headers)

    def expire_offers_sweep(self, headers):
        return self._request("POST", "/v1/distribution-offers/expire-sweep", {}, headers)

    # --- workers ---
    def create_worker(self, payload, headers):
        return self._request("POST", "/v1/workers", payload, headers)

    def list_workers(self, headers, params=None):
        return self._request("GET", "/v1/workers", headers=headers, params=params)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/v1/workers/{worker_id}", headers=headers)

    def offboard_complete_worker(self, worker_id, headers):
        return self._request("POST", f"/v1/workers/{worker_id}/offboard-complete", {}, headers)

    def rehire_worker(self, worker_id, headers):
        return self._request("POST", f"/v1/workers/{worker_id}/rehire", {}, headers)

    # --- assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", "/v1/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/v1/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/v1/assignments/{assignment_id}", headers=headers)

    def activate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/v1/assignments/{assignment_id}/activate", {}, headers)

    def extend_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/v1/assignments/{assignment_id}/extend", payload, headers)

    def terminate_assignment(self, assignment_id, headers):
        return self._request("POST", f"/v1/assignments/{assignment_id}/terminate", {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/v1/assignments/{assignment_id}/complete", {}, headers)

    # --- timesheets ---
    def create_timesheet(self, payload, headers):
        return self._request("POST", "/v1/timesheets", payload, headers)

    def list_timesheets(self, headers, params=None):
        return self._request("GET", "/v1/timesheets", headers=headers, params=params)

    def get_timesheet(self, timesheet_id, headers):
        return self._request("GET", f"/v1/timesheets/{timesheet_id}", headers=headers)

    def submit_timesheet(self, timesheet_id, headers):
        return self._request("POST", f"/v1/timesheets/{timesheet_id}/submit", {}, headers)

    def approve_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/v1/timesheets/{timesheet_id}/approve", payload, headers)

    def reject_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/v1/timesheets/{timesheet_id}/reject", payload, headers)

    def void_timesheet(self, timesheet_id, payload, headers):
        return self._request("POST", f"/v1/timesheets/{timesheet_id}/void", payload, headers)

    # --- milestones ---
    def create_milestone(self, engagement_id, payload, headers):
        return self._request("POST", f"/v1/engagements/{engagement_id}/milestones", payload, headers)

    def list_milestones(self, engagement_id, headers, params=None):
        return self._request(
            "GET", f"/v1/engagements/{engagement_id}/milestones", headers=headers, params=params
        )

    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/v1/milestones/{milestone_id}", headers=headers)

    def deliver_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/v1/milestones/{milestone_id}/deliver", payload, headers)

    def accept_milestone(self, milestone_id, headers):
        return self._request("POST", f"/v1/milestones/{milestone_id}/accept", {}, headers)

    def reject_milestone(self, milestone_id, payload, headers):
        return self._request("POST", f"/v1/milestones/{milestone_id}/reject", payload, headers)

    # --- invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/v1/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/v1/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def finalize_invoice(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/finalize", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/mark-paid", {}, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/v1/invoices/{invoice_id}/void", payload, headers)

    # --- invoice lines ---
    def list_invoice_lines(self, headers, params=None):
        return self._request("GET", "/v1/invoice-lines", headers=headers, params=params)

    def get_invoice_line(self, line_id, headers):
        return self._request("GET", f"/v1/invoice-lines/{line_id}", headers=headers)

    # --- conversion requests ---
    def create_conversion_request(self, payload, headers):
        return self._request("POST", "/v1/conversion-requests", payload, headers)

    def list_conversion_requests(self, headers, params=None):
        return self._request("GET", "/v1/conversion-requests", headers=headers, params=params)

    def get_conversion_request(self, request_id, headers):
        return self._request("GET", f"/v1/conversion-requests/{request_id}", headers=headers)

    def approve_conversion_request(self, request_id, headers):
        return self._request("POST", f"/v1/conversion-requests/{request_id}/approve", {}, headers)

    def decline_conversion_request(self, request_id, payload, headers):
        return self._request("POST", f"/v1/conversion-requests/{request_id}/decline", payload, headers)

    def complete_conversion_request(self, request_id, headers):
        return self._request("POST", f"/v1/conversion-requests/{request_id}/complete", {}, headers)

    # --- compliance audits ---
    def run_compliance_audit(self, payload, headers):
        return self._request("POST", "/v1/compliance-audits/run", payload, headers)

    def list_compliance_audits(self, headers, params=None):
        return self._request("GET", "/v1/compliance-audits", headers=headers, params=params)

    def get_compliance_audit(self, audit_id, headers):
        return self._request("GET", f"/v1/compliance-audits/{audit_id}", headers=headers)

    def acknowledge_audit(self, audit_id, headers):
        return self._request("POST", f"/v1/compliance-audits/{audit_id}/acknowledge", {}, headers)

    def resolve_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/v1/compliance-audits/{audit_id}/resolve", payload, headers)

    def dismiss_audit(self, audit_id, payload, headers):
        return self._request("POST", f"/v1/compliance-audits/{audit_id}/dismiss", payload, headers)

    # --- spend ledger & visibility ---
    def list_spend_ledger_entries(self, headers, params=None):
        return self._request("GET", "/v1/spend-ledger-entries", headers=headers, params=params)

    def get_spend_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/v1/spend-ledger-entries/{entry_id}", headers=headers)

    def get_spend_summary(self, headers, params=None):
        return self._request("GET", "/v1/spend/summary", headers=headers, params=params)


api_client = ApiClient()
