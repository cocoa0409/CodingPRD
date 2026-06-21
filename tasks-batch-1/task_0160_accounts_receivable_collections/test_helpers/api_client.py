"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base `_request()` does the HTTP
work and envelope handling. Signature: _request(method, path, payload=None,
headers=None, params=None).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving clock ------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Customer ----------------------------------------------------------
    def create_customer(self, payload, headers):
        return self._request("POST", "/ar/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/ar/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/ar/customers", headers=headers, params=params)

    def hold_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/ar/customers/{customer_id}/hold", headers=headers
        )

    def release_hold_customer(self, customer_id, headers):
        return self._request(
            "POST", f"/ar/customers/{customer_id}/release-hold", headers=headers
        )

    def list_customer_statements(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/ar/customers/{customer_id}/statements",
            headers=headers, params=params,
        )

    def list_customer_dunning_pauses(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/ar/customers/{customer_id}/dunning-pauses",
            headers=headers, params=params,
        )

    def create_statement(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/ar/customers/{customer_id}/statements", payload, headers
        )

    # ---- Invoice -----------------------------------------------------------
    def create_invoice(self, payload, headers):
        return self._request("POST", "/ar/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/ar/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/ar/invoices", headers=headers, params=params)

    def list_invoice_disputes(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/ar/invoices/{invoice_id}/disputes",
            headers=headers, params=params,
        )

    def list_invoice_write_offs(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/ar/invoices/{invoice_id}/write-offs",
            headers=headers, params=params,
        )

    def list_invoice_payment_applications(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/ar/invoices/{invoice_id}/payment-applications",
            headers=headers, params=params,
        )

    def list_invoice_dunning_notices(self, invoice_id, headers, params=None):
        return self._request(
            "GET", f"/ar/invoices/{invoice_id}/dunning-notices",
            headers=headers, params=params,
        )

    # ---- Payment + applications -------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/ar/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/ar/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/ar/payments", headers=headers, params=params)

    def create_payment_application(self, payment_id, payload, headers):
        return self._request(
            "POST", f"/ar/payments/{payment_id}/applications", payload, headers
        )

    def auto_apply_payment(self, payment_id, headers):
        return self._request(
            "POST", f"/ar/payments/{payment_id}/auto-apply", headers=headers
        )

    def list_payment_applications(self, payment_id, headers, params=None):
        return self._request(
            "GET", f"/ar/payments/{payment_id}/applications",
            headers=headers, params=params,
        )

    def reverse_payment_application(self, payment_id, app_id, headers):
        return self._request(
            "POST",
            f"/ar/payments/{payment_id}/applications/{app_id}/reverse",
            headers=headers,
        )

    # ---- Dispute -----------------------------------------------------------
    def create_dispute(self, payload, headers):
        return self._request("POST", "/ar/disputes", payload, headers)

    def get_dispute(self, dispute_id, headers):
        return self._request("GET", f"/ar/disputes/{dispute_id}", headers=headers)

    def start_review_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/ar/disputes/{dispute_id}/start-review", headers=headers
        )

    def resolve_dispute(self, dispute_id, payload, headers):
        return self._request(
            "POST", f"/ar/disputes/{dispute_id}/resolve", payload, headers
        )

    def reject_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/ar/disputes/{dispute_id}/reject", headers=headers
        )

    def reopen_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/ar/disputes/{dispute_id}/reopen", headers=headers
        )

    def withdraw_dispute(self, dispute_id, headers):
        return self._request(
            "POST", f"/ar/disputes/{dispute_id}/withdraw", headers=headers
        )

    # ---- Promise to pay ----------------------------------------------------
    def create_promise(self, payload, headers):
        return self._request("POST", "/ar/promises", payload, headers)

    def get_promise(self, promise_id, headers):
        return self._request("GET", f"/ar/promises/{promise_id}", headers=headers)

    def list_promises(self, headers, params=None):
        return self._request("GET", "/ar/promises", headers=headers, params=params)

    def cancel_promise(self, promise_id, headers):
        return self._request(
            "POST", f"/ar/promises/{promise_id}/cancel", headers=headers
        )

    def evaluate_promise(self, promise_id, headers):
        return self._request(
            "POST", f"/ar/promises/{promise_id}/evaluate", headers=headers
        )

    # ---- Write-off ---------------------------------------------------------
    def create_write_off(self, payload, headers):
        return self._request("POST", "/ar/write-offs", payload, headers)

    def approve_write_off(self, write_off_id, headers):
        return self._request(
            "POST", f"/ar/write-offs/{write_off_id}/approve", headers=headers
        )

    def get_write_off(self, write_off_id, headers):
        return self._request("GET", f"/ar/write-offs/{write_off_id}", headers=headers)

    # ---- Dunning -----------------------------------------------------------
    def create_dunning_sequence(self, payload, headers):
        return self._request("POST", "/ar/dunning-sequences", payload, headers)

    def get_dunning_sequence(self, sequence_id, headers):
        return self._request(
            "GET", f"/ar/dunning-sequences/{sequence_id}", headers=headers
        )

    def list_sequence_notices(self, sequence_id, headers, params=None):
        return self._request(
            "GET", f"/ar/dunning-sequences/{sequence_id}/notices",
            headers=headers, params=params,
        )

    def create_dunning_run(self, payload, headers):
        return self._request("POST", "/ar/dunning-runs", payload, headers)

    def create_dunning_pause(self, payload, headers):
        return self._request("POST", "/ar/dunning-pauses", payload, headers)

    # ---- Statement + forecast ---------------------------------------------
    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/ar/statements/{statement_id}", headers=headers)

    def get_cash_forecast(self, headers, params=None):
        return self._request(
            "GET", "/ar/cash-forecast", headers=headers, params=params
        )


api_client = ApiClient()
