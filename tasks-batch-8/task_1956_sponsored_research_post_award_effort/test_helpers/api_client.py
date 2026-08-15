"""API client: one method per endpoint defined in PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock (PRD §2.4, §4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/api/_clock/set_current_utc", payload, headers)

    # --- sponsors ---
    def create_sponsor(self, payload, headers):
        return self._request("POST", "/api/sponsors", payload, headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/api/sponsors", headers=headers, params=params)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/api/sponsors/{sponsor_id}", headers=headers)

    # --- persons ---
    def create_person(self, payload, headers):
        return self._request("POST", "/api/persons", payload, headers)

    def list_persons(self, headers, params=None):
        return self._request("GET", "/api/persons", headers=headers, params=params)

    def get_person(self, person_id, headers):
        return self._request("GET", f"/api/persons/{person_id}", headers=headers)

    # --- awards ---
    def create_award(self, payload, headers):
        return self._request("POST", "/api/awards", payload, headers)

    def list_awards(self, headers, params=None):
        return self._request("GET", "/api/awards", headers=headers, params=params)

    def get_award(self, award_id, headers):
        return self._request("GET", f"/api/awards/{award_id}", headers=headers)

    def activate_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/activate", {}, headers)

    def suspend_award(self, award_id, payload, headers):
        return self._request("POST", f"/api/awards/{award_id}/suspend", payload, headers)

    def reinstate_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/reinstate", {}, headers)

    def initiate_closeout(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/initiate-closeout", {}, headers)

    def reopen_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/reopen", {}, headers)

    def close_award(self, award_id, headers):
        return self._request("POST", f"/api/awards/{award_id}/close", {}, headers)

    def get_receivables_aging(self, award_id, headers):
        return self._request("GET", f"/api/awards/{award_id}/receivables-aging", headers=headers)

    # --- budget lines ---
    def create_budget_line(self, payload, headers):
        return self._request("POST", "/api/budget-lines", payload, headers)

    def list_budget_lines(self, headers, params=None):
        return self._request("GET", "/api/budget-lines", headers=headers, params=params)

    def get_budget_line(self, line_id, headers):
        return self._request("GET", f"/api/budget-lines/{line_id}", headers=headers)

    # --- effort commitments ---
    def create_effort_commitment(self, payload, headers):
        return self._request("POST", "/api/effort-commitments", payload, headers)

    def list_effort_commitments(self, headers, params=None):
        return self._request("GET", "/api/effort-commitments", headers=headers, params=params)

    def get_effort_commitment(self, commitment_id, headers):
        return self._request("GET", f"/api/effort-commitments/{commitment_id}", headers=headers)

    # --- expenditures ---
    def create_expenditure(self, payload, headers):
        return self._request("POST", "/api/expenditures", payload, headers)

    def list_expenditures(self, headers, params=None):
        return self._request("GET", "/api/expenditures", headers=headers, params=params)

    def get_expenditure(self, expenditure_id, headers):
        return self._request("GET", f"/api/expenditures/{expenditure_id}", headers=headers)

    def post_expenditure(self, expenditure_id, headers):
        return self._request("POST", f"/api/expenditures/{expenditure_id}/post", {}, headers)

    def disallow_expenditure(self, expenditure_id, payload, headers):
        return self._request("POST", f"/api/expenditures/{expenditure_id}/disallow", payload, headers)

    def resubmit_expenditure(self, expenditure_id, payload, headers):
        return self._request("POST", f"/api/expenditures/{expenditure_id}/resubmit", payload, headers)

    # --- cost transfers ---
    def create_cost_transfer(self, payload, headers):
        return self._request("POST", "/api/cost-transfers", payload, headers)

    def list_cost_transfers(self, headers, params=None):
        return self._request("GET", "/api/cost-transfers", headers=headers, params=params)

    def get_cost_transfer(self, transfer_id, headers):
        return self._request("GET", f"/api/cost-transfers/{transfer_id}", headers=headers)

    def submit_cost_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/cost-transfers/{transfer_id}/submit", payload, headers)

    def approve_cost_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/cost-transfers/{transfer_id}/approve", {}, headers)

    def countersign_cost_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/cost-transfers/{transfer_id}/countersign", {}, headers)

    def deny_cost_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/cost-transfers/{transfer_id}/deny", payload, headers)

    def revise_cost_transfer(self, transfer_id, payload, headers):
        return self._request("POST", f"/api/cost-transfers/{transfer_id}/revise", payload, headers)

    # --- effort cycles ---
    def create_effort_cycle(self, payload, headers):
        return self._request("POST", "/api/effort-cycles", payload, headers)

    def list_effort_cycles(self, headers, params=None):
        return self._request("GET", "/api/effort-cycles", headers=headers, params=params)

    def get_effort_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/effort-cycles/{cycle_id}", headers=headers)

    def open_effort_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/effort-cycles/{cycle_id}/open", {}, headers)

    def close_effort_cycle(self, cycle_id, payload, headers):
        return self._request("POST", f"/api/effort-cycles/{cycle_id}/close", payload, headers)

    # --- effort statements ---
    def list_effort_statements(self, headers, params=None):
        return self._request("GET", "/api/effort-statements", headers=headers, params=params)

    def get_effort_statement(self, statement_id, headers):
        return self._request("GET", f"/api/effort-statements/{statement_id}", headers=headers)

    def certify_effort_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/api/effort-statements/{statement_id}/certify", payload, headers)

    def reopen_effort_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/api/effort-statements/{statement_id}/reopen", payload, headers)

    # --- subawards ---
    def create_subaward(self, payload, headers):
        return self._request("POST", "/api/subawards", payload, headers)

    def list_subawards(self, headers, params=None):
        return self._request("GET", "/api/subawards", headers=headers, params=params)

    def get_subaward(self, subaward_id, headers):
        return self._request("GET", f"/api/subawards/{subaward_id}", headers=headers)

    def activate_subaward(self, subaward_id, headers):
        return self._request("POST", f"/api/subawards/{subaward_id}/activate", {}, headers)

    def close_subaward(self, subaward_id, headers):
        return self._request("POST", f"/api/subawards/{subaward_id}/close", {}, headers)

    # --- subaward invoices ---
    def create_subaward_invoice(self, payload, headers):
        return self._request("POST", "/api/subaward-invoices", payload, headers)

    def list_subaward_invoices(self, headers, params=None):
        return self._request("GET", "/api/subaward-invoices", headers=headers, params=params)

    def get_subaward_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/subaward-invoices/{invoice_id}", headers=headers)

    def begin_review_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/subaward-invoices/{invoice_id}/begin-review", {}, headers)

    def approve_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/subaward-invoices/{invoice_id}/approve", payload, headers)

    def reject_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/subaward-invoices/{invoice_id}/reject", payload, headers)

    def return_invoice_for_revision(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/subaward-invoices/{invoice_id}/return-for-revision", payload, headers)

    def resubmit_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/api/subaward-invoices/{invoice_id}/resubmit", payload, headers)

    # --- report requirements ---
    def create_report_requirement(self, payload, headers):
        return self._request("POST", "/api/report-requirements", payload, headers)

    def list_report_requirements(self, headers, params=None):
        return self._request("GET", "/api/report-requirements", headers=headers, params=params)

    def get_report_requirement(self, report_id, headers):
        return self._request("GET", f"/api/report-requirements/{report_id}", headers=headers)

    def submit_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/report-requirements/{report_id}/submit", payload, headers)

    def accept_report(self, report_id, headers):
        return self._request("POST", f"/api/report-requirements/{report_id}/accept", {}, headers)

    def reject_report(self, report_id, payload, headers):
        return self._request("POST", f"/api/report-requirements/{report_id}/reject", payload, headers)

    # --- drawdown requests ---
    def create_drawdown_request(self, payload, headers):
        return self._request("POST", "/api/drawdown-requests", payload, headers)

    def list_drawdown_requests(self, headers, params=None):
        return self._request("GET", "/api/drawdown-requests", headers=headers, params=params)

    def get_drawdown_request(self, drawdown_id, headers):
        return self._request("GET", f"/api/drawdown-requests/{drawdown_id}", headers=headers)

    def submit_drawdown(self, drawdown_id, headers):
        return self._request("POST", f"/api/drawdown-requests/{drawdown_id}/submit", {}, headers)

    def settle_drawdown(self, drawdown_id, headers):
        return self._request("POST", f"/api/drawdown-requests/{drawdown_id}/settle", {}, headers)

    def reject_drawdown(self, drawdown_id, payload, headers):
        return self._request("POST", f"/api/drawdown-requests/{drawdown_id}/reject", payload, headers)

    # --- receivables ---
    def create_receivable(self, payload, headers):
        return self._request("POST", "/api/receivables", payload, headers)

    def list_receivables(self, headers, params=None):
        return self._request("GET", "/api/receivables", headers=headers, params=params)

    def get_receivable(self, receivable_id, headers):
        return self._request("GET", f"/api/receivables/{receivable_id}", headers=headers)

    def record_payment(self, receivable_id, payload, headers):
        return self._request("POST", f"/api/receivables/{receivable_id}/payments", payload, headers)

    def dispute_receivable(self, receivable_id, payload, headers):
        return self._request("POST", f"/api/receivables/{receivable_id}/dispute", payload, headers)

    def resolve_dispute(self, receivable_id, headers):
        return self._request("POST", f"/api/receivables/{receivable_id}/resolve-dispute", {}, headers)

    # --- modification requests ---
    def create_modification_request(self, payload, headers):
        return self._request("POST", "/api/modification-requests", payload, headers)

    def list_modification_requests(self, headers, params=None):
        return self._request("GET", "/api/modification-requests", headers=headers, params=params)

    def get_modification_request(self, modification_id, headers):
        return self._request("GET", f"/api/modification-requests/{modification_id}", headers=headers)

    def submit_modification(self, modification_id, headers):
        return self._request("POST", f"/api/modification-requests/{modification_id}/submit", {}, headers)

    def internal_approve_modification(self, modification_id, headers):
        return self._request("POST", f"/api/modification-requests/{modification_id}/internal-approve", {}, headers)

    def sponsor_decision_modification(self, modification_id, payload, headers):
        return self._request("POST", f"/api/modification-requests/{modification_id}/sponsor-decision", payload, headers)

    def withdraw_modification(self, modification_id, headers):
        return self._request("POST", f"/api/modification-requests/{modification_id}/withdraw", {}, headers)

    # --- final financial reports ---
    def list_final_financial_reports(self, headers, params=None):
        return self._request("GET", "/api/final-financial-reports", headers=headers, params=params)

    def get_final_financial_report(self, ffr_id, headers):
        return self._request("GET", f"/api/final-financial-reports/{ffr_id}", headers=headers)

    def submit_ffr(self, ffr_id, payload, headers):
        return self._request("POST", f"/api/final-financial-reports/{ffr_id}/submit", payload, headers)

    def accept_ffr(self, ffr_id, headers):
        return self._request("POST", f"/api/final-financial-reports/{ffr_id}/accept", {}, headers)

    def return_ffr(self, ffr_id, payload, headers):
        return self._request("POST", f"/api/final-financial-reports/{ffr_id}/return", payload, headers)


api_client = ApiClient()
