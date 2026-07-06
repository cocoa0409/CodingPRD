"""API client: one method per endpoint defined in the PRD (all under /v1)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set_current_utc", payload, headers)

    # ─── Members ──────────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/v1/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    def list_wallet_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/v1/members/{member_id}/wallet-ledger",
                             headers=headers, params=params)

    # ─── Products ─────────────────────────────────────────────────────────
    def create_product(self, payload, headers):
        return self._request("POST", "/v1/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/v1/products/{product_id}", headers=headers)

    # ─── Stations ─────────────────────────────────────────────────────────
    def create_station(self, payload, headers):
        return self._request("POST", "/v1/stations", payload, headers)

    def get_station(self, station_id, headers):
        return self._request("GET", f"/v1/stations/{station_id}", headers=headers)

    # ─── Bulk bins ────────────────────────────────────────────────────────
    def create_bin(self, payload, headers):
        return self._request("POST", "/v1/bins", payload, headers)

    def get_bin(self, bin_id, headers):
        return self._request("GET", f"/v1/bins/{bin_id}", headers=headers)

    def list_bins(self, headers, params=None):
        return self._request("GET", "/v1/bins", headers=headers, params=params)

    def recount_bin(self, bin_id, payload, headers):
        return self._request("POST", f"/v1/bins/{bin_id}/recount", payload, headers)

    # ─── Containers ───────────────────────────────────────────────────────
    def create_container(self, payload, headers):
        return self._request("POST", "/v1/containers", payload, headers)

    def get_container(self, container_id, headers):
        return self._request("GET", f"/v1/containers/{container_id}", headers=headers)

    def list_containers(self, headers, params=None):
        return self._request("GET", "/v1/containers", headers=headers, params=params)

    def issue_container(self, container_id, payload, headers):
        return self._request("POST", f"/v1/containers/{container_id}/issue", payload, headers)

    def return_container(self, container_id, headers):
        return self._request("POST", f"/v1/containers/{container_id}/return", {}, headers)

    def inspect_container(self, container_id, payload, headers):
        return self._request("POST", f"/v1/containers/{container_id}/inspect", payload, headers)

    # ─── Orders ───────────────────────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/v1/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/v1/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/v1/orders", headers=headers, params=params)

    def add_line(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/lines", payload, headers)

    def start_fill(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/start-fill", {}, headers)

    def checkout_order(self, order_id, payload, headers):
        return self._request("POST", f"/v1/orders/{order_id}/checkout", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/v1/orders/{order_id}/cancel", {}, headers)

    # ─── Refill lines ─────────────────────────────────────────────────────
    def get_refill_line(self, line_id, headers):
        return self._request("GET", f"/v1/refill-lines/{line_id}", headers=headers)

    def list_refill_lines(self, headers, params=None):
        return self._request("GET", "/v1/refill-lines", headers=headers, params=params)

    def fill_line(self, line_id, payload, headers):
        return self._request("POST", f"/v1/refill-lines/{line_id}/fill", payload, headers)

    def void_line(self, line_id, headers):
        return self._request("POST", f"/v1/refill-lines/{line_id}/void", {}, headers)

    # ─── Restock tasks ────────────────────────────────────────────────────
    def get_restock_task(self, task_id, headers):
        return self._request("GET", f"/v1/restock-tasks/{task_id}", headers=headers)

    def list_restock_tasks(self, headers, params=None):
        return self._request("GET", "/v1/restock-tasks", headers=headers, params=params)

    def complete_restock_task(self, task_id, payload, headers):
        return self._request("POST", f"/v1/restock-tasks/{task_id}/complete", payload, headers)

    # ─── Subscriptions ────────────────────────────────────────────────────
    def create_subscription(self, payload, headers):
        return self._request("POST", "/v1/subscriptions", payload, headers)

    def get_subscription(self, subscription_id, headers):
        return self._request("GET", f"/v1/subscriptions/{subscription_id}", headers=headers)

    def list_subscriptions(self, headers, params=None):
        return self._request("GET", "/v1/subscriptions", headers=headers, params=params)

    def run_subscription(self, subscription_id, payload, headers):
        return self._request("POST", f"/v1/subscriptions/{subscription_id}/run", payload, headers)

    def cancel_subscription(self, subscription_id, headers):
        return self._request("POST", f"/v1/subscriptions/{subscription_id}/cancel", {}, headers)

    # ─── Delivery vehicles ────────────────────────────────────────────────
    def create_delivery_vehicle(self, payload, headers):
        return self._request("POST", "/v1/delivery-vehicles", payload, headers)

    def get_delivery_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/v1/delivery-vehicles/{vehicle_id}", headers=headers)

    # ─── Deliveries ───────────────────────────────────────────────────────
    def create_delivery(self, payload, headers):
        return self._request("POST", "/v1/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/v1/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/v1/deliveries", headers=headers, params=params)

    def dispatch_delivery(self, delivery_id, headers):
        return self._request("POST", f"/v1/deliveries/{delivery_id}/dispatch", {}, headers)

    def deliver_delivery(self, delivery_id, headers):
        return self._request("POST", f"/v1/deliveries/{delivery_id}/deliver", {}, headers)

    def return_received_delivery(self, delivery_id, headers):
        return self._request("POST", f"/v1/deliveries/{delivery_id}/return-received", {}, headers)

    def cancel_delivery(self, delivery_id, headers):
        return self._request("POST", f"/v1/deliveries/{delivery_id}/cancel", {}, headers)


api_client = ApiClient()
