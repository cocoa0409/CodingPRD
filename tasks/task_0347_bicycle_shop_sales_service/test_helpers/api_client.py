"""API client: one method per endpoint defined in the PRD §4.

All endpoints are mounted under the /shop prefix (PRD §4); the test-driving
clock is mounted under /_clock (PRD §3.3).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── Customer (PRD §3.1) ────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/shop/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/shop/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/shop/customers", headers=headers, params=params)

    # ─── Sku (PRD §3.1, §2.6) ───────────────────────────
    def create_sku(self, payload, headers):
        return self._request("POST", "/shop/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/shop/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/shop/skus", headers=headers, params=params)

    def restock_sku(self, sku_id, payload, headers):
        return self._request("POST", f"/shop/skus/{sku_id}/restock", payload, headers)

    def list_sku_reservations(self, sku_id, headers, params=None):
        return self._request("GET", f"/shop/skus/{sku_id}/reservations", headers=headers, params=params)

    def list_sku_recalls(self, sku_id, headers, params=None):
        return self._request("GET", f"/shop/skus/{sku_id}/recalls", headers=headers, params=params)

    # ─── TuneUpTier (PRD §3.2) ──────────────────────────
    def create_tune_up_tier(self, payload, headers):
        return self._request("POST", "/shop/tune-up-tiers", payload, headers)

    def get_tune_up_tier(self, tier_id, headers):
        return self._request("GET", f"/shop/tune-up-tiers/{tier_id}", headers=headers)

    def list_tune_up_tiers(self, headers, params=None):
        return self._request("GET", "/shop/tune-up-tiers", headers=headers, params=params)

    # ─── ServiceTicket (PRD §3.2) ───────────────────────
    def create_service_ticket(self, payload, headers):
        return self._request("POST", "/shop/service-tickets", payload, headers)

    def get_service_ticket(self, ticket_id, headers):
        return self._request("GET", f"/shop/service-tickets/{ticket_id}", headers=headers)

    def list_service_tickets(self, headers, params=None):
        return self._request("GET", "/shop/service-tickets", headers=headers, params=params)

    def quote_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/service-tickets/{ticket_id}/quote", headers=headers)

    def approve_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/service-tickets/{ticket_id}/approve", headers=headers)

    def complete_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/service-tickets/{ticket_id}/complete", headers=headers)

    def close_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/service-tickets/{ticket_id}/close", headers=headers)

    def cancel_service_ticket(self, ticket_id, headers):
        return self._request("POST", f"/shop/service-tickets/{ticket_id}/cancel", headers=headers)

    # ─── LaborLine (PRD §3.3) ───────────────────────────
    def create_labor_line(self, payload, headers):
        return self._request("POST", "/shop/labor-lines", payload, headers)

    def get_labor_line(self, line_id, headers):
        return self._request("GET", f"/shop/labor-lines/{line_id}", headers=headers)

    def list_labor_lines(self, headers, params=None):
        return self._request("GET", "/shop/labor-lines", headers=headers, params=params)

    # ─── ServiceBay (PRD §3.4) ──────────────────────────
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/shop/service-bays", payload, headers)

    def get_service_bay(self, bay_id, headers):
        return self._request("GET", f"/shop/service-bays/{bay_id}", headers=headers)

    def list_service_bays(self, headers, params=None):
        return self._request("GET", "/shop/service-bays", headers=headers, params=params)

    def list_bay_bookings_for_bay(self, bay_id, headers, params=None):
        return self._request("GET", f"/shop/service-bays/{bay_id}/bookings", headers=headers, params=params)

    # ─── BayBooking (PRD §3.4) ──────────────────────────
    def create_bay_booking(self, payload, headers):
        return self._request("POST", "/shop/bay-bookings", payload, headers)

    def get_bay_booking(self, booking_id, headers):
        return self._request("GET", f"/shop/bay-bookings/{booking_id}", headers=headers)

    def list_bay_bookings(self, headers, params=None):
        return self._request("GET", "/shop/bay-bookings", headers=headers, params=params)

    def release_bay_booking(self, booking_id, headers):
        return self._request("POST", f"/shop/bay-bookings/{booking_id}/release", headers=headers)

    # ─── SalesOrder (PRD §3.5) ──────────────────────────
    def create_sales_order(self, payload, headers):
        return self._request("POST", "/shop/sales-orders", payload, headers)

    def get_sales_order(self, order_id, headers):
        return self._request("GET", f"/shop/sales-orders/{order_id}", headers=headers)

    def list_sales_orders(self, headers, params=None):
        return self._request("GET", "/shop/sales-orders", headers=headers, params=params)

    def reserve_sales_order(self, order_id, payload, headers):
        return self._request("POST", f"/shop/sales-orders/{order_id}/reserve", payload, headers)

    def deliver_sales_order(self, order_id, headers):
        return self._request("POST", f"/shop/sales-orders/{order_id}/deliver", headers=headers)

    def cancel_sales_order(self, order_id, headers):
        return self._request("POST", f"/shop/sales-orders/{order_id}/cancel", headers=headers)

    # ─── OrderLine (PRD §3.5) ───────────────────────────
    def create_order_line(self, payload, headers):
        return self._request("POST", "/shop/order-lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/shop/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/shop/order-lines", headers=headers, params=params)

    # ─── Reservation (read-only; PRD §2.6) ──────────────
    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/shop/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/shop/reservations", headers=headers, params=params)

    # ─── LayawayPlan (PRD §3.7) ─────────────────────────
    def create_layaway_plan(self, payload, headers):
        return self._request("POST", "/shop/layaway-plans", payload, headers)

    def get_layaway_plan(self, plan_id, headers):
        return self._request("GET", f"/shop/layaway-plans/{plan_id}", headers=headers)

    def list_layaway_plans(self, headers, params=None):
        return self._request("GET", "/shop/layaway-plans", headers=headers, params=params)

    def fulfill_layaway_plan(self, plan_id, headers):
        return self._request("POST", f"/shop/layaway-plans/{plan_id}/fulfill", headers=headers)

    def forfeit_layaway_plan(self, plan_id, headers):
        return self._request("POST", f"/shop/layaway-plans/{plan_id}/forfeit", headers=headers)

    def cancel_layaway_plan(self, plan_id, headers):
        return self._request("POST", f"/shop/layaway-plans/{plan_id}/cancel", headers=headers)

    # ─── SpecialOrder (PRD §3.8) ────────────────────────
    def create_special_order(self, payload, headers):
        return self._request("POST", "/shop/special-orders", payload, headers)

    def get_special_order(self, order_id, headers):
        return self._request("GET", f"/shop/special-orders/{order_id}", headers=headers)

    def list_special_orders(self, headers, params=None):
        return self._request("GET", "/shop/special-orders", headers=headers, params=params)

    def confirm_special_order(self, order_id, headers):
        return self._request("POST", f"/shop/special-orders/{order_id}/confirm", headers=headers)

    def receive_special_order(self, order_id, headers):
        return self._request("POST", f"/shop/special-orders/{order_id}/receive", headers=headers)

    def fulfill_special_order(self, order_id, headers):
        return self._request("POST", f"/shop/special-orders/{order_id}/fulfill", headers=headers)

    def cancel_special_order(self, order_id, headers):
        return self._request("POST", f"/shop/special-orders/{order_id}/cancel", headers=headers)

    # ─── BuildJob (PRD §3.9) ────────────────────────────
    def create_build_job(self, payload, headers):
        return self._request("POST", "/shop/build-jobs", payload, headers)

    def get_build_job(self, build_id, headers):
        return self._request("GET", f"/shop/build-jobs/{build_id}", headers=headers)

    def list_build_jobs(self, headers, params=None):
        return self._request("GET", "/shop/build-jobs", headers=headers, params=params)

    def reserve_part_build_job(self, build_id, payload, headers):
        return self._request("POST", f"/shop/build-jobs/{build_id}/reserve-part", payload, headers)

    def reserve_frame_build_job(self, build_id, headers):
        return self._request("POST", f"/shop/build-jobs/{build_id}/reserve-frame", headers=headers)

    def mark_parts_reserved_build_job(self, build_id, headers):
        return self._request("POST", f"/shop/build-jobs/{build_id}/mark-parts-reserved", headers=headers)

    def start_build_job(self, build_id, headers):
        return self._request("POST", f"/shop/build-jobs/{build_id}/start", headers=headers)

    def complete_build_job(self, build_id, headers):
        return self._request("POST", f"/shop/build-jobs/{build_id}/complete", headers=headers)

    def cancel_build_job(self, build_id, headers):
        return self._request("POST", f"/shop/build-jobs/{build_id}/cancel", headers=headers)

    # ─── WarrantyClaim (PRD §3.10) ──────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/shop/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/shop/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/shop/warranty-claims", headers=headers, params=params)

    def review_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/shop/warranty-claims/{claim_id}/review", headers=headers)

    def approve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/shop/warranty-claims/{claim_id}/approve", payload, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/shop/warranty-claims/{claim_id}/deny", headers=headers)

    def resolve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/shop/warranty-claims/{claim_id}/resolve", headers=headers)

    # ─── TradeIn (PRD §3.11) ────────────────────────────
    def create_trade_in(self, payload, headers):
        return self._request("POST", "/shop/trade-ins", payload, headers)

    def get_trade_in(self, trade_in_id, headers):
        return self._request("GET", f"/shop/trade-ins/{trade_in_id}", headers=headers)

    def list_trade_ins(self, headers, params=None):
        return self._request("GET", "/shop/trade-ins", headers=headers, params=params)

    def accept_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/accept", headers=headers)

    def reject_trade_in(self, trade_in_id, headers):
        return self._request("POST", f"/shop/trade-ins/{trade_in_id}/reject", headers=headers)

    # ─── Payment (PRD §3.6) ─────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/shop/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/shop/payments", headers=headers, params=params)

    # ─── RecallNotice (PRD §3.11) ───────────────────────
    def create_recall_notice(self, payload, headers):
        return self._request("POST", "/shop/recall-notices", payload, headers)

    def get_recall_notice(self, recall_id, headers):
        return self._request("GET", f"/shop/recall-notices/{recall_id}", headers=headers)

    def list_recall_notices(self, headers, params=None):
        return self._request("GET", "/shop/recall-notices", headers=headers, params=params)

    # ─── RecallAck (PRD §3.11) ──────────────────────────
    def create_recall_ack(self, payload, headers):
        return self._request("POST", "/shop/recall-acks", payload, headers)

    def get_recall_ack(self, ack_id, headers):
        return self._request("GET", f"/shop/recall-acks/{ack_id}", headers=headers)

    def list_recall_acks(self, headers, params=None):
        return self._request("GET", "/shop/recall-acks", headers=headers, params=params)

    # ─── Test-driving clock (PRD §3.3) ──────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
