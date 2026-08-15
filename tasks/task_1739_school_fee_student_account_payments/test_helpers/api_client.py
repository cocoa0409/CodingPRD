"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # --- SchoolYear ---
    def create_school_year(self, payload, headers):
        return self._request("POST", "/school-years", payload, headers)

    def list_school_years(self, headers, params=None):
        return self._request("GET", "/school-years", headers=headers, params=params)

    def get_school_year(self, year_id, headers):
        return self._request("GET", f"/school-years/{year_id}", headers=headers)

    def open_school_year(self, year_id, headers):
        return self._request("POST", f"/school-years/{year_id}/open", headers=headers)

    def close_school_year(self, year_id, payload, headers):
        return self._request("POST", f"/school-years/{year_id}/close", payload, headers)

    def run_ops(self, year_id, headers):
        return self._request("POST", f"/school-years/{year_id}/ops-runs", headers=headers)

    # --- Department ---
    def create_department(self, year_id, payload, headers):
        return self._request("POST", f"/school-years/{year_id}/departments", payload, headers)

    def list_departments(self, year_id, headers, params=None):
        return self._request("GET", f"/school-years/{year_id}/departments", headers=headers, params=params)

    def get_department(self, year_id, department_id, headers):
        return self._request("GET", f"/school-years/{year_id}/departments/{department_id}", headers=headers)

    # --- FeeCatalogItem ---
    def create_fee_catalog_item(self, year_id, payload, headers):
        return self._request("POST", f"/school-years/{year_id}/fee-catalog-items", payload, headers)

    def list_fee_catalog_items(self, year_id, headers, params=None):
        return self._request("GET", f"/school-years/{year_id}/fee-catalog-items", headers=headers, params=params)

    def get_fee_catalog_item(self, year_id, item_id, headers):
        return self._request("GET", f"/school-years/{year_id}/fee-catalog-items/{item_id}", headers=headers)

    def retire_fee_catalog_item(self, year_id, item_id, headers):
        return self._request("POST", f"/school-years/{year_id}/fee-catalog-items/{item_id}/retire", headers=headers)

    # --- OptionalPurchaseItem ---
    def create_optional_purchase_item(self, year_id, payload, headers):
        return self._request("POST", f"/school-years/{year_id}/optional-purchase-items", payload, headers)

    def list_optional_purchase_items(self, year_id, headers, params=None):
        return self._request("GET", f"/school-years/{year_id}/optional-purchase-items", headers=headers, params=params)

    def get_optional_purchase_item(self, year_id, item_id, headers):
        return self._request("GET", f"/school-years/{year_id}/optional-purchase-items/{item_id}", headers=headers)

    # --- Offering ---
    def create_offering(self, year_id, payload, headers):
        return self._request("POST", f"/school-years/{year_id}/offerings", payload, headers)

    def list_offerings(self, year_id, headers, params=None):
        return self._request("GET", f"/school-years/{year_id}/offerings", headers=headers, params=params)

    def get_offering(self, year_id, offering_id, headers):
        return self._request("GET", f"/school-years/{year_id}/offerings/{offering_id}", headers=headers)

    def complete_offering(self, year_id, offering_id, headers):
        return self._request("POST", f"/school-years/{year_id}/offerings/{offering_id}/complete", headers=headers)

    def cancel_offering(self, year_id, offering_id, headers):
        return self._request("POST", f"/school-years/{year_id}/offerings/{offering_id}/cancel", headers=headers)

    # --- Student ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def withdraw_student(self, student_id, headers):
        return self._request("POST", f"/students/{student_id}/withdraw", headers=headers)

    def graduate_student(self, student_id, headers):
        return self._request("POST", f"/students/{student_id}/graduate", headers=headers)

    # --- StudentAccount ---
    def create_student_account(self, year_id, payload, headers):
        return self._request("POST", f"/school-years/{year_id}/student-accounts", payload, headers)

    def list_student_accounts(self, year_id, headers, params=None):
        return self._request("GET", f"/school-years/{year_id}/student-accounts", headers=headers, params=params)

    def get_student_account(self, account_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}", headers=headers)

    def get_account_summary(self, account_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/summary", headers=headers)

    # --- Enrollment ---
    def create_enrollment(self, account_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/enrollments", payload, headers)

    def list_enrollments(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/enrollments", headers=headers, params=params)

    def get_enrollment(self, account_id, enrollment_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/enrollments/{enrollment_id}", headers=headers)

    def withdraw_enrollment(self, account_id, enrollment_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/enrollments/{enrollment_id}/withdraw", headers=headers)

    # --- FeeAssessment ---
    def create_fee_assessment(self, account_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/fee-assessments", payload, headers)

    def list_fee_assessments(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/fee-assessments", headers=headers, params=params)

    def get_fee_assessment(self, account_id, assessment_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/fee-assessments/{assessment_id}", headers=headers)

    def void_fee_assessment(self, account_id, assessment_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/fee-assessments/{assessment_id}/void", headers=headers)

    # --- Purchase ---
    def create_purchase(self, account_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/purchases", payload, headers)

    def list_purchases(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/purchases", headers=headers, params=params)

    def get_purchase(self, account_id, purchase_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/purchases/{purchase_id}", headers=headers)

    # --- WaiverProgram ---
    def create_waiver_program(self, year_id, payload, headers):
        return self._request("POST", f"/school-years/{year_id}/waiver-programs", payload, headers)

    def list_waiver_programs(self, year_id, headers, params=None):
        return self._request("GET", f"/school-years/{year_id}/waiver-programs", headers=headers, params=params)

    def get_waiver_program(self, year_id, program_id, headers):
        return self._request("GET", f"/school-years/{year_id}/waiver-programs/{program_id}", headers=headers)

    def suspend_waiver_program(self, year_id, program_id, headers):
        return self._request("POST", f"/school-years/{year_id}/waiver-programs/{program_id}/suspend", headers=headers)

    # --- WaiverApplication ---
    def create_waiver_application(self, account_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/waiver-applications", payload, headers)

    def list_waiver_applications(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/waiver-applications", headers=headers, params=params)

    def get_waiver_application(self, account_id, application_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/waiver-applications/{application_id}", headers=headers)

    def approve_waiver_application(self, account_id, application_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/waiver-applications/{application_id}/approve", payload, headers)

    def deny_waiver_application(self, account_id, application_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/waiver-applications/{application_id}/deny", headers=headers)

    def revoke_waiver_application(self, account_id, application_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/waiver-applications/{application_id}/revoke", headers=headers)

    # --- Payment ---
    def create_payment(self, account_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/payments", payload, headers)

    def list_payments(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/payments", headers=headers, params=params)

    def get_payment(self, account_id, payment_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/payments/{payment_id}", headers=headers)

    def settle_payment(self, account_id, payment_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/payments/{payment_id}/settle", payload, headers)

    def void_payment(self, account_id, payment_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/payments/{payment_id}/void", headers=headers)

    def list_payment_allocations(self, account_id, payment_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/payments/{payment_id}/allocations", headers=headers, params=params)

    # --- PaymentPlan ---
    def create_payment_plan(self, account_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/payment-plans", payload, headers)

    def list_payment_plans(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/payment-plans", headers=headers, params=params)

    def get_payment_plan(self, account_id, plan_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/payment-plans/{plan_id}", headers=headers)

    def list_plan_installments(self, account_id, plan_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/payment-plans/{plan_id}/installments", headers=headers, params=params)

    def cancel_payment_plan(self, account_id, plan_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/payment-plans/{plan_id}/cancel", headers=headers)

    # --- Refund ---
    def create_refund(self, account_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/refunds", payload, headers)

    def list_refunds(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/refunds", headers=headers, params=params)

    def get_refund(self, account_id, refund_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/refunds/{refund_id}", headers=headers)

    def execute_refund(self, account_id, refund_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/refunds/{refund_id}/execute", headers=headers)

    def deny_refund(self, account_id, refund_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/refunds/{refund_id}/deny", headers=headers)

    # --- Ledger / Reconciliation ---
    def list_ledger_entries(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/ledger-entries", headers=headers, params=params)

    def create_reconciliation_run(self, year_id, headers):
        return self._request("POST", f"/school-years/{year_id}/reconciliation-runs", headers=headers)

    # --- CollectionsCase ---
    def list_collections_cases(self, account_id, headers, params=None):
        return self._request("GET", f"/student-accounts/{account_id}/collections-cases", headers=headers, params=params)

    def get_collections_case(self, account_id, case_id, headers):
        return self._request("GET", f"/student-accounts/{account_id}/collections-cases/{case_id}", headers=headers)

    def promise_collections_case(self, account_id, case_id, headers):
        return self._request("POST", f"/student-accounts/{account_id}/collections-cases/{case_id}/promise", headers=headers)

    def approve_writeoff(self, account_id, case_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/collections-cases/{case_id}/approve-writeoff", payload, headers)

    def write_off_case(self, account_id, case_id, payload, headers):
        return self._request("POST", f"/student-accounts/{account_id}/collections-cases/{case_id}/write-off", payload, headers)

    # --- Flat alias GETs used by tests ---
    def get_department_flat(self, department_id, headers):
        return self._request("GET", f"/departments/{department_id}", headers=headers)


api_client = ApiClient()
