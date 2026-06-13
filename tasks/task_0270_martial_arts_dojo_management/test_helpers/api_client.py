"""API client: one method per endpoint defined in the PRD.

All resources are mounted under the /dojo prefix. The base _request()
method is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ----- Programs & belt ranks -----
    def create_program(self, payload, headers):
        return self._request("POST", "/dojo/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/dojo/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/dojo/programs", headers=headers, params=params)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/dojo/programs/{program_id}/archive", {}, headers)

    def create_belt_rank(self, program_id, payload, headers):
        return self._request("POST", f"/dojo/programs/{program_id}/belt-ranks", payload, headers)

    def list_belt_ranks(self, program_id, headers, params=None):
        return self._request("GET", f"/dojo/programs/{program_id}/belt-ranks", headers=headers, params=params)

    # ----- Families -----
    def create_family(self, payload, headers):
        return self._request("POST", "/dojo/families", payload, headers)

    def get_family(self, family_id, headers):
        return self._request("GET", f"/dojo/families/{family_id}", headers=headers)

    # ----- Members -----
    def create_member(self, payload, headers):
        return self._request("POST", "/dojo/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/dojo/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/dojo/members", headers=headers, params=params)

    def sign_waiver(self, member_id, headers):
        return self._request("POST", f"/dojo/members/{member_id}/sign-waiver", {}, headers)

    def freeze_member(self, member_id, payload, headers):
        return self._request("POST", f"/dojo/members/{member_id}/freeze", payload, headers)

    def unfreeze_member(self, member_id, payload, headers):
        return self._request("POST", f"/dojo/members/{member_id}/unfreeze", payload, headers)

    def withdraw_member(self, member_id, payload, headers):
        return self._request("POST", f"/dojo/members/{member_id}/withdraw", payload, headers)

    # ----- Instructors -----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/dojo/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/dojo/instructors/{instructor_id}", headers=headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/dojo/instructors", headers=headers, params=params)

    # ----- Enrollments -----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/dojo/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/dojo/enrollments/{enrollment_id}", headers=headers)

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/dojo/enrollments", headers=headers, params=params)

    def get_test_eligibility(self, enrollment_id, headers):
        return self._request("GET", f"/dojo/enrollments/{enrollment_id}/test-eligibility", headers=headers)

    # ----- Class sessions & attendance -----
    def create_class_session(self, payload, headers):
        return self._request("POST", "/dojo/class-sessions", payload, headers)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/dojo/class-sessions/{session_id}", headers=headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/dojo/class-sessions", headers=headers, params=params)

    def cancel_class_session(self, session_id, payload, headers):
        return self._request("POST", f"/dojo/class-sessions/{session_id}/cancel", payload, headers)

    def complete_class_session(self, session_id, payload, headers):
        return self._request("POST", f"/dojo/class-sessions/{session_id}/complete", payload, headers)

    def create_attendance(self, payload, headers):
        return self._request("POST", "/dojo/attendances", payload, headers)

    def get_attendance(self, attendance_id, headers):
        return self._request("GET", f"/dojo/attendances/{attendance_id}", headers=headers)

    def list_attendances(self, headers, params=None):
        return self._request("GET", "/dojo/attendances", headers=headers, params=params)

    def cancel_attendance(self, attendance_id, headers):
        return self._request("POST", f"/dojo/attendances/{attendance_id}/cancel", {}, headers)

    # ----- Promotion tests -----
    def create_promotion_test(self, payload, headers):
        return self._request("POST", "/dojo/promotion-tests", payload, headers)

    def get_promotion_test(self, test_id, headers):
        return self._request("GET", f"/dojo/promotion-tests/{test_id}", headers=headers)

    def list_promotion_tests(self, headers, params=None):
        return self._request("GET", "/dojo/promotion-tests", headers=headers, params=params)

    def grade_promotion_test(self, test_id, payload, headers):
        return self._request("POST", f"/dojo/promotion-tests/{test_id}/grade", payload, headers)

    def signoff_promotion_test(self, test_id, headers):
        return self._request("POST", f"/dojo/promotion-tests/{test_id}/signoff", {}, headers)

    def cancel_promotion_test(self, test_id, headers):
        return self._request("POST", f"/dojo/promotion-tests/{test_id}/cancel", {}, headers)

    # ----- Contracts -----
    def create_contract(self, payload, headers):
        return self._request("POST", "/dojo/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/dojo/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/dojo/contracts", headers=headers, params=params)

    def get_buyout_quote(self, contract_id, headers):
        return self._request("GET", f"/dojo/contracts/{contract_id}/buyout-quote", headers=headers)

    def run_billing(self, contract_id, headers):
        return self._request("POST", f"/dojo/contracts/{contract_id}/run-billing", {}, headers)

    def terminate_contract(self, contract_id, payload, headers):
        return self._request("POST", f"/dojo/contracts/{contract_id}/terminate", payload, headers)

    # ----- Invoices -----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/dojo/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/dojo/invoices", headers=headers, params=params)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/dojo/invoices/{invoice_id}/pay", {}, headers)

    def waive_invoice(self, invoice_id, headers):
        return self._request("POST", f"/dojo/invoices/{invoice_id}/waive", {}, headers)

    def mark_invoice_overdue(self, invoice_id, headers):
        return self._request("POST", f"/dojo/invoices/{invoice_id}/mark-overdue", {}, headers)

    # ----- Private lessons -----
    def create_private_lesson(self, payload, headers):
        return self._request("POST", "/dojo/private-lessons", payload, headers)

    def get_private_lesson(self, lesson_id, headers):
        return self._request("GET", f"/dojo/private-lessons/{lesson_id}", headers=headers)

    def list_private_lessons(self, headers, params=None):
        return self._request("GET", "/dojo/private-lessons", headers=headers, params=params)

    def confirm_private_lesson(self, lesson_id, headers):
        return self._request("POST", f"/dojo/private-lessons/{lesson_id}/confirm", {}, headers)

    def complete_private_lesson(self, lesson_id, headers):
        return self._request("POST", f"/dojo/private-lessons/{lesson_id}/complete", {}, headers)

    def cancel_private_lesson(self, lesson_id, headers):
        return self._request("POST", f"/dojo/private-lessons/{lesson_id}/cancel", {}, headers)

    # ----- Tournament registrations -----
    def create_tournament_registration(self, payload, headers):
        return self._request("POST", "/dojo/tournament-registrations", payload, headers)

    def get_tournament_registration(self, registration_id, headers):
        return self._request("GET", f"/dojo/tournament-registrations/{registration_id}", headers=headers)

    def list_tournament_registrations(self, headers, params=None):
        return self._request("GET", "/dojo/tournament-registrations", headers=headers, params=params)

    def withdraw_tournament_registration(self, registration_id, headers):
        return self._request("POST", f"/dojo/tournament-registrations/{registration_id}/withdraw", {}, headers)

    # ----- Pro-shop -----
    def create_pro_shop_order(self, payload, headers):
        return self._request("POST", "/dojo/pro-shop-orders", payload, headers)

    def get_pro_shop_order(self, order_id, headers):
        return self._request("GET", f"/dojo/pro-shop-orders/{order_id}", headers=headers)

    def list_pro_shop_orders(self, headers, params=None):
        return self._request("GET", "/dojo/pro-shop-orders", headers=headers, params=params)

    def fulfill_pro_shop_order(self, order_id, headers):
        return self._request("POST", f"/dojo/pro-shop-orders/{order_id}/fulfill", {}, headers)

    def cancel_pro_shop_order(self, order_id, headers):
        return self._request("POST", f"/dojo/pro-shop-orders/{order_id}/cancel", {}, headers)

    # ----- Test-driving clock -----
    def advance_clock(self, payload, headers):
        return self._request("POST", "/dojo/_clock/advance", payload, headers)


api_client = ApiClient()
