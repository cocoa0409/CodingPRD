"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/litigation/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Staff users
    # ------------------------------------------------------------------
    def create_staff_user(self, payload, headers):
        return self._request("POST", "/litigation/staff-users", payload, headers)

    def list_staff_users(self, headers, params=None):
        return self._request("GET", "/litigation/staff-users", headers=headers, params=params)

    def get_staff_user(self, user_id, headers):
        return self._request("GET", f"/litigation/staff-users/{user_id}", headers=headers)

    def list_staff_custodianships(self, user_id, headers, params=None):
        return self._request("GET", f"/litigation/staff-users/{user_id}/custodianships",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Counsel firms
    # ------------------------------------------------------------------
    def create_counsel_firm(self, payload, headers):
        return self._request("POST", "/litigation/counsel-firms", payload, headers)

    def list_counsel_firms(self, headers, params=None):
        return self._request("GET", "/litigation/counsel-firms", headers=headers, params=params)

    def get_counsel_firm(self, firm_id, headers):
        return self._request("GET", f"/litigation/counsel-firms/{firm_id}", headers=headers)

    def conflict_check_firm(self, firm_id, result, headers):
        return self._request("POST", f"/litigation/counsel-firms/{firm_id}/conflict-check",
                             {"result": result}, headers)

    def approve_panel_firm(self, firm_id, headers):
        return self._request("POST", f"/litigation/counsel-firms/{firm_id}/approve-panel",
                             {}, headers)

    def suspend_firm(self, firm_id, headers):
        return self._request("POST", f"/litigation/counsel-firms/{firm_id}/suspend", {}, headers)

    def reinstate_firm(self, firm_id, headers):
        return self._request("POST", f"/litigation/counsel-firms/{firm_id}/reinstate", {}, headers)

    def terminate_firm(self, firm_id, headers):
        return self._request("POST", f"/litigation/counsel-firms/{firm_id}/terminate", {}, headers)

    def list_firm_engagements(self, firm_id, headers, params=None):
        return self._request("GET", f"/litigation/counsel-firms/{firm_id}/engagements",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Matters
    # ------------------------------------------------------------------
    def create_matter(self, payload, headers):
        return self._request("POST", "/litigation/matters", payload, headers)

    def list_matters(self, headers, params=None):
        return self._request("GET", "/litigation/matters", headers=headers, params=params)

    def get_matter(self, matter_id, headers):
        return self._request("GET", f"/litigation/matters/{matter_id}", headers=headers)

    def patch_matter(self, matter_id, payload, headers):
        return self._request("PATCH", f"/litigation/matters/{matter_id}", payload, headers)

    def submit_assessment(self, matter_id, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/submit-assessment",
                             {}, headers)

    def advance_to_staffing(self, matter_id, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/advance-to-staffing",
                             {}, headers)

    def activate_matter(self, matter_id, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/activate", {}, headers)

    def resolve_matter(self, matter_id, resolution_type, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/resolve",
                             {"resolution_type": resolution_type}, headers)

    def reopen_matter(self, matter_id, reopen_reason, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/reopen",
                             {"reopen_reason": reopen_reason}, headers)

    def close_matter(self, matter_id, close_checklist_ack, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/close",
                             {"close_checklist_ack": close_checklist_ack}, headers)

    def get_matter_summary(self, matter_id, headers):
        return self._request("GET", f"/litigation/matters/{matter_id}/summary", headers=headers)

    # ------------------------------------------------------------------
    # Engagements
    # ------------------------------------------------------------------
    def create_engagement(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/engagements",
                             payload, headers)

    def list_matter_engagements(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/engagements",
                             headers=headers, params=params)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/litigation/engagements", headers=headers, params=params)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/litigation/engagements/{engagement_id}", headers=headers)

    def patch_engagement(self, engagement_id, payload, headers):
        return self._request("PATCH", f"/litigation/engagements/{engagement_id}", payload, headers)

    def approve_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/approve",
                             {}, headers)

    def reject_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/reject",
                             {}, headers)

    def activate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/activate",
                             {}, headers)

    def suspend_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/suspend",
                             {}, headers)

    def reinstate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/reinstate",
                             {}, headers)

    def terminate_engagement(self, engagement_id, headers):
        return self._request("POST", f"/litigation/engagements/{engagement_id}/terminate",
                             {}, headers)

    # ------------------------------------------------------------------
    # Budgets
    # ------------------------------------------------------------------
    def create_budget(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/budgets",
                             payload, headers)

    def list_matter_budgets(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/budgets",
                             headers=headers, params=params)

    def list_budgets(self, headers, params=None):
        return self._request("GET", "/litigation/budgets", headers=headers, params=params)

    def get_budget(self, budget_id, headers):
        return self._request("GET", f"/litigation/budgets/{budget_id}", headers=headers)

    def submit_budget(self, budget_id, headers):
        return self._request("POST", f"/litigation/budgets/{budget_id}/submit", {}, headers)

    def approve_budget(self, budget_id, headers):
        return self._request("POST", f"/litigation/budgets/{budget_id}/approve", {}, headers)

    def reject_budget(self, budget_id, headers):
        return self._request("POST", f"/litigation/budgets/{budget_id}/reject", {}, headers)

    # ------------------------------------------------------------------
    # Accrual entries
    # ------------------------------------------------------------------
    def create_accrual_entry(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/accrual-entries",
                             payload, headers)

    def list_matter_accrual_entries(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/accrual-entries",
                             headers=headers, params=params)

    def list_engagement_accrual_entries(self, engagement_id, headers, params=None):
        return self._request("GET", f"/litigation/engagements/{engagement_id}/accrual-entries",
                             headers=headers, params=params)

    def list_accrual_entries(self, headers, params=None):
        return self._request("GET", "/litigation/accrual-entries", headers=headers, params=params)

    def get_accrual_entry(self, entry_id, headers):
        return self._request("GET", f"/litigation/accrual-entries/{entry_id}", headers=headers)

    def submit_accrual_entry(self, entry_id, headers):
        return self._request("POST", f"/litigation/accrual-entries/{entry_id}/submit",
                             {}, headers)

    def post_accrual_entry(self, entry_id, headers):
        return self._request("POST", f"/litigation/accrual-entries/{entry_id}/post", {}, headers)

    def void_accrual_entry(self, entry_id, headers):
        return self._request("POST", f"/litigation/accrual-entries/{entry_id}/void", {}, headers)

    # ------------------------------------------------------------------
    # Litigation holds and custodians
    # ------------------------------------------------------------------
    def create_hold(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/holds", payload, headers)

    def list_matter_holds(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/holds",
                             headers=headers, params=params)

    def get_hold(self, hold_id, headers):
        return self._request("GET", f"/litigation/holds/{hold_id}", headers=headers)

    def issue_hold(self, hold_id, headers):
        return self._request("POST", f"/litigation/holds/{hold_id}/issue", {}, headers)

    def release_hold(self, hold_id, release_reason, headers):
        return self._request("POST", f"/litigation/holds/{hold_id}/release",
                             {"release_reason": release_reason}, headers)

    def add_custodian(self, hold_id, staff_user_id, headers):
        return self._request("POST", f"/litigation/holds/{hold_id}/custodians",
                             {"staff_user_id": staff_user_id}, headers)

    def list_hold_custodians(self, hold_id, headers, params=None):
        return self._request("GET", f"/litigation/holds/{hold_id}/custodians",
                             headers=headers, params=params)

    def get_custodian(self, custodian_id, headers):
        return self._request("GET", f"/litigation/hold-custodians/{custodian_id}", headers=headers)

    def acknowledge_custodian(self, custodian_id, headers):
        return self._request("POST", f"/litigation/hold-custodians/{custodian_id}/acknowledge",
                             {}, headers)

    def escalate_custodian(self, custodian_id, headers):
        return self._request("POST", f"/litigation/hold-custodians/{custodian_id}/escalate",
                             {}, headers)

    def exempt_custodian(self, custodian_id, exemption_reason, headers):
        return self._request("POST", f"/litigation/hold-custodians/{custodian_id}/exempt",
                             {"exemption_reason": exemption_reason}, headers)

    # ------------------------------------------------------------------
    # Discovery vendors and work orders
    # ------------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/litigation/discovery-vendors", payload, headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/litigation/discovery-vendors", headers=headers, params=params)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/litigation/discovery-vendors/{vendor_id}", headers=headers)

    def list_vendor_work_orders(self, vendor_id, headers, params=None):
        return self._request("GET", f"/litigation/discovery-vendors/{vendor_id}/work-orders",
                             headers=headers, params=params)

    def create_work_order(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/work-orders",
                             payload, headers)

    def list_matter_work_orders(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/work-orders",
                             headers=headers, params=params)

    def list_hold_work_orders(self, hold_id, headers, params=None):
        return self._request("GET", f"/litigation/holds/{hold_id}/work-orders",
                             headers=headers, params=params)

    def get_work_order(self, work_order_id, headers):
        return self._request("GET", f"/litigation/work-orders/{work_order_id}", headers=headers)

    def authorize_work_order(self, work_order_id, headers):
        return self._request("POST", f"/litigation/work-orders/{work_order_id}/authorize",
                             {}, headers)

    def start_work_order(self, work_order_id, headers):
        return self._request("POST", f"/litigation/work-orders/{work_order_id}/start",
                             {}, headers)

    def complete_work_order(self, work_order_id, actual_gb, headers):
        return self._request("POST", f"/litigation/work-orders/{work_order_id}/complete",
                             {"actual_gb": actual_gb}, headers)

    def cancel_work_order(self, work_order_id, headers):
        return self._request("POST", f"/litigation/work-orders/{work_order_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Deadlines
    # ------------------------------------------------------------------
    def create_deadline(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/deadlines",
                             payload, headers)

    def list_matter_deadlines(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/deadlines",
                             headers=headers, params=params)

    def get_deadline(self, deadline_id, headers):
        return self._request("GET", f"/litigation/deadlines/{deadline_id}", headers=headers)

    def mark_deadline_met(self, deadline_id, headers):
        return self._request("POST", f"/litigation/deadlines/{deadline_id}/mark-met", {}, headers)

    def mark_deadline_missed(self, deadline_id, headers):
        return self._request("POST", f"/litigation/deadlines/{deadline_id}/mark-missed",
                             {}, headers)

    def vacate_deadline(self, deadline_id, headers, court_order_reference=None):
        payload = {}
        if court_order_reference is not None:
            payload["court_order_reference"] = court_order_reference
        return self._request("POST", f"/litigation/deadlines/{deadline_id}/vacate",
                             payload, headers)

    # ------------------------------------------------------------------
    # Settlement authority policies
    # ------------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/litigation/settlement-authority-policies",
                             payload, headers)

    def list_policies(self, headers, params=None):
        return self._request("GET", "/litigation/settlement-authority-policies",
                             headers=headers, params=params)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/litigation/settlement-authority-policies/{policy_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Settlement requests
    # ------------------------------------------------------------------
    def create_settlement_request(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/settlement-requests",
                             payload, headers)

    def list_matter_settlement_requests(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/settlement-requests",
                             headers=headers, params=params)

    def list_settlement_requests(self, headers, params=None):
        return self._request("GET", "/litigation/settlement-requests",
                             headers=headers, params=params)

    def get_settlement_request(self, request_id, headers):
        return self._request("GET", f"/litigation/settlement-requests/{request_id}",
                             headers=headers)

    def submit_settlement(self, request_id, headers):
        return self._request("POST", f"/litigation/settlement-requests/{request_id}/submit",
                             {}, headers)

    def begin_review_settlement(self, request_id, headers):
        return self._request("POST", f"/litigation/settlement-requests/{request_id}/begin-review",
                             {}, headers)

    def approve_settlement(self, request_id, headers):
        return self._request("POST", f"/litigation/settlement-requests/{request_id}/approve",
                             {}, headers)

    def counter_settlement(self, request_id, counter_amount_cents, headers):
        return self._request("POST", f"/litigation/settlement-requests/{request_id}/counter",
                             {"counter_amount_cents": counter_amount_cents}, headers)

    def accept_counter_settlement(self, request_id, headers):
        return self._request("POST",
                             f"/litigation/settlement-requests/{request_id}/accept-counter",
                             {}, headers)

    def reject_settlement(self, request_id, headers):
        return self._request("POST", f"/litigation/settlement-requests/{request_id}/reject",
                             {}, headers)

    def execute_settlement(self, request_id, headers):
        return self._request("POST", f"/litigation/settlement-requests/{request_id}/execute",
                             {}, headers)

    def withdraw_settlement(self, request_id, headers):
        return self._request("POST", f"/litigation/settlement-requests/{request_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Payment requests
    # ------------------------------------------------------------------
    def create_payment_request(self, matter_id, payload, headers):
        return self._request("POST", f"/litigation/matters/{matter_id}/payment-requests",
                             payload, headers)

    def list_matter_payment_requests(self, matter_id, headers, params=None):
        return self._request("GET", f"/litigation/matters/{matter_id}/payment-requests",
                             headers=headers, params=params)

    def list_settlement_payment_requests(self, request_id, headers, params=None):
        return self._request("GET",
                             f"/litigation/settlement-requests/{request_id}/payment-requests",
                             headers=headers, params=params)

    def list_payment_requests(self, headers, params=None):
        return self._request("GET", "/litigation/payment-requests", headers=headers, params=params)

    def get_payment_request(self, payment_id, headers):
        return self._request("GET", f"/litigation/payment-requests/{payment_id}", headers=headers)

    def submit_payment(self, payment_id, headers):
        return self._request("POST", f"/litigation/payment-requests/{payment_id}/submit",
                             {}, headers)

    def finance_approve_payment(self, payment_id, headers):
        return self._request("POST",
                             f"/litigation/payment-requests/{payment_id}/finance-approve",
                             {}, headers)

    def disburse_payment(self, payment_id, headers):
        return self._request("POST", f"/litigation/payment-requests/{payment_id}/disburse",
                             {}, headers)

    def confirm_receipt_payment(self, payment_id, headers):
        return self._request("POST",
                             f"/litigation/payment-requests/{payment_id}/confirm-receipt",
                             {}, headers)

    def mark_returned_payment(self, payment_id, headers):
        return self._request("POST",
                             f"/litigation/payment-requests/{payment_id}/mark-returned",
                             {}, headers)

    def redisburse_payment(self, payment_id, headers):
        return self._request("POST", f"/litigation/payment-requests/{payment_id}/redisburse",
                             {}, headers)

    def reject_payment(self, payment_id, headers):
        return self._request("POST", f"/litigation/payment-requests/{payment_id}/reject",
                             {}, headers)

    def cancel_payment(self, payment_id, headers):
        return self._request("POST", f"/litigation/payment-requests/{payment_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------
    def get_portfolio_report(self, headers, params=None):
        return self._request("GET", "/litigation/reports/portfolio",
                             headers=headers, params=params)


api_client = ApiClient()
