"""API client: one method per endpoint declared by the PRD.

All paths are rooted at the /fulfillment-network prefix.
"""

from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/fulfillment-network"


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------- stores

    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    def patch_store(self, store_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/stores/{store_id}", payload, headers)

    def reactivate_store(self, store_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/reactivate", payload or {}, headers
        )

    # --------------------------------------------------------------- skus

    def create_sku(self, payload, headers):
        return self._request("POST", f"{PREFIX}/skus", payload, headers)

    def list_skus(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/skus", headers=headers, params=params)

    def get_sku(self, sku_id, headers):
        return self._request("GET", f"{PREFIX}/skus/{sku_id}", headers=headers)

    # ---------------------------------------------------------- inventory

    def create_store_inventory(self, payload, headers):
        return self._request("POST", f"{PREFIX}/store-inventories", payload, headers)

    def list_store_inventories(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/store-inventories", headers=headers, params=params
        )

    def get_store_inventory(self, inventory_id, headers):
        return self._request(
            "GET", f"{PREFIX}/store-inventories/{inventory_id}", headers=headers
        )

    def adjust_store_inventory(self, inventory_id, payload, headers):
        return self._request(
            "POST",
            f"{PREFIX}/store-inventories/{inventory_id}/adjustments",
            payload,
            headers,
        )

    # ---------------------------------------------------------- packaging

    def create_packaging_supply(self, payload, headers):
        return self._request("POST", f"{PREFIX}/packaging-supplies", payload, headers)

    def list_packaging_supplies(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/packaging-supplies", headers=headers, params=params
        )

    def get_packaging_supply(self, supply_id, headers):
        return self._request(
            "GET", f"{PREFIX}/packaging-supplies/{supply_id}", headers=headers
        )

    def restock_packaging_supply(self, supply_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/packaging-supplies/{supply_id}/restock", payload, headers
        )

    # ----------------------------------------------------- carrier pickups

    def create_carrier_pickup(self, store_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/stores/{store_id}/carrier-pickups", payload, headers
        )

    def list_carrier_pickups(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/carrier-pickups", headers=headers, params=params
        )

    def get_carrier_pickup(self, pickup_id, headers):
        return self._request(
            "GET", f"{PREFIX}/carrier-pickups/{pickup_id}", headers=headers
        )

    def close_carrier_pickup(self, pickup_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/carrier-pickups/{pickup_id}/close", payload or {}, headers
        )

    def depart_carrier_pickup(self, pickup_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/carrier-pickups/{pickup_id}/depart",
            payload or {},
            headers,
        )

    def cancel_carrier_pickup(self, pickup_id, headers, payload=None):
        return self._request(
            "POST",
            f"{PREFIX}/carrier-pickups/{pickup_id}/cancel",
            payload or {},
            headers,
        )

    # ------------------------------------------------------------- orders

    def create_order(self, payload, headers):
        return self._request("POST", f"{PREFIX}/orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"{PREFIX}/orders/{order_id}", headers=headers)

    def create_order_line(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/lines", payload, headers
        )

    def list_order_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/order-lines", headers=headers, params=params
        )

    def get_order_line(self, order_line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/order-lines/{order_line_id}", headers=headers
        )

    def cancel_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/cancel", payload, headers
        )

    def get_cost_comparison(self, order_id, headers):
        return self._request(
            "GET", f"{PREFIX}/orders/{order_id}/cost-comparison", headers=headers
        )

    # ------------------------------------------------------------ routing

    def create_routing_run(self, order_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/orders/{order_id}/routing-runs", payload, headers
        )

    def list_routing_runs(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/routing-runs", headers=headers, params=params
        )

    def get_routing_run(self, routing_run_id, headers):
        return self._request(
            "GET", f"{PREFIX}/routing-runs/{routing_run_id}", headers=headers
        )

    def list_routing_candidates(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/routing-candidates", headers=headers, params=params
        )

    def get_routing_candidate(self, candidate_id, headers):
        return self._request(
            "GET", f"{PREFIX}/routing-candidates/{candidate_id}", headers=headers
        )

    # -------------------------------------------------------- assignments

    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignments", headers=headers, params=params
        )

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers
        )

    def accept_assignment(self, assignment_id, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/accept", payload or {}, headers
        )

    def reject_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/reject", payload, headers
        )

    def pick_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/pick", payload, headers
        )

    def pack_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/pack", payload, headers
        )

    def ship_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/ship", payload, headers
        )

    def cancel_assignment(self, assignment_id, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/assignments/{assignment_id}/cancel", payload, headers
        )

    def list_assignment_lines(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/assignment-lines", headers=headers, params=params
        )

    def get_assignment_line(self, assignment_line_id, headers):
        return self._request(
            "GET", f"{PREFIX}/assignment-lines/{assignment_line_id}", headers=headers
        )

    # --------------------------------------------------- node performance

    def close_performance_windows(self, headers, payload=None):
        return self._request(
            "POST", f"{PREFIX}/performance-windows/close", payload or {}, headers
        )

    def list_performance_windows(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/performance-windows", headers=headers, params=params
        )

    def get_performance_window(self, window_id, headers):
        return self._request(
            "GET", f"{PREFIX}/performance-windows/{window_id}", headers=headers
        )

    # ------------------------------------------------------ notifications

    def list_notifications(self, headers, params=None):
        return self._request(
            "GET", f"{PREFIX}/notifications", headers=headers, params=params
        )

    def get_notification(self, notification_id, headers):
        return self._request(
            "GET", f"{PREFIX}/notifications/{notification_id}", headers=headers
        )

    # -------------------------------------------------------------- clock

    def set_clock(self, payload, headers):
        return self._request(
            "POST", f"{PREFIX}/_clock/set_current_utc", payload, headers
        )


api_client = ApiClient()
