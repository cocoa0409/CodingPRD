"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Creators ----
    def create_creator(self, payload, headers):
        return self._request("POST", "/creators", payload, headers)

    def get_creator(self, creator_id, headers):
        return self._request("GET", f"/creators/{creator_id}", headers=headers)

    def set_creator_status(self, creator_id, payload, headers):
        return self._request("POST", f"/creators/{creator_id}/set-status", payload, headers)

    # ---- Students ----
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    # ---- Courses ----
    def create_course(self, payload, headers):
        return self._request("POST", "/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/courses", headers=headers, params=params)

    def set_course_status(self, course_id, payload, headers):
        return self._request("POST", f"/courses/{course_id}/set-status", payload, headers)

    # ---- Lessons ----
    def create_lesson(self, payload, headers):
        return self._request("POST", "/lessons", payload, headers)

    def get_lesson(self, lesson_id, headers):
        return self._request("GET", f"/lessons/{lesson_id}", headers=headers)

    def list_lessons(self, headers, params=None):
        return self._request("GET", "/lessons", headers=headers, params=params)

    # ---- Price Plans ----
    def create_price_plan(self, payload, headers):
        return self._request("POST", "/price-plans", payload, headers)

    def get_price_plan(self, plan_id, headers):
        return self._request("GET", f"/price-plans/{plan_id}", headers=headers)

    def list_price_plans(self, headers, params=None):
        return self._request("GET", "/price-plans", headers=headers, params=params)

    def set_price_plan_status(self, plan_id, payload, headers):
        return self._request("POST", f"/price-plans/{plan_id}/set-status", payload, headers)

    # ---- Coupons ----
    def create_coupon(self, payload, headers):
        return self._request("POST", "/coupons", payload, headers)

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    def list_coupons(self, headers, params=None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def set_coupon_status(self, coupon_id, payload, headers):
        return self._request("POST", f"/coupons/{coupon_id}/set-status", payload, headers)

    # ---- Affiliates ----
    def create_affiliate(self, payload, headers):
        return self._request("POST", "/affiliates", payload, headers)

    def get_affiliate(self, affiliate_id, headers):
        return self._request("GET", f"/affiliates/{affiliate_id}", headers=headers)

    def list_affiliates(self, headers, params=None):
        return self._request("GET", "/affiliates", headers=headers, params=params)

    def set_affiliate_status(self, affiliate_id, payload, headers):
        return self._request("POST", f"/affiliates/{affiliate_id}/set-status", payload, headers)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/enrollments", headers=headers, params=params)

    def complete_lesson(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/complete-lesson", payload, headers)

    def cancel_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/cancel", payload, headers)

    def create_quiz_attempt(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/quiz-attempts", payload, headers)

    def create_cycle_invoice(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/invoices", payload, headers)

    # ---- Quiz Attempts ----
    def get_quiz_attempt(self, quiz_attempt_id, headers):
        return self._request("GET", f"/quiz-attempts/{quiz_attempt_id}", headers=headers)

    def list_quiz_attempts(self, headers, params=None):
        return self._request("GET", "/quiz-attempts", headers=headers, params=params)

    # ---- Invoices ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", payload, headers)

    def refund_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"/invoices/{invoice_id}/refund", payload, headers)

    # ---- Payouts ----
    def create_payout(self, creator_id, payload, headers):
        return self._request("POST", f"/creators/{creator_id}/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def set_payout_status(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/set-status", payload, headers)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
