"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/fundraiser/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Campaigns
    # ------------------------------------------------------------------
    def create_campaign(self, payload, headers):
        return self._request("POST", "/fundraiser/campaigns", payload, headers)

    def get_campaign(self, campaign_id, headers):
        return self._request("GET", f"/fundraiser/campaigns/{campaign_id}",
                             headers=headers)

    def patch_campaign(self, campaign_id, payload, headers):
        return self._request("PATCH", f"/fundraiser/campaigns/{campaign_id}",
                             payload, headers)

    def open_campaign(self, campaign_id, headers):
        return self._request("POST", f"/fundraiser/campaigns/{campaign_id}/open",
                             {}, headers)

    def close_ordering(self, campaign_id, headers):
        return self._request("POST",
                             f"/fundraiser/campaigns/{campaign_id}/close-ordering",
                             {}, headers)

    def mark_sorted(self, campaign_id, headers):
        return self._request("POST",
                             f"/fundraiser/campaigns/{campaign_id}/mark-sorted",
                             {}, headers)

    def complete_distribution(self, campaign_id, headers):
        return self._request(
            "POST", f"/fundraiser/campaigns/{campaign_id}/complete-distribution",
            {}, headers)

    def reconcile_campaign(self, campaign_id, headers):
        return self._request("POST",
                             f"/fundraiser/campaigns/{campaign_id}/reconcile",
                             {}, headers)

    def close_campaign(self, campaign_id, headers):
        return self._request("POST", f"/fundraiser/campaigns/{campaign_id}/close",
                             {}, headers)

    def cancel_campaign(self, campaign_id, headers):
        return self._request("POST", f"/fundraiser/campaigns/{campaign_id}/cancel",
                             {}, headers)

    def generate_sort_tickets(self, campaign_id, headers):
        return self._request(
            "POST", f"/fundraiser/campaigns/{campaign_id}/generate-sort-tickets",
            {}, headers)

    def list_campaign_groups(self, campaign_id, headers, params=None):
        return self._request("GET", f"/fundraiser/campaigns/{campaign_id}/groups",
                             headers=headers, params=params)

    def list_campaign_products(self, campaign_id, headers, params=None):
        return self._request("GET",
                             f"/fundraiser/campaigns/{campaign_id}/products",
                             headers=headers, params=params)

    def list_campaign_prizes(self, campaign_id, headers, params=None):
        return self._request("GET", f"/fundraiser/campaigns/{campaign_id}/prizes",
                             headers=headers, params=params)

    def list_campaign_sellers(self, campaign_id, headers, params=None):
        return self._request("GET",
                             f"/fundraiser/campaigns/{campaign_id}/sellers",
                             headers=headers, params=params)

    def list_campaign_supplier_orders(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/fundraiser/campaigns/{campaign_id}/supplier-orders",
            headers=headers, params=params)

    def list_campaign_distribution_events(self, campaign_id, headers, params=None):
        return self._request(
            "GET", f"/fundraiser/campaigns/{campaign_id}/distribution-events",
            headers=headers, params=params)

    def list_campaign_ledger(self, campaign_id, headers, params=None):
        return self._request("GET", f"/fundraiser/campaigns/{campaign_id}/ledger",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Student groups
    # ------------------------------------------------------------------
    def create_group(self, payload, headers):
        return self._request("POST", "/fundraiser/groups", payload, headers)

    def get_group(self, group_id, headers):
        return self._request("GET", f"/fundraiser/groups/{group_id}",
                             headers=headers)

    def list_group_sellers(self, group_id, headers, params=None):
        return self._request("GET", f"/fundraiser/groups/{group_id}/sellers",
                             headers=headers, params=params)

    def list_group_ledger(self, group_id, headers, params=None):
        return self._request("GET", f"/fundraiser/groups/{group_id}/ledger",
                             headers=headers, params=params)

    def create_group_adjustment(self, group_id, payload, headers):
        return self._request("POST",
                             f"/fundraiser/groups/{group_id}/adjustments",
                             payload, headers)

    # ------------------------------------------------------------------
    # Products
    # ------------------------------------------------------------------
    def create_product(self, payload, headers):
        return self._request("POST", "/fundraiser/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/fundraiser/products/{product_id}",
                             headers=headers)

    def patch_product(self, product_id, payload, headers):
        return self._request("PATCH", f"/fundraiser/products/{product_id}",
                             payload, headers)

    def discontinue_product(self, product_id, headers):
        return self._request("POST",
                             f"/fundraiser/products/{product_id}/discontinue",
                             {}, headers)

    def list_product_order_lines(self, product_id, headers, params=None):
        return self._request("GET",
                             f"/fundraiser/products/{product_id}/order-lines",
                             headers=headers, params=params)

    def list_product_supplier_order_lines(self, product_id, headers, params=None):
        return self._request(
            "GET", f"/fundraiser/products/{product_id}/supplier-order-lines",
            headers=headers, params=params)

    # ------------------------------------------------------------------
    # Prizes
    # ------------------------------------------------------------------
    def create_prize(self, payload, headers):
        return self._request("POST", "/fundraiser/prizes", payload, headers)

    def get_prize(self, prize_id, headers):
        return self._request("GET", f"/fundraiser/prizes/{prize_id}",
                             headers=headers)

    # ------------------------------------------------------------------
    # Sellers
    # ------------------------------------------------------------------
    def create_seller(self, payload, headers):
        return self._request("POST", "/fundraiser/sellers", payload, headers)

    def get_seller(self, seller_id, headers):
        return self._request("GET", f"/fundraiser/sellers/{seller_id}",
                             headers=headers)

    def suspend_seller(self, seller_id, headers):
        return self._request("POST", f"/fundraiser/sellers/{seller_id}/suspend",
                             {}, headers)

    def reinstate_seller(self, seller_id, headers):
        return self._request("POST", f"/fundraiser/sellers/{seller_id}/reinstate",
                             {}, headers)

    def withdraw_seller(self, seller_id, headers):
        return self._request("POST", f"/fundraiser/sellers/{seller_id}/withdraw",
                             {}, headers)

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/fundraiser/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/fundraiser/orders", headers=headers,
                             params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/fundraiser/orders/{order_id}",
                             headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/fundraiser/orders/{order_id}/submit",
                             {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/fundraiser/orders/{order_id}/cancel",
                             {}, headers)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/fundraiser/orders/{order_id}/lines",
                             headers=headers, params=params)

    def list_order_payments(self, order_id, headers, params=None):
        return self._request("GET", f"/fundraiser/orders/{order_id}/payments",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Payments
    # ------------------------------------------------------------------
    def create_payment(self, payload, headers):
        return self._request("POST", "/fundraiser/payments", payload, headers)

    def clear_payment(self, payment_id, headers):
        return self._request("POST", f"/fundraiser/payments/{payment_id}/clear",
                             {}, headers)

    def bounce_payment(self, payment_id, headers, payload=None):
        return self._request("POST", f"/fundraiser/payments/{payment_id}/bounce",
                             payload or {}, headers)

    def refund_payment(self, payment_id, payload, headers):
        return self._request("POST", f"/fundraiser/payments/{payment_id}/refund",
                             payload, headers)

    def void_payment(self, payment_id, headers):
        return self._request("POST", f"/fundraiser/payments/{payment_id}/void",
                             {}, headers)

    # ------------------------------------------------------------------
    # Supplier orders
    # ------------------------------------------------------------------
    def create_supplier_order(self, payload, headers):
        return self._request("POST", "/fundraiser/supplier-orders", payload,
                             headers)

    def get_supplier_order(self, supplier_order_id, headers):
        return self._request("GET",
                             f"/fundraiser/supplier-orders/{supplier_order_id}",
                             headers=headers)

    def list_supplier_order_lines(self, supplier_order_id, headers, params=None):
        return self._request(
            "GET", f"/fundraiser/supplier-orders/{supplier_order_id}/lines",
            headers=headers, params=params)

    def patch_supplier_order(self, supplier_order_id, payload, headers):
        return self._request("PATCH",
                             f"/fundraiser/supplier-orders/{supplier_order_id}",
                             payload, headers)

    def submit_supplier_order(self, supplier_order_id, headers):
        return self._request(
            "POST", f"/fundraiser/supplier-orders/{supplier_order_id}/submit",
            {}, headers)

    def unsubmit_supplier_order(self, supplier_order_id, headers):
        return self._request(
            "POST", f"/fundraiser/supplier-orders/{supplier_order_id}/unsubmit",
            {}, headers)

    def acknowledge_supplier_order(self, supplier_order_id, payload, headers):
        return self._request(
            "POST", f"/fundraiser/supplier-orders/{supplier_order_id}/acknowledge",
            payload, headers)

    def deliver_supplier_order(self, supplier_order_id, payload, headers):
        return self._request(
            "POST", f"/fundraiser/supplier-orders/{supplier_order_id}/deliver",
            payload, headers)

    def cancel_supplier_order(self, supplier_order_id, headers):
        return self._request(
            "POST", f"/fundraiser/supplier-orders/{supplier_order_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Distribution events
    # ------------------------------------------------------------------
    def create_distribution_event(self, payload, headers):
        return self._request("POST", "/fundraiser/distribution-events", payload,
                             headers)

    def get_distribution_event(self, event_id, headers):
        return self._request("GET", f"/fundraiser/distribution-events/{event_id}",
                             headers=headers)

    def complete_distribution_event(self, event_id, headers):
        return self._request(
            "POST", f"/fundraiser/distribution-events/{event_id}/complete",
            {}, headers)

    def cancel_distribution_event(self, event_id, headers):
        return self._request(
            "POST", f"/fundraiser/distribution-events/{event_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Sort tickets
    # ------------------------------------------------------------------
    def list_sort_tickets(self, headers, params=None):
        return self._request("GET", "/fundraiser/sort-tickets", headers=headers,
                             params=params)

    def get_sort_ticket(self, ticket_id, headers):
        return self._request("GET", f"/fundraiser/sort-tickets/{ticket_id}",
                             headers=headers)

    def verify_sort_ticket(self, ticket_id, payload, headers):
        return self._request("POST",
                             f"/fundraiser/sort-tickets/{ticket_id}/verify",
                             payload, headers)

    # ------------------------------------------------------------------
    # Pickup appointments
    # ------------------------------------------------------------------
    def create_pickup_appointment(self, payload, headers):
        return self._request("POST", "/fundraiser/pickup-appointments", payload,
                             headers)

    def list_pickup_appointments(self, headers, params=None):
        return self._request("GET", "/fundraiser/pickup-appointments",
                             headers=headers, params=params)

    def get_pickup_appointment(self, appointment_id, headers):
        return self._request("GET",
                             f"/fundraiser/pickup-appointments/{appointment_id}",
                             headers=headers)

    def complete_pickup_appointment(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/fundraiser/pickup-appointments/{appointment_id}/complete",
            payload, headers)

    def cancel_pickup_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/fundraiser/pickup-appointments/{appointment_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Reconciliation claims
    # ------------------------------------------------------------------
    def create_claim(self, payload, headers):
        return self._request("POST", "/fundraiser/reconciliation-claims", payload,
                             headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/fundraiser/reconciliation-claims",
                             headers=headers, params=params)

    def get_claim(self, claim_id, headers):
        return self._request("GET",
                             f"/fundraiser/reconciliation-claims/{claim_id}",
                             headers=headers)

    def approve_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/fundraiser/reconciliation-claims/{claim_id}/approve",
            {}, headers)

    def deny_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/fundraiser/reconciliation-claims/{claim_id}/deny",
            payload or {}, headers)

    def appeal_claim(self, claim_id, headers, payload=None):
        return self._request(
            "POST", f"/fundraiser/reconciliation-claims/{claim_id}/appeal",
            payload or {}, headers)

    def resolve_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/fundraiser/reconciliation-claims/{claim_id}/resolve",
            payload, headers)

    # ------------------------------------------------------------------
    # Return requests
    # ------------------------------------------------------------------
    def create_return_request(self, payload, headers):
        return self._request("POST", "/fundraiser/return-requests", payload,
                             headers)

    def list_return_requests(self, headers, params=None):
        return self._request("GET", "/fundraiser/return-requests", headers=headers,
                             params=params)

    def get_return_request(self, return_id, headers):
        return self._request("GET", f"/fundraiser/return-requests/{return_id}",
                             headers=headers)

    def approve_return_request(self, return_id, headers):
        return self._request(
            "POST", f"/fundraiser/return-requests/{return_id}/approve", {},
            headers)

    def reject_return_request(self, return_id, headers, payload=None):
        return self._request(
            "POST", f"/fundraiser/return-requests/{return_id}/reject",
            payload or {}, headers)

    def resubmit_return_request(self, return_id, payload, headers):
        return self._request(
            "POST", f"/fundraiser/return-requests/{return_id}/resubmit", payload,
            headers)

    def receive_return_request(self, return_id, payload, headers):
        return self._request(
            "POST", f"/fundraiser/return-requests/{return_id}/receive", payload,
            headers)

    # ------------------------------------------------------------------
    # Prize awards
    # ------------------------------------------------------------------
    def list_prize_awards(self, headers, params=None):
        return self._request("GET", "/fundraiser/prize-awards", headers=headers,
                             params=params)

    def get_prize_award(self, award_id, headers):
        return self._request("GET", f"/fundraiser/prize-awards/{award_id}",
                             headers=headers)

    def fulfill_prize_award(self, award_id, headers):
        return self._request(
            "POST", f"/fundraiser/prize-awards/{award_id}/fulfill", {}, headers)


api_client = ApiClient()
