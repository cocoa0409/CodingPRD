"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Service plans ---
    def create_service_plan(self, payload, headers):
        return self._request("POST", "/service-plans", payload, headers)

    def get_service_plan(self, plan_id, headers):
        return self._request("GET", f"/service-plans/{plan_id}", headers=headers)

    # --- Subscribers ---
    def create_subscriber(self, payload, headers):
        return self._request("POST", "/subscribers", payload, headers)

    def get_subscriber(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}", headers=headers)

    def get_impact(self, subscriber_id, headers):
        return self._request("GET", f"/subscribers/{subscriber_id}/impact", headers=headers)

    def create_credit_adjustment(self, subscriber_id, payload, headers):
        return self._request(
            "POST", f"/subscribers/{subscriber_id}/credit-adjustments", payload, headers
        )

    # --- Subscriptions ---
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", headers=headers, params=params)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def pause_subscription(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/pause", payload, headers
        )

    def resume_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/resume", {}, headers
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", {}, headers
        )

    def plan_change(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/plan-change", payload, headers
        )

    # --- Routes ---
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def generate_stops(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/generate-stops", payload, headers
        )

    def post_weigh_ticket(self, route_id, payload, headers):
        return self._request(
            "POST", f"/routes/{route_id}/weigh-tickets", payload, headers
        )

    # --- Bins ---
    def create_bin(self, payload, headers):
        return self._request("POST", "/bins", payload, headers)

    def list_bins(self, headers, params=None):
        return self._request("GET", "/bins", headers=headers, params=params)

    def get_bin(self, bin_id, headers):
        return self._request("GET", f"/bins/{bin_id}", headers=headers)

    def wash_bin(self, bin_id, headers):
        return self._request("POST", f"/bins/{bin_id}/wash", {}, headers)

    # --- Pickups ---
    def list_pickups(self, headers, params=None):
        return self._request("GET", "/pickups", headers=headers, params=params)

    def get_pickup(self, pickup_id, headers):
        return self._request("GET", f"/pickups/{pickup_id}", headers=headers)

    def complete_pickup(self, pickup_id, payload, headers):
        return self._request("POST", f"/pickups/{pickup_id}/complete", payload, headers)

    def miss_pickup(self, pickup_id, headers):
        return self._request("POST", f"/pickups/{pickup_id}/miss", {}, headers)

    def skip_pickup(self, pickup_id, headers):
        return self._request("POST", f"/pickups/{pickup_id}/skip", {}, headers)

    def void_pickup(self, pickup_id, headers):
        return self._request("POST", f"/pickups/{pickup_id}/void", {}, headers)

    # --- Contamination tags ---
    def create_contamination_tag(self, pickup_id, payload, headers):
        return self._request(
            "POST", f"/pickups/{pickup_id}/contamination-tags", payload, headers
        )

    def list_contamination_tags(self, headers, params=None):
        return self._request("GET", "/contamination-tags", headers=headers, params=params)

    def get_contamination_tag(self, tag_id, headers):
        return self._request("GET", f"/contamination-tags/{tag_id}", headers=headers)

    def dispute_tag(self, tag_id, headers):
        return self._request("POST", f"/contamination-tags/{tag_id}/dispute", {}, headers)

    def confirm_tag(self, tag_id, headers):
        return self._request("POST", f"/contamination-tags/{tag_id}/confirm", {}, headers)

    def waive_tag(self, tag_id, headers):
        return self._request("POST", f"/contamination-tags/{tag_id}/waive", {}, headers)

    # --- Weigh tickets ---
    def list_weigh_tickets(self, headers, params=None):
        return self._request("GET", "/weigh-tickets", headers=headers, params=params)

    def get_weigh_ticket(self, ticket_id, headers):
        return self._request("GET", f"/weigh-tickets/{ticket_id}", headers=headers)

    # --- Credit ledger ---
    def list_credit_entries(self, headers, params=None):
        return self._request("GET", "/credit-entries", headers=headers, params=params)

    def get_credit_entry(self, entry_id, headers):
        return self._request("GET", f"/credit-entries/{entry_id}", headers=headers)

    # --- Credit redemptions ---
    def create_redemption(self, payload, headers):
        return self._request("POST", "/credit-redemptions", payload, headers)

    def list_redemptions(self, headers, params=None):
        return self._request("GET", "/credit-redemptions", headers=headers, params=params)

    def get_redemption(self, redemption_id, headers):
        return self._request("GET", f"/credit-redemptions/{redemption_id}", headers=headers)

    def fulfill_redemption(self, redemption_id, headers):
        return self._request(
            "POST", f"/credit-redemptions/{redemption_id}/fulfill", {}, headers
        )

    def cancel_redemption(self, redemption_id, headers):
        return self._request(
            "POST", f"/credit-redemptions/{redemption_id}/cancel", {}, headers
        )

    # --- Compost stock ---
    def get_compost_stock(self, headers):
        return self._request("GET", "/compost-stock", headers=headers)

    # --- Billing / invoices ---
    def run_billing(self, payload, headers):
        return self._request("POST", "/billing/run", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/void", {}, headers)

    # --- Logical clock (test-driving capability, PRD §2.4) ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
