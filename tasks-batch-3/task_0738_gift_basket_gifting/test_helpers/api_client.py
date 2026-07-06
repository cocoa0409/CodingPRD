"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Catalog & fulfillment configuration ──────────────────────────────
    def create_template(self, payload, headers):
        return self._request("POST", "/gift-basket-templates", payload, headers)

    def update_template(self, template_id, payload, headers):
        return self._request("PATCH", f"/gift-basket-templates/{template_id}", payload, headers)

    def create_sku(self, payload, headers):
        return self._request("POST", "/component-skus", payload, headers)

    def create_shipping_zone(self, payload, headers):
        return self._request("POST", "/shipping-zones", payload, headers)

    def create_assembly_station(self, payload, headers):
        return self._request("POST", "/assembly-stations", payload, headers)

    # ─── CorporateAccount ─────────────────────────────────────────────────
    def create_account(self, payload, headers):
        return self._request("POST", "/corporate-accounts", payload, headers)

    def get_account(self, account_id, headers):
        return self._request("GET", f"/corporate-accounts/{account_id}", headers=headers)

    def update_account_budget(self, account_id, payload, headers):
        return self._request("PATCH", f"/corporate-accounts/{account_id}/budget",
                             payload, headers)

    # ─── BrandingProfile ──────────────────────────────────────────────────
    def create_branding_profile(self, account_id, payload, headers):
        return self._request("POST", f"/corporate-accounts/{account_id}/branding-profiles",
                             payload, headers)

    def list_branding_profiles(self, account_id, headers, params=None):
        return self._request("GET", f"/corporate-accounts/{account_id}/branding-profiles",
                             headers=headers, params=params)

    def approve_branding_profile(self, profile_id, headers):
        return self._request("POST", f"/branding-profiles/{profile_id}/approve", {}, headers)

    # ─── CorporateOrder ───────────────────────────────────────────────────
    def create_order(self, account_id, payload, headers):
        return self._request("POST", f"/corporate-accounts/{account_id}/orders",
                             payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def import_recipients(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/recipients/import",
                             payload, headers)

    def list_recipients(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/recipients",
                             headers=headers, params=params)

    def submit_for_approval(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/submit-for-approval",
                             payload, headers)

    def budget_decision(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/budget-decision",
                             payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def list_budget_approvals(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/budget-approvals",
                             headers=headers, params=params)

    # ─── Recipient / MessageProof ─────────────────────────────────────────
    def get_recipient(self, recipient_id, headers):
        return self._request("GET", f"/recipients/{recipient_id}", headers=headers)

    def submit_message_proof(self, recipient_id, payload, headers):
        return self._request("POST", f"/recipients/{recipient_id}/message-proof",
                             payload, headers)

    def get_message_proof(self, recipient_id, headers):
        return self._request("GET", f"/recipients/{recipient_id}/message-proof",
                             headers=headers)

    def decide_message_proof(self, proof_id, payload, headers):
        return self._request("POST", f"/message-proofs/{proof_id}/decision",
                             payload, headers)

    # ─── Inventory & Assembly ─────────────────────────────────────────────
    def list_inventory_reservations(self, headers, params=None):
        return self._request("GET", "/inventory-reservations",
                             headers=headers, params=params)

    def get_inventory_reservation(self, reservation_id, headers):
        return self._request("GET", f"/inventory-reservations/{reservation_id}",
                             headers=headers)

    def list_assembly_tasks(self, headers, params=None):
        return self._request("GET", "/assembly-tasks",
                             headers=headers, params=params)

    def get_assembly_task(self, task_id, headers):
        return self._request("GET", f"/assembly-tasks/{task_id}", headers=headers)

    def advance_assembly_task(self, task_id, payload, headers):
        return self._request("POST", f"/assembly-tasks/{task_id}/advance",
                             payload, headers)

    # ─── Shipment ─────────────────────────────────────────────────────────
    def list_shipments(self, headers, params=None):
        return self._request("GET", "/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/shipments/{shipment_id}", headers=headers)

    def create_shipment(self, recipient_id, payload, headers):
        return self._request("POST", f"/recipients/{recipient_id}/shipments",
                             payload, headers)

    def advance_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"/shipments/{shipment_id}/advance",
                             payload, headers)

    # ─── RecurringOrderSeries ─────────────────────────────────────────────
    def create_recurring_series(self, account_id, payload, headers):
        return self._request("POST", f"/corporate-accounts/{account_id}/recurring-series",
                             payload, headers)

    def list_recurring_series(self, headers, params=None):
        return self._request("GET", "/recurring-series",
                             headers=headers, params=params)

    def get_recurring_series(self, series_id, headers):
        return self._request("GET", f"/recurring-series/{series_id}", headers=headers)

    def update_recurring_series(self, series_id, payload, headers):
        return self._request("PATCH", f"/recurring-series/{series_id}",
                             payload, headers)


api_client = ApiClient()
