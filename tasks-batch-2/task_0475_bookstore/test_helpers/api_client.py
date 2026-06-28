"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Members ----------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_credit_ledger(self, member_id, headers, params=None):
        return self._request(
            "GET", f"/members/{member_id}/credit-ledger", headers=headers, params=params
        )

    def create_credit_adjustment(self, member_id, payload, headers):
        return self._request(
            "POST", f"/members/{member_id}/credit-adjustments", payload, headers
        )

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/suspend", headers=headers)

    # ---- Titles + stock ---------------------------------------------------
    def create_title(self, payload, headers):
        return self._request("POST", "/titles", payload, headers)

    def get_title(self, title_id, headers):
        return self._request("GET", f"/titles/{title_id}", headers=headers)

    def list_titles(self, headers, params=None):
        return self._request("GET", "/titles", headers=headers, params=params)

    def create_stock_items(self, title_id, payload, headers):
        return self._request(
            "POST", f"/titles/{title_id}/stock-items", payload, headers
        )

    def list_title_stock_items(self, title_id, headers, params=None):
        return self._request(
            "GET", f"/titles/{title_id}/stock-items", headers=headers, params=params
        )

    def get_stock_item(self, stock_item_id, headers):
        return self._request("GET", f"/stock-items/{stock_item_id}", headers=headers)

    def list_stock_items(self, headers, params=None):
        return self._request("GET", "/stock-items", headers=headers, params=params)

    # ---- Sales orders -----------------------------------------------------
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/sales-orders", headers=headers, params=params)

    def create_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/lines", payload, headers
        )

    def list_order_lines(self, order_id, headers, params=None):
        return self._request(
            "GET", f"/sales-orders/{order_id}/lines", headers=headers, params=params
        )

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/order-lines/{line_id}", headers=headers)

    def list_all_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/sales-orders/{order_id}/pay", headers=headers)

    def reserve_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/reserve", payload, headers
        )

    def fulfill_order(self, order_id, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/fulfill", headers=headers
        )

    def cancel_order(self, order_id, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/cancel", headers=headers
        )

    def refund_order(self, order_id, headers):
        return self._request(
            "POST", f"/sales-orders/{order_id}/refund", headers=headers
        )

    # ---- Special orders ---------------------------------------------------
    def create_special_order(self, payload, headers):
        return self._request("POST", "/special-orders", payload, headers)

    def get_special_order(self, so_id, headers):
        return self._request("GET", f"/special-orders/{so_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/special-orders", headers=headers, params=params)

    def quote_special_order(self, so_id, headers):
        return self._request(
            "POST", f"/special-orders/{so_id}/quote", headers=headers
        )

    def revise_special_order(self, so_id, headers):
        return self._request(
            "POST", f"/special-orders/{so_id}/revise", headers=headers
        )

    def confirm_special_order(self, so_id, headers):
        return self._request(
            "POST", f"/special-orders/{so_id}/confirm", headers=headers
        )

    def receive_special_order(self, so_id, headers):
        return self._request(
            "POST", f"/special-orders/{so_id}/receive", headers=headers
        )

    def cancel_special_order(self, so_id, headers):
        return self._request(
            "POST", f"/special-orders/{so_id}/cancel", headers=headers
        )

    # ---- Publisher returns ------------------------------------------------
    def create_publisher_return(self, payload, headers):
        return self._request("POST", "/publisher-returns", payload, headers)

    def get_publisher_return(self, pr_id, headers):
        return self._request("GET", f"/publisher-returns/{pr_id}", headers=headers)

    def list_publisher_returns(self, headers, params=None):
        return self._request(
            "GET", "/publisher-returns", headers=headers, params=params
        )

    def submit_publisher_return(self, pr_id, payload, headers):
        return self._request(
            "POST", f"/publisher-returns/{pr_id}/submit", payload, headers
        )

    def accept_publisher_return(self, pr_id, headers):
        return self._request(
            "POST", f"/publisher-returns/{pr_id}/accept", headers=headers
        )

    def reject_publisher_return(self, pr_id, headers):
        return self._request(
            "POST", f"/publisher-returns/{pr_id}/reject", headers=headers
        )

    # ---- Buybacks ---------------------------------------------------------
    def create_buyback(self, payload, headers):
        return self._request("POST", "/buybacks", payload, headers)

    def get_buyback(self, bb_id, headers):
        return self._request("GET", f"/buybacks/{bb_id}", headers=headers)

    def list_buybacks(self, headers, params=None):
        return self._request("GET", "/buybacks", headers=headers, params=params)

    def create_buyback_line(self, bb_id, payload, headers):
        return self._request("POST", f"/buybacks/{bb_id}/lines", payload, headers)

    def list_buyback_lines(self, bb_id, headers, params=None):
        return self._request(
            "GET", f"/buybacks/{bb_id}/lines", headers=headers, params=params
        )

    def get_buyback_line(self, line_id, headers):
        return self._request("GET", f"/buyback-lines/{line_id}", headers=headers)

    def list_all_buyback_lines(self, headers, params=None):
        return self._request("GET", "/buyback-lines", headers=headers, params=params)

    def offer_buyback(self, bb_id, headers):
        return self._request("POST", f"/buybacks/{bb_id}/offer", headers=headers)

    def complete_buyback(self, bb_id, headers):
        return self._request("POST", f"/buybacks/{bb_id}/complete", headers=headers)

    def void_buyback(self, bb_id, headers):
        return self._request("POST", f"/buybacks/{bb_id}/void", headers=headers)

    # ---- Author events + tickets ------------------------------------------
    def create_author_event(self, payload, headers):
        return self._request("POST", "/author-events", payload, headers)

    def get_author_event(self, event_id, headers):
        return self._request("GET", f"/author-events/{event_id}", headers=headers)

    def list_author_events(self, headers, params=None):
        return self._request("GET", "/author-events", headers=headers, params=params)

    def book_ticket(self, event_id, payload, headers):
        return self._request(
            "POST", f"/author-events/{event_id}/tickets", payload, headers
        )

    def list_event_tickets_for_event(self, event_id, headers, params=None):
        return self._request(
            "GET", f"/author-events/{event_id}/tickets", headers=headers, params=params
        )

    def get_event_ticket(self, ticket_id, headers):
        return self._request("GET", f"/event-tickets/{ticket_id}", headers=headers)

    def list_event_tickets(self, headers, params=None):
        return self._request("GET", "/event-tickets", headers=headers, params=params)

    def check_in_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/event-tickets/{ticket_id}/check-in", headers=headers
        )

    def refund_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/event-tickets/{ticket_id}/refund", headers=headers
        )

    def cancel_author_event(self, event_id, headers):
        return self._request(
            "POST", f"/author-events/{event_id}/cancel", headers=headers
        )

    # ---- Consignment ------------------------------------------------------
    def create_consignment_agreement(self, payload, headers):
        return self._request("POST", "/consignment-agreements", payload, headers)

    def get_consignment_agreement(self, ag_id, headers):
        return self._request(
            "GET", f"/consignment-agreements/{ag_id}", headers=headers
        )

    def list_consignment_agreements(self, headers, params=None):
        return self._request(
            "GET", "/consignment-agreements", headers=headers, params=params
        )

    def create_consignment_copy(self, ag_id, payload, headers):
        return self._request(
            "POST", f"/consignment-agreements/{ag_id}/copies", payload, headers
        )

    def list_consignment_copies(self, ag_id, headers, params=None):
        return self._request(
            "GET", f"/consignment-agreements/{ag_id}/copies", headers=headers, params=params
        )

    def mark_copy_sold(self, copy_id, headers):
        return self._request(
            "POST", f"/consignment-copies/{copy_id}/mark-sold", headers=headers
        )

    def terminate_consignment_agreement(self, ag_id, headers):
        return self._request(
            "POST", f"/consignment-agreements/{ag_id}/terminate", headers=headers
        )


api_client = ApiClient()
