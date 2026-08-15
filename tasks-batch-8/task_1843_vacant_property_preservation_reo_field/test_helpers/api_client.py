"""API client: one method per endpoint defined in the PRD endpoint catalogue."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock / ops ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/preservation/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    def run_daily_sweep(self, headers):
        return self._request("POST", "/preservation/ops/run-daily-sweep", {}, headers)

    # --- Servicer ---
    def create_servicer(self, payload, headers):
        return self._request("POST", "/preservation/servicers", payload, headers)

    def get_servicer(self, servicer_id, headers):
        return self._request("GET", f"/preservation/servicers/{servicer_id}", headers=headers)

    # --- Crew ---
    def create_crew(self, payload, headers):
        return self._request("POST", "/preservation/crews", payload, headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/preservation/crews/{crew_id}", headers=headers)

    # --- InvestorAllowable ---
    def create_investor_allowable(self, payload, headers):
        return self._request("POST", "/preservation/investor-allowables", payload, headers)

    def get_investor_allowable(self, allowable_id, headers):
        return self._request("GET", f"/preservation/investor-allowables/{allowable_id}", headers=headers)

    def update_investor_allowable(self, allowable_id, payload, headers):
        return self._request("PATCH", f"/preservation/investor-allowables/{allowable_id}", payload, headers)

    # --- Property ---
    def create_property(self, payload, headers):
        return self._request("POST", "/preservation/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/preservation/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/preservation/properties", headers=headers, params=params)

    def convey_property(self, property_id, headers):
        return self._request("POST", f"/preservation/properties/{property_id}/convey", {}, headers)

    def clear_financial_review(self, property_id, headers):
        return self._request("POST", f"/preservation/properties/{property_id}/clear-financial-review", {}, headers)

    # --- WorkOrder ---
    def create_work_order(self, payload, headers):
        return self._request("POST", "/preservation/work-orders", payload, headers)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/preservation/work-orders/{work_order_id}", headers=headers)

    def list_work_orders(self, headers, params=None):
        return self._request("GET", "/preservation/work-orders", headers=headers, params=params)

    def assign_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/assign", payload, headers)

    def reassign_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/reassign", payload, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/start", {}, headers)

    def submit_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/submit", payload, headers)

    def approve_work_order(self, work_order_id, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/approve", {}, headers)

    def reject_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/reject", payload, headers)

    def cancel_work_order(self, work_order_id, payload, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/cancel", payload, headers)

    def complete_work_order(self, work_order_id, headers):
        return self._request("POST", f"/preservation/work-orders/{work_order_id}/complete", {}, headers)

    # --- Inspection ---
    def create_inspection(self, payload, headers):
        return self._request("POST", "/preservation/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/preservation/inspections/{inspection_id}", headers=headers)

    def list_inspections(self, headers, params=None):
        return self._request("GET", "/preservation/inspections", headers=headers, params=params)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/preservation/inspections/{inspection_id}/record", payload, headers)

    def verify_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"/preservation/inspections/{inspection_id}/verify", payload, headers)

    # --- PersonalPropertyDisposition ---
    def create_disposition(self, payload, headers):
        return self._request("POST", "/preservation/personal-property-dispositions", payload, headers)

    def get_disposition(self, disposition_id, headers):
        return self._request("GET", f"/preservation/personal-property-dispositions/{disposition_id}", headers=headers)

    def list_dispositions(self, headers, params=None):
        return self._request("GET", "/preservation/personal-property-dispositions", headers=headers, params=params)

    def authorize_disposal(self, disposition_id, headers):
        return self._request("POST", f"/preservation/personal-property-dispositions/{disposition_id}/authorize-disposal", {}, headers)

    def dispose_disposition(self, disposition_id, payload, headers):
        return self._request("POST", f"/preservation/personal-property-dispositions/{disposition_id}/dispose", payload, headers)

    # --- RecurringServicePlan ---
    def create_recurring_plan(self, payload, headers):
        return self._request("POST", "/preservation/recurring-plans", payload, headers)

    def get_recurring_plan(self, plan_id, headers):
        return self._request("GET", f"/preservation/recurring-plans/{plan_id}", headers=headers)

    def list_recurring_plans(self, headers, params=None):
        return self._request("GET", "/preservation/recurring-plans", headers=headers, params=params)

    def suspend_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/preservation/recurring-plans/{plan_id}/suspend", {}, headers)

    def resume_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/preservation/recurring-plans/{plan_id}/resume", {}, headers)

    def end_recurring_plan(self, plan_id, headers):
        return self._request("POST", f"/preservation/recurring-plans/{plan_id}/end", {}, headers)

    # --- CodeViolation ---
    def create_code_violation(self, payload, headers):
        return self._request("POST", "/preservation/code-violations", payload, headers)

    def get_code_violation(self, violation_id, headers):
        return self._request("GET", f"/preservation/code-violations/{violation_id}", headers=headers)

    def list_code_violations(self, headers, params=None):
        return self._request("GET", "/preservation/code-violations", headers=headers, params=params)

    def start_cure(self, violation_id, payload, headers):
        return self._request("POST", f"/preservation/code-violations/{violation_id}/start-cure", payload, headers)

    def submit_cure(self, violation_id, headers):
        return self._request("POST", f"/preservation/code-violations/{violation_id}/submit-cure", {}, headers)

    def verify_code_violation(self, violation_id, headers):
        return self._request("POST", f"/preservation/code-violations/{violation_id}/verify", {}, headers)

    def reject_cure(self, violation_id, payload, headers):
        return self._request("POST", f"/preservation/code-violations/{violation_id}/reject-cure", payload, headers)

    # --- MunicipalRegistration ---
    def create_registration(self, payload, headers):
        return self._request("POST", "/preservation/registrations", payload, headers)

    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/preservation/registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/preservation/registrations", headers=headers, params=params)

    def activate_registration(self, registration_id, headers):
        return self._request("POST", f"/preservation/registrations/{registration_id}/activate", {}, headers)

    def renew_registration(self, registration_id, payload, headers):
        return self._request("POST", f"/preservation/registrations/{registration_id}/renew", payload, headers)

    def release_registration(self, registration_id, headers):
        return self._request("POST", f"/preservation/registrations/{registration_id}/release", {}, headers)

    # --- DamageReport ---
    def create_damage_report(self, payload, headers):
        return self._request("POST", "/preservation/damage-reports", payload, headers)

    def get_damage_report(self, report_id, headers):
        return self._request("GET", f"/preservation/damage-reports/{report_id}", headers=headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", "/preservation/damage-reports", headers=headers, params=params)

    def triage_damage_report(self, report_id, headers):
        return self._request("POST", f"/preservation/damage-reports/{report_id}/triage", {}, headers)

    def request_bids(self, report_id, headers):
        return self._request("POST", f"/preservation/damage-reports/{report_id}/request-bids", {}, headers)

    def close_damage_report(self, report_id, payload, headers):
        return self._request("POST", f"/preservation/damage-reports/{report_id}/close", payload, headers)

    # --- Bid ---
    def create_bid(self, damage_report_id, payload, headers):
        return self._request("POST", f"/preservation/damage-reports/{damage_report_id}/bids", payload, headers)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/preservation/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/preservation/bids", headers=headers, params=params)

    def submit_bid(self, bid_id, headers):
        return self._request("POST", f"/preservation/bids/{bid_id}/submit", {}, headers)

    def approve_bid(self, bid_id, headers):
        return self._request("POST", f"/preservation/bids/{bid_id}/approve", {}, headers)

    def counter_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/preservation/bids/{bid_id}/counter", payload, headers)

    def revise_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/preservation/bids/{bid_id}/revise", payload, headers)

    def reject_bid(self, bid_id, payload, headers):
        return self._request("POST", f"/preservation/bids/{bid_id}/reject", payload, headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request("POST", f"/preservation/bids/{bid_id}/withdraw", {}, headers)

    # --- PhotoEvidence ---
    def create_photo_evidence(self, payload, headers):
        return self._request("POST", "/preservation/photo-evidence", payload, headers)

    def get_photo_evidence(self, photo_id, headers):
        return self._request("GET", f"/preservation/photo-evidence/{photo_id}", headers=headers)

    def list_photo_evidence(self, headers, params=None):
        return self._request("GET", "/preservation/photo-evidence", headers=headers, params=params)

    def flag_photo(self, photo_id, payload, headers):
        return self._request("POST", f"/preservation/photo-evidence/{photo_id}/flag", payload, headers)

    def clear_photo_flag(self, photo_id, headers):
        return self._request("POST", f"/preservation/photo-evidence/{photo_id}/clear-flag", {}, headers)

    # --- Invoice / ExpenseLine ---
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/preservation/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/preservation/invoices", headers=headers, params=params)

    def add_expense_line(self, invoice_id, payload, headers):
        return self._request("POST", f"/preservation/invoices/{invoice_id}/lines", payload, headers)

    def list_invoice_lines(self, invoice_id, headers):
        return self._request("GET", f"/preservation/invoices/{invoice_id}/lines", headers=headers)

    def list_expense_lines(self, headers, params=None):
        return self._request("GET", "/preservation/expense-lines", headers=headers, params=params)

    def get_expense_line(self, expense_line_id, headers):
        return self._request("GET", f"/preservation/expense-lines/{expense_line_id}", headers=headers)

    def submit_invoice(self, invoice_id, headers):
        return self._request("POST", f"/preservation/invoices/{invoice_id}/submit", {}, headers)

    def approve_invoice(self, invoice_id, headers):
        return self._request("POST", f"/preservation/invoices/{invoice_id}/approve", {}, headers)

    def deny_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/preservation/invoices/{invoice_id}/deny", payload, headers)

    def appeal_invoice(self, invoice_id, headers):
        return self._request("POST", f"/preservation/invoices/{invoice_id}/appeal", {}, headers)

    def mark_invoice_paid(self, invoice_id, headers):
        return self._request("POST", f"/preservation/invoices/{invoice_id}/mark-paid", {}, headers)

    def void_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/preservation/invoices/{invoice_id}/void", payload, headers)


api_client = ApiClient()
