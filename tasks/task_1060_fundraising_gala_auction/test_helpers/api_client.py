"""API client: one method per endpoint defined in the PRD.

All paths are mounted under /api. The base _request() implementation is
inherited from the framework's GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ──────────────────────────────────────────────────────

    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Gala events ────────────────────────────────────────────────────────

    def create_event(self, payload, headers):
        return self._request("POST", "/api/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/api/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/api/events", headers=headers, params=params)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/publish", {}, headers)

    def unpublish_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/unpublish", {}, headers)

    def go_live_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/go-live", {}, headers)

    def start_settlement(self, event_id, headers):
        return self._request(
            "POST", f"/api/events/{event_id}/start-settlement", {}, headers
        )

    def close_event(self, event_id, headers):
        return self._request("POST", f"/api/events/{event_id}/close", {}, headers)

    def get_revenue_summary(self, event_id, headers):
        return self._request(
            "GET", f"/api/events/{event_id}/revenue-summary", headers=headers
        )

    # ─── Ticket tables ──────────────────────────────────────────────────────

    def create_table(self, event_id, payload, headers):
        return self._request("POST", f"/api/events/{event_id}/tables", payload, headers)

    def get_table(self, table_id, headers):
        return self._request("GET", f"/api/tables/{table_id}", headers=headers)

    def list_tables(self, headers, params=None):
        return self._request("GET", "/api/tables", headers=headers, params=params)

    # ─── Table holds ────────────────────────────────────────────────────────

    def create_table_hold(self, payload, headers):
        return self._request("POST", "/api/table-holds", payload, headers)

    def get_table_hold(self, hold_id, headers):
        return self._request("GET", f"/api/table-holds/{hold_id}", headers=headers)

    def list_table_holds(self, headers, params=None):
        return self._request("GET", "/api/table-holds", headers=headers, params=params)

    def release_table_hold(self, hold_id, headers):
        return self._request(
            "POST", f"/api/table-holds/{hold_id}/release", {}, headers
        )

    # ─── Bidders ────────────────────────────────────────────────────────────

    def create_bidder(self, payload, headers):
        return self._request("POST", "/api/bidders", payload, headers)

    def get_bidder(self, bidder_id, headers):
        return self._request("GET", f"/api/bidders/{bidder_id}", headers=headers)

    def list_bidders(self, headers, params=None):
        return self._request("GET", "/api/bidders", headers=headers, params=params)

    def set_payment_method(self, bidder_id, payment_method_on_file, headers):
        return self._request(
            "POST",
            f"/api/bidders/{bidder_id}/payment-method",
            {"payment_method_on_file": payment_method_on_file},
            headers,
        )

    # ─── Sponsors ───────────────────────────────────────────────────────────

    def create_sponsor(self, payload, headers):
        return self._request("POST", "/api/sponsors", payload, headers)

    def get_sponsor(self, sponsor_id, headers):
        return self._request("GET", f"/api/sponsors/{sponsor_id}", headers=headers)

    def list_sponsors(self, headers, params=None):
        return self._request("GET", "/api/sponsors", headers=headers, params=params)

    def confirm_sponsor(self, sponsor_id, paid_amount_cents, headers):
        return self._request(
            "POST",
            f"/api/sponsors/{sponsor_id}/confirm",
            {"paid_amount_cents": paid_amount_cents},
            headers,
        )

    def withdraw_sponsor(self, sponsor_id, headers):
        return self._request(
            "POST", f"/api/sponsors/{sponsor_id}/withdraw", {}, headers
        )

    # ─── Program ads ────────────────────────────────────────────────────────

    def create_program_ad(self, payload, headers):
        return self._request("POST", "/api/program-ads", payload, headers)

    def get_program_ad(self, ad_id, headers):
        return self._request("GET", f"/api/program-ads/{ad_id}", headers=headers)

    def list_program_ads(self, headers, params=None):
        return self._request("GET", "/api/program-ads", headers=headers, params=params)

    def review_program_ad(self, ad_id, payload, headers):
        return self._request(
            "POST", f"/api/program-ads/{ad_id}/review", payload, headers
        )

    def resubmit_program_ad(self, ad_id, artwork_ref, headers):
        return self._request(
            "POST",
            f"/api/program-ads/{ad_id}/resubmit",
            {"artwork_ref": artwork_ref},
            headers,
        )

    def place_program_ad(self, ad_id, page_number, headers):
        return self._request(
            "POST",
            f"/api/program-ads/{ad_id}/place",
            {"page_number": page_number},
            headers,
        )

    # ─── Ticket orders ──────────────────────────────────────────────────────

    def create_ticket_order(self, payload, headers):
        return self._request("POST", "/api/ticket-orders", payload, headers)

    def get_ticket_order(self, order_id, headers):
        return self._request("GET", f"/api/ticket-orders/{order_id}", headers=headers)

    def list_ticket_orders(self, headers, params=None):
        return self._request(
            "GET", "/api/ticket-orders", headers=headers, params=params
        )

    def assign_seats(self, order_id, headers):
        return self._request(
            "POST", f"/api/ticket-orders/{order_id}/assign-seats", {}, headers
        )

    def cancel_ticket_order(self, order_id, headers):
        return self._request(
            "POST", f"/api/ticket-orders/{order_id}/cancel", {}, headers
        )

    # ─── Auction items ──────────────────────────────────────────────────────

    def create_auction_item(self, payload, headers):
        return self._request("POST", "/api/auction-items", payload, headers)

    def get_auction_item(self, item_id, headers):
        return self._request("GET", f"/api/auction-items/{item_id}", headers=headers)

    def list_auction_items(self, headers, params=None):
        return self._request(
            "GET", "/api/auction-items", headers=headers, params=params
        )

    def open_auction_item(self, item_id, headers):
        return self._request("POST", f"/api/auction-items/{item_id}/open", {}, headers)

    def close_auction_item(self, item_id, headers):
        return self._request("POST", f"/api/auction-items/{item_id}/close", {}, headers)

    def get_valuation(self, item_id, variant, headers):
        return self._request(
            "GET",
            f"/api/auction-items/{item_id}/valuation",
            {"variant": variant},
            headers,
        )

    # ─── Bids ───────────────────────────────────────────────────────────────

    def place_bid(self, item_id, payload, headers):
        return self._request(
            "POST", f"/api/auction-items/{item_id}/bids", payload, headers
        )

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/api/bids/{bid_id}", headers=headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/api/bids", headers=headers, params=params)

    def retract_bid(self, bid_id, headers):
        return self._request("POST", f"/api/bids/{bid_id}/retract", {}, headers)

    # ─── Paddle raises ──────────────────────────────────────────────────────

    def create_paddle_raise(self, payload, headers):
        return self._request("POST", "/api/paddle-raises", payload, headers)

    def get_paddle_raise(self, paddle_raise_id, headers):
        return self._request(
            "GET", f"/api/paddle-raises/{paddle_raise_id}", headers=headers
        )

    def list_paddle_raises(self, headers, params=None):
        return self._request(
            "GET", "/api/paddle-raises", headers=headers, params=params
        )

    # ─── Pledges ────────────────────────────────────────────────────────────

    def create_pledge(self, payload, headers):
        return self._request("POST", "/api/pledges", payload, headers)

    def get_pledge(self, pledge_id, headers):
        return self._request("GET", f"/api/pledges/{pledge_id}", headers=headers)

    def list_pledges(self, headers, params=None):
        return self._request("GET", "/api/pledges", headers=headers, params=params)

    def record_installment(self, pledge_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/api/pledges/{pledge_id}/installments",
            {"amount_cents": amount_cents},
            headers,
        )

    def lapse_pledge(self, pledge_id, headers):
        return self._request("POST", f"/api/pledges/{pledge_id}/lapse", {}, headers)

    # ─── Checkout invoices ──────────────────────────────────────────────────

    def create_invoice(self, payload, headers):
        return self._request("POST", "/api/invoices", payload, headers)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/api/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/api/invoices", headers=headers, params=params)

    def finalize_invoice(self, invoice_id, headers):
        return self._request(
            "POST", f"/api/invoices/{invoice_id}/finalize", {}, headers
        )

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/api/invoices/{invoice_id}/void", {}, headers)

    # ─── Payments ───────────────────────────────────────────────────────────

    def create_payment(self, payload, headers):
        return self._request("POST", "/api/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/api/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/api/payments", headers=headers, params=params)

    def void_payment(self, payment_id, reason, headers):
        return self._request(
            "POST", f"/api/payments/{payment_id}/void", {"reason": reason}, headers
        )

    # ─── Receipts ───────────────────────────────────────────────────────────

    def create_receipt(self, invoice_id, headers):
        return self._request(
            "POST", "/api/receipts", {"invoice_id": invoice_id}, headers
        )

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/api/receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/api/receipts", headers=headers, params=params)

    # ─── Reconciliation runs ────────────────────────────────────────────────

    def create_reconciliation_run(self, event_id, payload, headers):
        return self._request(
            "POST", f"/api/events/{event_id}/reconciliation-runs", payload, headers
        )

    def get_reconciliation_run(self, run_id, headers):
        return self._request(
            "GET", f"/api/reconciliation-runs/{run_id}", headers=headers
        )

    def list_reconciliation_runs(self, event_id, headers, params=None):
        return self._request(
            "GET",
            f"/api/events/{event_id}/reconciliation-runs",
            headers=headers,
            params=params,
        )

    def finalize_reconciliation_run(self, run_id, payload, headers):
        return self._request(
            "POST", f"/api/reconciliation-runs/{run_id}/finalize", payload, headers
        )

    def reopen_reconciliation_run(self, run_id, headers):
        return self._request(
            "POST", f"/api/reconciliation-runs/{run_id}/reopen", {}, headers
        )


api_client = ApiClient()
