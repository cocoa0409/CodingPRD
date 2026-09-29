"""API client: one method per endpoint of the Interline & Codeshare Proration API."""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/interline"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------ clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --------------------------------------------------------------- carriers
    def create_carrier(self, payload, headers):
        return self._request("POST", f"{PREFIX}/carriers", payload, headers)

    def get_carrier(self, carrier_id, headers):
        return self._request("GET", f"{PREFIX}/carriers/{carrier_id}", headers=headers)

    def list_carriers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/carriers", headers=headers, params=params)

    def suspend_carrier(self, carrier_id, headers):
        return self._request(
            "POST", f"{PREFIX}/carriers/{carrier_id}/suspend", {}, headers
        )

    def reinstate_carrier(self, carrier_id, headers):
        return self._request(
            "POST", f"{PREFIX}/carriers/{carrier_id}/reinstate", {}, headers
        )

    # -------------------------------------------------------------- agreements
    def create_agreement(self, payload, headers):
        return self._request("POST", f"{PREFIX}/prorate-agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request(
            "GET", f"{PREFIX}/prorate-agreements/{agreement_id}", headers=headers
        )

    def list_agreements(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/prorate-agreements", headers=headers, params=params
        )

    def create_factor(self, agreement_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/prorate-agreements/{agreement_id}/factors", payload, headers
        )

    def list_factors(self, agreement_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/prorate-agreements/{agreement_id}/factors",
            headers=headers,
            params=params,
        )

    def activate_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/prorate-agreements/{agreement_id}/activate", {}, headers
        )

    def suspend_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"{PREFIX}/prorate-agreements/{agreement_id}/suspend", {}, headers
        )

    # ------------------------------------------------------- periods and rates
    def create_period(self, payload, headers):
        return self._request("POST", f"{PREFIX}/settlement-periods", payload, headers)

    def get_period(self, period_id, headers):
        return self._request(
            "GET", f"{PREFIX}/settlement-periods/{period_id}", headers=headers
        )

    def close_period(self, period_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-periods/{period_id}/close", {}, headers
        )

    def settle_period(self, period_id, headers):
        return self._request(
            "POST", f"{PREFIX}/settlement-periods/{period_id}/settle", {}, headers
        )

    def create_exchange_rate(self, payload, headers):
        return self._request("POST", f"{PREFIX}/exchange-rates", payload, headers)

    # ----------------------------------------------------- tickets and coupons
    def create_ticket(self, payload, headers):
        return self._request("POST", f"{PREFIX}/tickets", payload, headers)

    def get_ticket(self, ticket_id, headers):
        return self._request("GET", f"{PREFIX}/tickets/{ticket_id}", headers=headers)

    def list_tickets(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/tickets", headers=headers, params=params)

    def create_coupon(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/coupons", payload, headers
        )

    def get_coupon(self, coupon_id, headers):
        return self._request("GET", f"{PREFIX}/coupons/{coupon_id}", headers=headers)

    def list_coupons(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/coupons", headers=headers, params=params)

    def fly_coupon(self, coupon_id, headers):
        return self._request("POST", f"{PREFIX}/coupons/{coupon_id}/fly", {}, headers)

    def void_coupon(self, coupon_id, headers):
        return self._request("POST", f"{PREFIX}/coupons/{coupon_id}/void", {}, headers)

    def prorate_ticket(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/prorate", payload, headers
        )

    def list_proration_runs(self, ticket_id, headers, params=None):
        return self._request(
            "GET",
            f"{PREFIX}/tickets/{ticket_id}/proration-runs",
            headers=headers,
            params=params,
        )

    def void_proration(self, ticket_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/tickets/{ticket_id}/void-proration", payload, headers
        )

    # --------------------------------------------------------------- invoices
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/billing-invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request(
            "GET", f"{PREFIX}/billing-invoices/{invoice_id}", headers=headers
        )

    def list_invoices(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/billing-invoices", headers=headers, params=params
        )

    def submit_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-invoices/{invoice_id}/submit", {}, headers
        )

    def recall_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"{PREFIX}/billing-invoices/{invoice_id}/recall", {}, headers
        )

    # ------------------------------------------------------------------ memos
    def create_memo(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rejection-memos", payload, headers)

    def get_memo(self, memo_id, headers):
        return self._request(
            "GET", f"{PREFIX}/rejection-memos/{memo_id}", headers=headers
        )

    def list_memos(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/rejection-memos", headers=headers, params=params
        )

    def counter_memo(self, memo_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rejection-memos/{memo_id}/counter", payload, headers
        )

    def re_reject_memo(self, memo_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rejection-memos/{memo_id}/re-reject", payload, headers
        )

    def accept_memo(self, memo_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rejection-memos/{memo_id}/accept", payload, headers
        )

    def withdraw_memo(self, memo_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/rejection-memos/{memo_id}/withdraw", payload, headers
        )

    def escalate_memo(self, memo_id, headers):
        return self._request(
            "POST", f"{PREFIX}/rejection-memos/{memo_id}/escalate", {}, headers
        )

    def arbitrate_memo(self, memo_id, ruling, headers):
        return self._request(
            "POST",
            f"{PREFIX}/rejection-memos/{memo_id}/arbitrate",
            {"ruling": ruling},
            headers,
        )

    # ---------------------------------------------------------- audit samples
    def create_audit_sample(self, payload, headers):
        return self._request("POST", f"{PREFIX}/audit-samples", payload, headers)

    def get_audit_sample(self, sample_id, headers):
        return self._request(
            "GET", f"{PREFIX}/audit-samples/{sample_id}", headers=headers
        )

    def list_audit_samples(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/audit-samples", headers=headers, params=params
        )

    def record_finding(self, sample_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-samples/{sample_id}/record-finding", payload, headers
        )

    def close_audit_sample(self, sample_id, headers):
        return self._request(
            "POST", f"{PREFIX}/audit-samples/{sample_id}/close", {}, headers
        )

    def claim_decision(self, sample_id, decision, headers):
        return self._request(
            "POST",
            f"{PREFIX}/audit-samples/{sample_id}/claim-decision",
            {"decision": decision},
            headers,
        )


api_client = ApiClient()
