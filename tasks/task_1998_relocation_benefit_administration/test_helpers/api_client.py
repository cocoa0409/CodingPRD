"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Employees
    # ------------------------------------------------------------------
    def create_employee(self, payload, headers):
        return self._request("POST", "/employees", payload, headers)

    def get_employee(self, employee_id, headers):
        return self._request("GET", f"/employees/{employee_id}", headers=headers)

    def terminate_employee(self, employee_id, headers):
        return self._request("POST", f"/employees/{employee_id}/terminate", {}, headers)

    # ------------------------------------------------------------------
    # Policy tiers
    # ------------------------------------------------------------------
    def create_policy(self, payload, headers):
        return self._request("POST", "/policies", payload, headers)

    def get_policy(self, policy_id, headers):
        return self._request("GET", f"/policies/{policy_id}", headers=headers)

    # ------------------------------------------------------------------
    # Vendors
    # ------------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    # ------------------------------------------------------------------
    # Relocation cases
    # ------------------------------------------------------------------
    def create_case(self, payload, headers):
        return self._request("POST", "/relocation-cases", payload, headers)

    def get_case(self, case_id, headers):
        return self._request("GET", f"/relocation-cases/{case_id}", headers=headers)

    def list_cases(self, headers, params=None):
        return self._request("GET", "/relocation-cases", headers=headers, params=params)

    def authorize_case(self, case_id, headers):
        return self._request("POST", f"/relocation-cases/{case_id}/authorize", {}, headers)

    def start_case(self, case_id, headers):
        return self._request("POST", f"/relocation-cases/{case_id}/start", {}, headers)

    def cancel_case(self, case_id, headers):
        return self._request("POST", f"/relocation-cases/{case_id}/cancel", {}, headers)

    def terminate_early_case(self, case_id, headers):
        return self._request("POST", f"/relocation-cases/{case_id}/terminate-early", {}, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/relocation-cases/{case_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Move assignments (household goods)
    # ------------------------------------------------------------------
    def create_move_assignment(self, payload, headers):
        return self._request("POST", "/move-assignments", payload, headers)

    def get_move_assignment(self, assignment_id, headers):
        return self._request("GET", f"/move-assignments/{assignment_id}", headers=headers)

    def list_move_assignments(self, headers, params=None):
        return self._request("GET", "/move-assignments", headers=headers, params=params)

    def schedule_survey(self, assignment_id, payload, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/schedule-survey", payload, headers)

    def submit_estimate(self, assignment_id, payload, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/submit-estimate", payload, headers)

    def approve_estimate(self, assignment_id, payload, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/approve-estimate", payload, headers)

    def reject_estimate(self, assignment_id, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/reject-estimate", {}, headers)

    def mark_delivered(self, assignment_id, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/mark-delivered", {}, headers)

    def submit_invoice(self, assignment_id, payload, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/submit-invoice", payload, headers)

    def mark_paid(self, assignment_id, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/mark-paid", {}, headers)

    def rate_assignment(self, assignment_id, payload, headers):
        return self._request("POST", f"/move-assignments/{assignment_id}/rate", payload, headers)

    # ------------------------------------------------------------------
    # Service bookings (temp housing + travel)
    # ------------------------------------------------------------------
    def create_service_booking(self, payload, headers):
        return self._request("POST", "/service-bookings", payload, headers)

    def get_service_booking(self, booking_id, headers):
        return self._request("GET", f"/service-bookings/{booking_id}", headers=headers)

    def list_case_service_bookings(self, case_id, headers, params=None):
        return self._request("GET", f"/relocation-cases/{case_id}/service-bookings",
                             headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/service-bookings/{booking_id}/confirm", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/service-bookings/{booking_id}/cancel", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/service-bookings/{booking_id}/complete", {}, headers)

    # ------------------------------------------------------------------
    # Expense claims
    # ------------------------------------------------------------------
    def create_expense_claim(self, payload, headers):
        return self._request("POST", "/expense-claims", payload, headers)

    def get_expense_claim(self, claim_id, headers):
        return self._request("GET", f"/expense-claims/{claim_id}", headers=headers)

    def list_case_expense_claims(self, case_id, headers, params=None):
        return self._request("GET", f"/relocation-cases/{case_id}/expense-claims",
                             headers=headers, params=params)

    def approve_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/expense-claims/{claim_id}/approve", payload, headers)

    def reject_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/expense-claims/{claim_id}/reject", payload, headers)

    def resubmit_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/expense-claims/{claim_id}/resubmit", payload, headers)

    def pay_claim(self, claim_id, headers):
        return self._request("POST", f"/expense-claims/{claim_id}/pay", {}, headers)

    # ------------------------------------------------------------------
    # Home sale / loss on sale
    # ------------------------------------------------------------------
    def create_home_sale(self, payload, headers):
        return self._request("POST", "/home-sales", payload, headers)

    def get_home_sale(self, home_sale_id, headers):
        return self._request("GET", f"/home-sales/{home_sale_id}", headers=headers)

    def list_case_home_sales(self, case_id, headers, params=None):
        return self._request("GET", f"/relocation-cases/{case_id}/home-sales",
                             headers=headers, params=params)

    def record_sale(self, home_sale_id, payload, headers):
        return self._request("POST", f"/home-sales/{home_sale_id}/record-sale", payload, headers)

    def settle_home_sale(self, home_sale_id, headers):
        return self._request("POST", f"/home-sales/{home_sale_id}/settle", {}, headers)

    # ------------------------------------------------------------------
    # Repayment agreements
    # ------------------------------------------------------------------
    def get_repayment_agreement(self, agreement_id, headers):
        return self._request("GET", f"/repayment-agreements/{agreement_id}", headers=headers)

    def list_case_repayment_agreements(self, case_id, headers, params=None):
        return self._request("GET", f"/relocation-cases/{case_id}/repayment-agreements",
                             headers=headers, params=params)

    def sign_agreement(self, agreement_id, headers):
        return self._request("POST", f"/repayment-agreements/{agreement_id}/sign", {}, headers)

    def record_payment(self, agreement_id, payload, headers):
        return self._request("POST", f"/repayment-agreements/{agreement_id}/payments", payload, headers)

    def reverse_payment(self, agreement_id, payload, headers):
        return self._request("POST", f"/repayment-agreements/{agreement_id}/reverse-payment", payload, headers)

    def mark_default(self, agreement_id, headers):
        return self._request("POST", f"/repayment-agreements/{agreement_id}/mark-default", {}, headers)

    # ------------------------------------------------------------------
    # Exception requests
    # ------------------------------------------------------------------
    def create_exception_request(self, payload, headers):
        return self._request("POST", "/exception-requests", payload, headers)

    def get_exception_request(self, request_id, headers):
        return self._request("GET", f"/exception-requests/{request_id}", headers=headers)

    def list_case_exception_requests(self, case_id, headers, params=None):
        return self._request("GET", f"/relocation-cases/{case_id}/exception-requests",
                             headers=headers, params=params)

    def approve_exception(self, request_id, payload, headers):
        return self._request("POST", f"/exception-requests/{request_id}/approve", payload, headers)

    def reject_exception(self, request_id, payload, headers):
        return self._request("POST", f"/exception-requests/{request_id}/reject", payload, headers)

    def appeal_exception(self, request_id, headers):
        return self._request("POST", f"/exception-requests/{request_id}/appeal", {}, headers)

    # ------------------------------------------------------------------
    # Test-driving clock
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
