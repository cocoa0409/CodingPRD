"""API client: one method per endpoint defined in the PRD.

Endpoints are mounted at the root of the service; there is no shared path prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock --
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --------------------------------------------------------------- stores --
    def create_store(self, payload, headers):
        return self._request("POST", "/stores", payload, headers)

    def get_store(self, store_id, headers):
        return self._request("GET", f"/stores/{store_id}", headers=headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def patch_store(self, store_id, payload, headers):
        return self._request("PATCH", f"/stores/{store_id}", payload, headers)

    def create_hour_window(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/hour-windows", payload, headers)

    def list_hour_windows(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/hour-windows", headers=headers, params=params)

    def publish_menu(self, store_id, payload, headers):
        return self._request("POST", f"/stores/{store_id}/publish-menu", payload, headers)

    def recompute_throttle(self, store_id, headers, payload=None):
        return self._request("POST", f"/stores/{store_id}/recompute-throttle", payload, headers)

    def get_quote(self, store_id, headers, params=None):
        return self._request("GET", f"/stores/{store_id}/quote", headers=headers, params=params)

    # ------------------------------------------------------------- channels --
    def create_channel(self, payload, headers):
        return self._request("POST", "/channels", payload, headers)

    def get_channel(self, channel_id, headers):
        return self._request("GET", f"/channels/{channel_id}", headers=headers)

    def patch_channel(self, channel_id, payload, headers):
        return self._request("PATCH", f"/channels/{channel_id}", payload, headers)

    # --------------------------------------------------------- menu versions --
    def create_menu_version(self, payload, headers):
        return self._request("POST", "/menu-versions", payload, headers)

    def get_menu_version(self, menu_version_id, headers):
        return self._request("GET", f"/menu-versions/{menu_version_id}", headers=headers)

    def create_menu_item(self, menu_version_id, payload, headers):
        return self._request("POST", f"/menu-versions/{menu_version_id}/items", payload, headers)

    def list_menu_items(self, menu_version_id, headers, params=None):
        return self._request("GET", f"/menu-versions/{menu_version_id}/items", headers=headers, params=params)

    def finalize_menu_version(self, menu_version_id, headers, payload=None):
        return self._request("POST", f"/menu-versions/{menu_version_id}/finalize", payload, headers)

    # ------------------------------------------------------ channel listings --
    def get_channel_listing(self, listing_id, headers):
        return self._request("GET", f"/channel-listings/{listing_id}", headers=headers)

    def list_channel_listings(self, headers, params=None):
        return self._request("GET", "/channel-listings", headers=headers, params=params)

    def patch_channel_listing(self, listing_id, payload, headers):
        return self._request("PATCH", f"/channel-listings/{listing_id}", payload, headers)

    # --------------------------------------------------- availability events --
    def create_availability_event(self, payload, headers):
        return self._request("POST", "/availability-events", payload, headers)

    def get_availability_event(self, event_id, headers):
        return self._request("GET", f"/availability-events/{event_id}", headers=headers)

    def list_availability_events(self, headers, params=None):
        return self._request("GET", "/availability-events", headers=headers, params=params)

    # --------------------------------------------------------------- orders --
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def list_order_lines(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/lines", headers=headers, params=params)

    def inject_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/inject", payload, headers)

    def list_injection_attempts(self, order_id, headers, params=None):
        return self._request("GET", f"/orders/{order_id}/injection-attempts", headers=headers, params=params)

    def resume_injection(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/resume-injection", payload, headers)

    def mark_order_ready(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/ready", payload, headers)

    def cancel_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", payload, headers)

    def dispatch_order(self, order_id, headers, payload=None):
        return self._request("POST", f"/orders/{order_id}/dispatch", payload, headers)

    # ------------------------------------------------------ courier networks --
    def create_courier_network(self, payload, headers):
        return self._request("POST", "/courier-networks", payload, headers)

    def get_courier_network(self, network_id, headers):
        return self._request("GET", f"/courier-networks/{network_id}", headers=headers)

    # --------------------------------------------------- delivery assignments --
    def get_delivery_assignment(self, assignment_id, headers):
        return self._request("GET", f"/delivery-assignments/{assignment_id}", headers=headers)

    def list_delivery_assignments(self, headers, params=None):
        return self._request("GET", "/delivery-assignments", headers=headers, params=params)

    def accept_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/delivery-assignments/{assignment_id}/accept", payload, headers)

    def decline_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/delivery-assignments/{assignment_id}/decline", payload, headers)

    def handoff_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/delivery-assignments/{assignment_id}/handoff", payload, headers)

    def deliver_assignment(self, assignment_id, headers, payload=None):
        return self._request("POST", f"/delivery-assignments/{assignment_id}/deliver", payload, headers)

    # ---------------------------------------------------------- adjustments --
    def create_adjustment(self, payload, headers):
        return self._request("POST", "/adjustments", payload, headers)

    def get_adjustment(self, adjustment_id, headers):
        return self._request("GET", f"/adjustments/{adjustment_id}", headers=headers)

    def list_adjustments(self, headers, params=None):
        return self._request("GET", "/adjustments", headers=headers, params=params)

    def submit_adjustment(self, adjustment_id, headers, payload=None):
        return self._request("POST", f"/adjustments/{adjustment_id}/submit", payload, headers)

    def request_adjustment_revision(self, adjustment_id, headers, payload=None):
        return self._request("POST", f"/adjustments/{adjustment_id}/request-revision", payload, headers)

    def revise_adjustment(self, adjustment_id, headers, payload=None):
        return self._request("POST", f"/adjustments/{adjustment_id}/revise", payload, headers)

    def accept_adjustment(self, adjustment_id, headers, payload=None):
        return self._request("POST", f"/adjustments/{adjustment_id}/accept", payload, headers)

    def reverse_adjustment(self, adjustment_id, payload, headers):
        return self._request("POST", f"/adjustments/{adjustment_id}/reverse", payload, headers)

    # -------------------------------------------------- remittance statements --
    def create_statement(self, payload, headers):
        return self._request("POST", "/remittance-statements", payload, headers)

    def get_statement(self, statement_id, headers):
        return self._request("GET", f"/remittance-statements/{statement_id}", headers=headers)

    def list_statements(self, headers, params=None):
        return self._request("GET", "/remittance-statements", headers=headers, params=params)

    def assign_orders(self, statement_id, payload, headers):
        return self._request("POST", f"/remittance-statements/{statement_id}/assign-orders", payload, headers)

    def preview_statement(self, statement_id, headers, params=None):
        return self._request("GET", f"/remittance-statements/{statement_id}/preview", headers=headers, params=params)

    def reconcile_statement(self, statement_id, headers, payload=None):
        return self._request("POST", f"/remittance-statements/{statement_id}/reconcile", payload, headers)

    def dispute_statement(self, statement_id, payload, headers):
        return self._request("POST", f"/remittance-statements/{statement_id}/dispute", payload, headers)

    def settle_statement(self, statement_id, headers, payload=None):
        return self._request("POST", f"/remittance-statements/{statement_id}/settle", payload, headers)


api_client = ApiClient()
