"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving capability, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/dealer/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ------------------------------------------------------------------
    # Seed programs
    # ------------------------------------------------------------------
    def create_program(self, payload, headers):
        return self._request("POST", "/dealer/programs", payload, headers)

    def get_program(self, program_id, headers):
        return self._request("GET", f"/dealer/programs/{program_id}", headers=headers)

    def list_programs(self, headers, params=None):
        return self._request("GET", "/dealer/programs", headers=headers, params=params)

    def open_program(self, program_id, headers):
        return self._request("POST", f"/dealer/programs/{program_id}/open", {}, headers)

    def close_sales(self, program_id, headers):
        return self._request("POST", f"/dealer/programs/{program_id}/close_sales", {}, headers)

    def settle_program(self, program_id, headers):
        return self._request("POST", f"/dealer/programs/{program_id}/settle", {}, headers)

    # ------------------------------------------------------------------
    # Trait packages
    # ------------------------------------------------------------------
    def create_trait_package(self, payload, headers):
        return self._request("POST", "/dealer/trait-packages", payload, headers)

    def get_trait_package(self, package_id, headers):
        return self._request("GET", f"/dealer/trait-packages/{package_id}", headers=headers)

    def list_trait_packages(self, headers, params=None):
        return self._request("GET", "/dealer/trait-packages", headers=headers, params=params)

    def retire_trait_package(self, package_id, headers):
        return self._request("POST", f"/dealer/trait-packages/{package_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Varieties
    # ------------------------------------------------------------------
    def create_variety(self, payload, headers):
        return self._request("POST", "/dealer/varieties", payload, headers)

    def get_variety(self, variety_id, headers):
        return self._request("GET", f"/dealer/varieties/{variety_id}", headers=headers)

    def list_varieties(self, headers, params=None):
        return self._request("GET", "/dealer/varieties", headers=headers, params=params)

    def delist_variety(self, variety_id, headers):
        return self._request("POST", f"/dealer/varieties/{variety_id}/delist", {}, headers)

    # ------------------------------------------------------------------
    # Grower accounts
    # ------------------------------------------------------------------
    def create_grower(self, payload, headers):
        return self._request("POST", "/dealer/growers", payload, headers)

    def get_grower(self, grower_id, headers):
        return self._request("GET", f"/dealer/growers/{grower_id}", headers=headers)

    def list_growers(self, headers, params=None):
        return self._request("GET", "/dealer/growers", headers=headers, params=params)

    def hold_grower(self, grower_id, headers):
        return self._request("POST", f"/dealer/growers/{grower_id}/hold", {}, headers)

    def release_grower_hold(self, grower_id, headers):
        return self._request("POST", f"/dealer/growers/{grower_id}/release_hold", {}, headers)

    def deactivate_grower(self, grower_id, headers):
        return self._request("POST", f"/dealer/growers/{grower_id}/deactivate", {}, headers)

    def refund_prepay(self, grower_id, order_id, headers):
        return self._request(
            "POST", f"/dealer/growers/{grower_id}/refund_prepay", {"order_id": order_id}, headers
        )

    # ------------------------------------------------------------------
    # Fields
    # ------------------------------------------------------------------
    def create_field(self, payload, headers):
        return self._request("POST", "/dealer/fields", payload, headers)

    def get_field(self, field_id, headers):
        return self._request("GET", f"/dealer/fields/{field_id}", headers=headers)

    def list_fields(self, headers, params=None):
        return self._request("GET", "/dealer/fields", headers=headers, params=params)

    def retire_field(self, field_id, headers):
        return self._request("POST", f"/dealer/fields/{field_id}/retire", {}, headers)

    # ------------------------------------------------------------------
    # Trait agreements
    # ------------------------------------------------------------------
    def create_trait_agreement(self, payload, headers):
        return self._request("POST", "/dealer/trait-agreements", payload, headers)

    def get_trait_agreement(self, agreement_id, headers):
        return self._request("GET", f"/dealer/trait-agreements/{agreement_id}", headers=headers)

    def list_trait_agreements(self, headers, params=None):
        return self._request("GET", "/dealer/trait-agreements", headers=headers, params=params)

    def sign_trait_agreement(self, agreement_id, headers):
        return self._request("POST", f"/dealer/trait-agreements/{agreement_id}/sign", {}, headers)

    def suspend_trait_agreement(self, agreement_id, reason, headers):
        return self._request(
            "POST", f"/dealer/trait-agreements/{agreement_id}/suspend", {"reason": reason}, headers
        )

    def reinstate_trait_agreement(self, agreement_id, headers):
        return self._request(
            "POST", f"/dealer/trait-agreements/{agreement_id}/reinstate", {}, headers
        )

    def revoke_trait_agreement(self, agreement_id, headers):
        return self._request("POST", f"/dealer/trait-agreements/{agreement_id}/revoke", {}, headers)

    # ------------------------------------------------------------------
    # Placement recommendations
    # ------------------------------------------------------------------
    def create_recommendation(self, payload, headers):
        return self._request("POST", "/dealer/recommendations", payload, headers)

    def get_recommendation(self, recommendation_id, headers):
        return self._request(
            "GET", f"/dealer/recommendations/{recommendation_id}", headers=headers
        )

    def list_recommendations(self, headers, params=None):
        return self._request("GET", "/dealer/recommendations", headers=headers, params=params)

    def publish_recommendation(self, recommendation_id, headers):
        return self._request(
            "POST", f"/dealer/recommendations/{recommendation_id}/publish", {}, headers
        )

    def accept_recommendation(self, recommendation_id, headers):
        return self._request(
            "POST", f"/dealer/recommendations/{recommendation_id}/accept", {}, headers
        )

    def withdraw_recommendation(self, recommendation_id, headers):
        return self._request(
            "POST", f"/dealer/recommendations/{recommendation_id}/withdraw", {}, headers
        )

    # ------------------------------------------------------------------
    # Seed orders and order lines
    # ------------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/dealer/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/dealer/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/dealer/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/dealer/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/dealer/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/dealer/order-lines", headers=headers, params=params)

    def confirm_order(self, order_id, headers):
        return self._request("POST", f"/dealer/orders/{order_id}/confirm", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/dealer/orders/{order_id}/cancel", {}, headers)

    def release_order_hold(self, order_id, headers):
        return self._request("POST", f"/dealer/orders/{order_id}/release_hold", {}, headers)

    def prepay_order(self, order_id, amount_cents, headers):
        return self._request(
            "POST", f"/dealer/orders/{order_id}/prepay", {"amount_cents": amount_cents}, headers
        )

    def record_payment(self, order_id, amount_cents, headers):
        return self._request(
            "POST",
            f"/dealer/orders/{order_id}/record_payment",
            {"amount_cents": amount_cents},
            headers,
        )

    # ------------------------------------------------------------------
    # Treatment options
    # ------------------------------------------------------------------
    def create_treatment_option(self, payload, headers):
        return self._request("POST", "/dealer/treatment-options", payload, headers)

    def get_treatment_option(self, option_id, headers):
        return self._request("GET", f"/dealer/treatment-options/{option_id}", headers=headers)

    def list_treatment_options(self, headers, params=None):
        return self._request("GET", "/dealer/treatment-options", headers=headers, params=params)

    def discontinue_treatment_option(self, option_id, headers):
        return self._request(
            "POST", f"/dealer/treatment-options/{option_id}/discontinue", {}, headers
        )

    # ------------------------------------------------------------------
    # Inventory lots
    # ------------------------------------------------------------------
    def create_inventory_lot(self, payload, headers):
        return self._request("POST", "/dealer/inventory-lots", payload, headers)

    def get_inventory_lot(self, lot_id, headers):
        return self._request("GET", f"/dealer/inventory-lots/{lot_id}", headers=headers)

    def list_inventory_lots(self, headers, params=None):
        return self._request("GET", "/dealer/inventory-lots", headers=headers, params=params)

    def quarantine_lot(self, lot_id, headers):
        return self._request("POST", f"/dealer/inventory-lots/{lot_id}/quarantine", {}, headers)

    def release_quarantine(self, lot_id, headers):
        return self._request(
            "POST", f"/dealer/inventory-lots/{lot_id}/release_quarantine", {}, headers
        )

    # ------------------------------------------------------------------
    # Delivery tickets
    # ------------------------------------------------------------------
    def create_delivery_ticket(self, payload, headers):
        return self._request("POST", "/dealer/delivery-tickets", payload, headers)

    def get_delivery_ticket(self, ticket_id, headers):
        return self._request("GET", f"/dealer/delivery-tickets/{ticket_id}", headers=headers)

    def list_delivery_tickets(self, headers, params=None):
        return self._request("GET", "/dealer/delivery-tickets", headers=headers, params=params)

    def complete_delivery_ticket(self, ticket_id, headers):
        return self._request(
            "POST", f"/dealer/delivery-tickets/{ticket_id}/complete", {}, headers
        )

    def cancel_delivery_ticket(self, ticket_id, headers):
        return self._request("POST", f"/dealer/delivery-tickets/{ticket_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Seed returns
    # ------------------------------------------------------------------
    def create_return(self, payload, headers):
        return self._request("POST", "/dealer/returns", payload, headers)

    def get_return(self, return_id, headers):
        return self._request("GET", f"/dealer/returns/{return_id}", headers=headers)

    def list_returns(self, headers, params=None):
        return self._request("GET", "/dealer/returns", headers=headers, params=params)

    def approve_return(self, return_id, headers):
        return self._request("POST", f"/dealer/returns/{return_id}/approve", {}, headers)

    def receive_return(self, return_id, headers):
        return self._request("POST", f"/dealer/returns/{return_id}/receive", {}, headers)

    def credit_return(self, return_id, headers):
        return self._request("POST", f"/dealer/returns/{return_id}/credit", {}, headers)

    def reject_return(self, return_id, headers, note=None):
        payload = {} if note is None else {"note": note}
        return self._request("POST", f"/dealer/returns/{return_id}/reject", payload, headers)

    # ------------------------------------------------------------------
    # Replant claims
    # ------------------------------------------------------------------
    def create_replant_claim(self, payload, headers):
        return self._request("POST", "/dealer/replant-claims", payload, headers)

    def get_replant_claim(self, claim_id, headers):
        return self._request("GET", f"/dealer/replant-claims/{claim_id}", headers=headers)

    def list_replant_claims(self, headers, params=None):
        return self._request("GET", "/dealer/replant-claims", headers=headers, params=params)

    def start_claim_review(self, claim_id, headers):
        return self._request(
            "POST", f"/dealer/replant-claims/{claim_id}/start_review", {}, headers
        )

    def request_claim_info(self, claim_id, headers, note=None):
        payload = {} if note is None else {"note": note}
        return self._request(
            "POST", f"/dealer/replant-claims/{claim_id}/request_info", payload, headers
        )

    def provide_claim_info(self, claim_id, headers, note=None):
        payload = {} if note is None else {"note": note}
        return self._request(
            "POST", f"/dealer/replant-claims/{claim_id}/provide_info", payload, headers
        )

    def approve_claim(self, claim_id, headers):
        return self._request("POST", f"/dealer/replant-claims/{claim_id}/approve", {}, headers)

    def deny_claim(self, claim_id, denial_reason, headers):
        return self._request(
            "POST",
            f"/dealer/replant-claims/{claim_id}/deny",
            {"denial_reason": denial_reason},
            headers,
        )

    def withdraw_claim(self, claim_id, headers):
        return self._request("POST", f"/dealer/replant-claims/{claim_id}/withdraw", {}, headers)

    # ------------------------------------------------------------------
    # Plot trials
    # ------------------------------------------------------------------
    def create_plot_trial(self, payload, headers):
        return self._request("POST", "/dealer/plot-trials", payload, headers)

    def get_plot_trial(self, trial_id, headers):
        return self._request("GET", f"/dealer/plot-trials/{trial_id}", headers=headers)

    def list_plot_trials(self, headers, params=None):
        return self._request("GET", "/dealer/plot-trials", headers=headers, params=params)

    def record_planting(self, trial_id, headers):
        return self._request(
            "POST", f"/dealer/plot-trials/{trial_id}/record_planting", {}, headers
        )

    def record_harvest(self, trial_id, yield_bu_per_acre, moisture_pct, headers):
        return self._request(
            "POST",
            f"/dealer/plot-trials/{trial_id}/record_harvest",
            {"yield_bu_per_acre": yield_bu_per_acre, "moisture_pct": moisture_pct},
            headers,
        )

    def publish_plot_trial(self, trial_id, headers):
        return self._request("POST", f"/dealer/plot-trials/{trial_id}/publish", {}, headers)

    def discard_plot_trial(self, trial_id, headers):
        return self._request("POST", f"/dealer/plot-trials/{trial_id}/discard", {}, headers)

    # ------------------------------------------------------------------
    # Commission statements
    # ------------------------------------------------------------------
    def get_commission_statement(self, statement_id, headers):
        return self._request(
            "GET", f"/dealer/commission-statements/{statement_id}", headers=headers
        )

    def list_commission_statements(self, headers, params=None):
        return self._request(
            "GET", "/dealer/commission-statements", headers=headers, params=params
        )

    def recompute_commission_statement(self, statement_id, headers):
        return self._request(
            "POST", f"/dealer/commission-statements/{statement_id}/recompute", {}, headers
        )

    def mark_commission_paid(self, statement_id, headers):
        return self._request(
            "POST", f"/dealer/commission-statements/{statement_id}/mark_paid", {}, headers
        )


api_client = ApiClient()
