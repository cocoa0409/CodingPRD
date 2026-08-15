"""API client: one method per endpoint defined in PRD §4 (all under /bursar)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Bursar Student Accounts API client."""

    # --- Logical clock (PRD §2.4) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/bursar/_clock/set_current_utc", payload, headers)

    # --- Terms ---
    def create_term(self, payload, headers):
        return self._request("POST", "/bursar/terms", payload, headers)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/bursar/terms/{term_id}", headers=headers)

    def transition_term(self, term_id, payload, headers):
        return self._request(
            "POST", f"/bursar/terms/{term_id}/transition", payload, headers
        )

    def run_billing_cycle(self, term_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/terms/{term_id}/run-billing-cycle", payload or {}, headers
        )

    # --- Tuition rates ---
    def create_tuition_rate(self, payload, headers):
        return self._request("POST", "/bursar/tuition-rates", payload, headers)

    def list_term_tuition_rates(self, term_id, headers):
        return self._request(
            "GET", f"/bursar/terms/{term_id}/tuition-rates", headers=headers
        )

    # --- Students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/bursar/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/bursar/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/bursar/students", headers=headers, params=params)

    # --- Enrollments ---
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/bursar/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request(
            "GET", f"/bursar/enrollments/{enrollment_id}", headers=headers
        )

    def list_enrollments(self, headers, params=None):
        return self._request("GET", "/bursar/enrollments", headers=headers, params=params)

    def drop_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/bursar/enrollments/{enrollment_id}/drop", payload, headers
        )

    def withdraw_enrollment(self, enrollment_id, payload, headers):
        return self._request(
            "POST", f"/bursar/enrollments/{enrollment_id}/withdraw", payload, headers
        )

    # --- Accounts & ledger ---
    def get_account(self, account_id, headers):
        return self._request("GET", f"/bursar/accounts/{account_id}", headers=headers)

    def list_student_accounts(self, student_id, headers):
        return self._request(
            "GET", f"/bursar/students/{student_id}/accounts", headers=headers
        )

    def list_term_accounts(self, term_id, headers):
        return self._request("GET", f"/bursar/terms/{term_id}/accounts", headers=headers)

    def get_account_ledger(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/bursar/accounts/{account_id}/ledger", headers=headers, params=params
        )

    def get_enrollment_ledger(self, enrollment_id, headers):
        return self._request(
            "GET", f"/bursar/enrollments/{enrollment_id}/ledger", headers=headers
        )

    def send_to_collections(self, account_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/accounts/{account_id}/send-to-collections",
            payload or {}, headers,
        )

    def write_off(self, account_id, payload, headers):
        return self._request(
            "POST", f"/bursar/accounts/{account_id}/write-off", payload, headers
        )

    # --- Payments ---
    def create_payment(self, payload, headers):
        return self._request("POST", "/bursar/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/bursar/payments/{payment_id}", headers=headers)

    def list_account_payments(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/bursar/accounts/{account_id}/payments",
            headers=headers, params=params,
        )

    def reverse_payment(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/bursar/payments/{payment_id}/reverse", payload, headers
        )

    # --- Waivers ---
    def create_waiver(self, payload, headers):
        return self._request("POST", "/bursar/waivers", payload, headers)

    def post_waiver(self, waiver_id, payload, headers):
        return self._request(
            "POST", f"/bursar/waivers/{waiver_id}/post", payload, headers
        )

    def revoke_waiver(self, waiver_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/waivers/{waiver_id}/revoke", payload or {}, headers
        )

    def list_account_waivers(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/bursar/accounts/{account_id}/waivers",
            headers=headers, params=params,
        )

    # --- Sponsor agreements ---
    def create_sponsor_agreement(self, payload, headers):
        return self._request("POST", "/bursar/sponsor-agreements", payload, headers)

    def get_sponsor_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"/bursar/sponsor-agreements/{agreement_id}", headers=headers
        )

    def list_sponsor_agreements(self, headers, params=None):
        return self._request(
            "GET", "/bursar/sponsor-agreements", headers=headers, params=params
        )

    def terminate_sponsor_agreement(self, agreement_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/sponsor-agreements/{agreement_id}/terminate",
            payload or {}, headers,
        )

    # --- Sponsor invoices ---
    def create_sponsor_invoice(self, payload, headers):
        return self._request("POST", "/bursar/sponsor-invoices", payload, headers)

    def get_sponsor_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"/bursar/sponsor-invoices/{invoice_id}", headers=headers
        )

    def list_agreement_invoices(self, agreement_id, headers, params=None):
        return self._request(
            "GET", f"/bursar/sponsor-agreements/{agreement_id}/invoices",
            headers=headers, params=params,
        )

    def transition_sponsor_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/bursar/sponsor-invoices/{invoice_id}/transition", payload, headers
        )

    def record_sponsor_payment(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"/bursar/sponsor-invoices/{invoice_id}/payments", payload, headers
        )

    # --- Payment plans / installments ---
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/bursar/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/bursar/payment-plans/{plan_id}", headers=headers)

    def list_account_payment_plans(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/bursar/accounts/{account_id}/payment-plans",
            headers=headers, params=params,
        )

    def cancel_payment_plan(self, plan_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/payment-plans/{plan_id}/cancel", payload or {}, headers
        )

    def list_plan_installments(self, plan_id, headers, params=None):
        return self._request(
            "GET", f"/bursar/payment-plans/{plan_id}/installments",
            headers=headers, params=params,
        )

    def pay_installment(self, installment_id, payload, headers):
        return self._request(
            "POST", f"/bursar/installments/{installment_id}/pay", payload, headers
        )

    # --- Financial holds ---
    def create_hold(self, payload, headers):
        return self._request("POST", "/bursar/holds", payload, headers)

    def release_hold(self, hold_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/holds/{hold_id}/release", payload or {}, headers
        )

    def list_account_holds(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/bursar/accounts/{account_id}/holds", headers=headers, params=params
        )

    # --- Refunds ---
    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/bursar/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/bursar/refunds", headers=headers, params=params)

    def transition_refund(self, refund_id, payload, headers):
        return self._request(
            "POST", f"/bursar/refunds/{refund_id}/transition", payload, headers
        )

    # --- 1098-T tax forms ---
    def create_tax_form(self, payload, headers):
        return self._request("POST", "/bursar/tax-forms", payload, headers)

    def get_tax_form(self, form_id, headers):
        return self._request("GET", f"/bursar/tax-forms/{form_id}", headers=headers)

    def list_student_tax_forms(self, student_id, headers):
        return self._request(
            "GET", f"/bursar/students/{student_id}/tax-forms", headers=headers
        )

    def list_tax_forms(self, headers, params=None):
        return self._request("GET", "/bursar/tax-forms", headers=headers, params=params)

    def finalize_tax_form(self, form_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/tax-forms/{form_id}/finalize", payload or {}, headers
        )

    def correct_tax_form(self, form_id, headers, payload=None):
        return self._request(
            "POST", f"/bursar/tax-forms/{form_id}/correct", payload or {}, headers
        )


class _FreshConnectionApiClient(ApiClient):
    """Per-test-server isolation restarts the API server before every test.
    A session-scoped requests.Session pools keep-alive connections, so the
    first request after a restart can ride a TCP connection whose peer (the
    previous server process) is already gone -> ConnectionResetError /
    RemoteDisconnected. Forcing Connection: close makes every request open a
    fresh connection to the currently-running server."""

    def _request(self, method, path, payload=None, headers=None, params=None):
        h = dict(headers or {})
        h["Connection"] = "close"
        return super()._request(method, path, payload=payload, headers=h,
                                params=params)


api_client = _FreshConnectionApiClient()
