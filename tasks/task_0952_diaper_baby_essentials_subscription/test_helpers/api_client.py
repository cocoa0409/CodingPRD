"""API client: one method per endpoint the PRD declares."""

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Operator utilities
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    def run_daily_jobs(self, headers):
        return self._request("POST", "/_ops/run-daily-jobs", {}, headers)

    # ------------------------------------------------------------------
    # Accounts
    # ------------------------------------------------------------------
    def create_account(self, payload, headers):
        return self._request("POST", "/accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/accounts/{account_id}", headers=headers)

    def list_accounts(self, headers, params=None):
        return self._request("GET", "/accounts", payload=params, headers=headers)

    def update_account(self, account_id, payload, headers):
        return self._request("PATCH", f"/accounts/{account_id}", payload, headers)

    def verify_account(self, account_id, verification_token, headers):
        return self._request(
            "POST",
            f"/accounts/{account_id}/verify",
            {"verification_token": verification_token},
            headers,
        )

    def suspend_account(self, account_id, reason, headers):
        return self._request(
            "POST", f"/accounts/{account_id}/suspend", {"reason": reason}, headers
        )

    def reinstate_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/reinstate", {}, headers)

    def close_account(self, account_id, headers):
        return self._request("POST", f"/accounts/{account_id}/close", {}, headers)

    def get_credit_summary(self, account_id, headers, params=None):
        return self._request(
            "GET", f"/accounts/{account_id}/credit-summary", payload=params, headers=headers
        )

    # ------------------------------------------------------------------
    # Children, weights and allergen flags
    # ------------------------------------------------------------------
    def create_child(self, payload, headers):
        return self._request("POST", "/children", payload, headers)

    def get_child(self, child_id, headers):
        return self._request("GET", f"/children/{child_id}", headers=headers)

    def list_children(self, headers, params=None):
        return self._request("GET", "/children", payload=params, headers=headers)

    def update_child(self, child_id, payload, headers):
        return self._request("PATCH", f"/children/{child_id}", payload, headers)

    def record_weight_measurement(self, child_id, weight_grams, headers):
        return self._request(
            "POST",
            f"/children/{child_id}/weight-measurements",
            {"weight_grams": weight_grams},
            headers,
        )

    def create_allergen_flag(self, child_id, payload, headers):
        return self._request(
            "POST", f"/children/{child_id}/allergen-flags", payload, headers
        )

    def get_allergen_flag(self, flag_id, headers):
        return self._request("GET", f"/allergen-flags/{flag_id}", headers=headers)

    def list_allergen_flags(self, headers, params=None):
        return self._request("GET", "/allergen-flags", payload=params, headers=headers)

    def delete_allergen_flag(self, flag_id, headers):
        return self._request("DELETE", f"/allergen-flags/{flag_id}", headers=headers)

    # ------------------------------------------------------------------
    # Catalog: plans, SKUs, stock
    # ------------------------------------------------------------------
    def create_plan(self, payload, headers):
        return self._request("POST", "/plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/plans", payload=params, headers=headers)

    def update_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/plans/{plan_id}", payload, headers)

    def create_sku(self, payload, headers):
        return self._request("POST", "/skus", payload, headers)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"/skus/{sku_id}", headers=headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", "/skus", payload=params, headers=headers)

    def update_sku(self, sku_id, payload, headers):
        return self._request("PATCH", f"/skus/{sku_id}", payload, headers)

    def adjust_sku_stock(self, sku_id, delta_packs, headers):
        return self._request(
            "POST",
            f"/skus/{sku_id}/stock-adjustments",
            {"delta_packs": delta_packs},
            headers,
        )

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------
    def create_subscription(self, payload, headers):
        return self._request("POST", "/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/subscriptions", payload=params, headers=headers)

    def update_subscription(self, subscription_id, payload, headers):
        return self._request("PATCH", f"/subscriptions/{subscription_id}", payload, headers)

    def activate_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/activate", {}, headers
        )

    def set_cadence_override(self, subscription_id, cadence_override_days, headers):
        return self._request(
            "POST",
            f"/subscriptions/{subscription_id}/cadence-override",
            {"cadence_override_days": cadence_override_days},
            headers,
        )

    def clear_cadence_override(self, subscription_id, headers):
        return self._request(
            "DELETE", f"/subscriptions/{subscription_id}/cadence-override", headers=headers
        )

    def request_resize(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/resizes", payload, headers
        )

    def create_pause(self, subscription_id, payload, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/pauses", payload, headers
        )

    def resume_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/resume", {}, headers
        )

    def cancel_subscription(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cancel", {}, headers
        )

    def generate_cycle(self, subscription_id, headers):
        return self._request(
            "POST", f"/subscriptions/{subscription_id}/cycles", {}, headers
        )

    def get_cadence_projection(self, subscription_id, headers):
        return self._request(
            "GET", f"/subscriptions/{subscription_id}/cadence-projection", headers=headers
        )

    # ------------------------------------------------------------------
    # Cycles
    # ------------------------------------------------------------------
    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}", headers=headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/cycles", payload=params, headers=headers)

    def allocate_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/allocate", {}, headers)

    def lock_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/lock", {}, headers)

    def charge_cycle(self, cycle_id, headers, payload=None):
        return self._request("POST", f"/cycles/{cycle_id}/charge", payload or {}, headers)

    def dispatch_cycle(self, cycle_id, headers, payload=None):
        return self._request(
            "POST", f"/cycles/{cycle_id}/dispatch", payload or {}, headers
        )

    def deliver_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/deliver", {}, headers)

    def skip_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/skip", {}, headers)

    def revoke_skip(self, cycle_id, headers):
        return self._request("DELETE", f"/cycles/{cycle_id}/skip", headers=headers)

    def return_cycle(self, cycle_id, headers):
        return self._request("POST", f"/cycles/{cycle_id}/return", {}, headers)

    def create_cycle_refund_request(self, cycle_id, reason, headers):
        return self._request(
            "POST", f"/cycles/{cycle_id}/refund-requests", {"reason": reason}, headers
        )

    def get_pricing_preview(self, cycle_id, headers):
        return self._request("GET", f"/cycles/{cycle_id}/pricing-preview", headers=headers)

    # ------------------------------------------------------------------
    # Cycle lines
    # ------------------------------------------------------------------
    def get_cycle_line(self, line_id, headers):
        return self._request("GET", f"/cycle-lines/{line_id}", headers=headers)

    def list_cycle_lines(self, headers, params=None):
        return self._request("GET", "/cycle-lines", payload=params, headers=headers)

    def substitute_cycle_line(self, line_id, headers):
        return self._request("POST", f"/cycle-lines/{line_id}/substitute", {}, headers)

    def rescreen_cycle_line(self, line_id, headers):
        return self._request("POST", f"/cycle-lines/{line_id}/rescreen", {}, headers)

    # ------------------------------------------------------------------
    # Resize events, skip records, pause records
    # ------------------------------------------------------------------
    def get_resize_event(self, event_id, headers):
        return self._request("GET", f"/resize-events/{event_id}", headers=headers)

    def list_resize_events(self, headers, params=None):
        return self._request("GET", "/resize-events", payload=params, headers=headers)

    def get_skip_record(self, record_id, headers):
        return self._request("GET", f"/skip-records/{record_id}", headers=headers)

    def list_skip_records(self, headers, params=None):
        return self._request("GET", "/skip-records", payload=params, headers=headers)

    def get_pause_record(self, record_id, headers):
        return self._request("GET", f"/pause-records/{record_id}", headers=headers)

    def list_pause_records(self, headers, params=None):
        return self._request("GET", "/pause-records", payload=params, headers=headers)

    def cancel_pause_record(self, record_id, headers):
        return self._request("DELETE", f"/pause-records/{record_id}", headers=headers)

    # ------------------------------------------------------------------
    # Registries and registry items
    # ------------------------------------------------------------------
    def create_registry(self, payload, headers):
        return self._request("POST", "/registries", payload, headers)

    def get_registry(self, registry_id, headers):
        return self._request("GET", f"/registries/{registry_id}", headers=headers)

    def list_registries(self, headers, params=None):
        return self._request("GET", "/registries", payload=params, headers=headers)

    def update_registry(self, registry_id, payload, headers):
        return self._request("PATCH", f"/registries/{registry_id}", payload, headers)

    def open_registry(self, registry_id, headers):
        return self._request("POST", f"/registries/{registry_id}/open", {}, headers)

    def close_registry(self, registry_id, headers):
        return self._request("POST", f"/registries/{registry_id}/close", {}, headers)

    def reopen_registry(self, registry_id, headers):
        return self._request("POST", f"/registries/{registry_id}/reopen", {}, headers)

    def archive_registry(self, registry_id, headers):
        return self._request("POST", f"/registries/{registry_id}/archive", {}, headers)

    def get_registry_summary(self, registry_id, headers):
        return self._request("GET", f"/registries/{registry_id}/summary", headers=headers)

    def create_registry_item(self, registry_id, payload, headers):
        return self._request("POST", f"/registries/{registry_id}/items", payload, headers)

    def get_registry_item(self, item_id, headers):
        return self._request("GET", f"/registry-items/{item_id}", headers=headers)

    def list_registry_items(self, headers, params=None):
        return self._request("GET", "/registry-items", payload=params, headers=headers)

    def update_registry_item(self, registry_id, item_id, payload, headers):
        return self._request(
            "PATCH", f"/registries/{registry_id}/items/{item_id}", payload, headers
        )

    def delete_registry_item(self, registry_id, item_id, headers):
        return self._request(
            "DELETE", f"/registries/{registry_id}/items/{item_id}", headers=headers
        )

    # ------------------------------------------------------------------
    # Gift orders
    # ------------------------------------------------------------------
    def create_gift_order(self, payload, headers):
        return self._request("POST", "/gift-orders", payload, headers)

    def get_gift_order(self, gift_order_id, headers):
        return self._request("GET", f"/gift-orders/{gift_order_id}", headers=headers)

    def list_gift_orders(self, headers, params=None):
        return self._request("GET", "/gift-orders", payload=params, headers=headers)

    def pay_gift_order(self, gift_order_id, headers):
        return self._request("POST", f"/gift-orders/{gift_order_id}/pay", {}, headers)

    def claim_gift_order(self, gift_order_id, payload, headers):
        return self._request(
            "POST", f"/gift-orders/{gift_order_id}/claim", payload, headers
        )

    def refund_gift_order(self, gift_order_id, headers):
        return self._request("POST", f"/gift-orders/{gift_order_id}/refund", {}, headers)

    # ------------------------------------------------------------------
    # Credits
    # ------------------------------------------------------------------
    def issue_credit(self, payload, headers):
        return self._request("POST", "/credits", payload, headers)

    def get_credit(self, credit_id, headers):
        return self._request("GET", f"/credits/{credit_id}", headers=headers)

    def list_credits(self, headers, params=None):
        return self._request("GET", "/credits", payload=params, headers=headers)

    def revoke_credit(self, credit_id, headers):
        return self._request("POST", f"/credits/{credit_id}/revoke", {}, headers)

    def expire_credit(self, credit_id, headers):
        return self._request("POST", f"/credits/{credit_id}/expire", {}, headers)

    # ------------------------------------------------------------------
    # Shipments
    # ------------------------------------------------------------------
    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", payload=params, headers=headers)

    def pick_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/pick", {}, headers)

    def transit_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/transit", {}, headers)

    def exception_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/exception", {}, headers)

    def retry_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/retry", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/deliver", {}, headers)

    def return_shipment(self, shipment_id, headers):
        return self._request("POST", f"/shipments/{shipment_id}/return", {}, headers)

    # ------------------------------------------------------------------
    # Loyalty
    # ------------------------------------------------------------------
    def get_loyalty_account(self, loyalty_account_id, headers):
        return self._request(
            "GET", f"/loyalty-accounts/{loyalty_account_id}", headers=headers
        )

    def list_loyalty_accounts(self, headers, params=None):
        return self._request("GET", "/loyalty-accounts", payload=params, headers=headers)

    def redeem_points(self, loyalty_account_id, points, headers):
        return self._request(
            "POST",
            f"/loyalty-accounts/{loyalty_account_id}/redemptions",
            {"points": points},
            headers,
        )

    def expire_points(self, loyalty_account_id, headers):
        return self._request(
            "POST", f"/loyalty-accounts/{loyalty_account_id}/expire-points", {}, headers
        )

    def reevaluate_tier(self, loyalty_account_id, headers):
        return self._request(
            "POST", f"/loyalty-accounts/{loyalty_account_id}/reevaluate-tier", {}, headers
        )

    def get_points_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/points-ledger-entries/{entry_id}", headers=headers)

    def list_points_ledger_entries(self, headers, params=None):
        return self._request(
            "GET", "/points-ledger-entries", payload=params, headers=headers
        )

    # ------------------------------------------------------------------
    # Referrals
    # ------------------------------------------------------------------
    def create_referral(self, payload, headers):
        return self._request("POST", "/referrals", payload, headers)

    def get_referral(self, referral_id, headers):
        return self._request("GET", f"/referrals/{referral_id}", headers=headers)

    def list_referrals(self, headers, params=None):
        return self._request("GET", "/referrals", payload=params, headers=headers)

    def expire_referral(self, referral_id, headers):
        return self._request("POST", f"/referrals/{referral_id}/expire", {}, headers)

    # ------------------------------------------------------------------
    # Refunds
    # ------------------------------------------------------------------
    def get_refund(self, refund_id, headers):
        return self._request("GET", f"/refunds/{refund_id}", headers=headers)

    def list_refunds(self, headers, params=None):
        return self._request("GET", "/refunds", payload=params, headers=headers)

    def approve_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/approve", {}, headers)

    def settle_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/settle", {}, headers)

    def deny_refund(self, refund_id, headers):
        return self._request("POST", f"/refunds/{refund_id}/deny", {}, headers)

    # ------------------------------------------------------------------
    # Substitution events
    # ------------------------------------------------------------------
    def get_substitution_event(self, event_id, headers):
        return self._request("GET", f"/substitution-events/{event_id}", headers=headers)

    def list_substitution_events(self, headers, params=None):
        return self._request(
            "GET", "/substitution-events", payload=params, headers=headers
        )


api_client = ApiClient()
