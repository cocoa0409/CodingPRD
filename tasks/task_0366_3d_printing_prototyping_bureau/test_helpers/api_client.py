"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Bureau ───────────────────────────────────────
    def create_bureau(self, payload, headers):
        return self._request("POST", "/bureaus", payload, headers)

    def get_bureau(self, bureau_id, headers):
        return self._request("GET", f"/bureaus/{bureau_id}", headers=headers)

    def set_clock(self, bureau_id, payload, headers):
        return self._request("POST", f"/bureaus/{bureau_id}/clock", payload, headers)

    # ─── Customer ─────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/bureaus/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/bureaus/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/bureaus/customers", headers=headers, params=params)

    def deposit(self, customer_id, payload, headers):
        return self._request("POST", f"/bureaus/customers/{customer_id}/deposit", payload, headers)

    # ─── Material ─────────────────────────────────────
    def create_material(self, payload, headers):
        return self._request("POST", "/bureaus/materials", payload, headers)

    def get_material(self, material_id, headers):
        return self._request("GET", f"/bureaus/materials/{material_id}", headers=headers)

    def list_materials(self, headers, params=None):
        return self._request("GET", "/bureaus/materials", headers=headers, params=params)

    def retire_material(self, material_id, headers):
        return self._request("POST", f"/bureaus/materials/{material_id}/retire", None, headers)

    # ─── Machine ──────────────────────────────────────
    def create_machine(self, payload, headers):
        return self._request("POST", "/bureaus/machines", payload, headers)

    def get_machine(self, machine_id, headers):
        return self._request("GET", f"/bureaus/machines/{machine_id}", headers=headers)

    def list_machines(self, headers, params=None):
        return self._request("GET", "/bureaus/machines", headers=headers, params=params)

    def set_maintenance(self, machine_id, payload, headers):
        return self._request("POST", f"/bureaus/machines/{machine_id}/maintenance", payload, headers)

    # ─── Spool ────────────────────────────────────────
    def create_spool(self, payload, headers):
        return self._request("POST", "/bureaus/spools", payload, headers)

    def get_spool(self, spool_id, headers):
        return self._request("GET", f"/bureaus/spools/{spool_id}", headers=headers)

    def list_spools(self, headers, params=None):
        return self._request("GET", "/bureaus/spools", headers=headers, params=params)

    # ─── PrintFile ────────────────────────────────────
    def create_print_file(self, payload, headers):
        return self._request("POST", "/bureaus/print-files", payload, headers)

    def get_print_file(self, file_id, headers):
        return self._request("GET", f"/bureaus/print-files/{file_id}", headers=headers)

    def list_print_files(self, headers, params=None):
        return self._request("GET", "/bureaus/print-files", headers=headers, params=params)

    def check_print_file(self, file_id, payload, headers):
        return self._request("POST", f"/bureaus/print-files/{file_id}/check", payload, headers)

    def override_print_file(self, file_id, headers):
        return self._request("POST", f"/bureaus/print-files/{file_id}/override", None, headers)

    # ─── Order ────────────────────────────────────────
    def create_order(self, payload, headers):
        return self._request("POST", "/bureaus/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/bureaus/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/bureaus/orders", headers=headers, params=params)

    def quote_order(self, order_id, headers):
        return self._request("POST", f"/bureaus/orders/{order_id}/quote", {}, headers)

    def confirm_order(self, order_id, payload, headers):
        return self._request("POST", f"/bureaus/orders/{order_id}/confirm", payload, headers)

    def ship_order(self, order_id, payload, headers):
        return self._request("POST", f"/bureaus/orders/{order_id}/ship", payload, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/bureaus/orders/{order_id}/cancel", {}, headers)

    # ─── OrderLine ────────────────────────────────────
    def create_order_line(self, payload, headers):
        return self._request("POST", "/bureaus/order-lines", payload, headers)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/bureaus/order-lines/{line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/bureaus/order-lines", headers=headers, params=params)

    # ─── FinishingTask ────────────────────────────────
    def create_finishing_task(self, payload, headers):
        return self._request("POST", "/bureaus/finishing-tasks", payload, headers)

    def get_finishing_task(self, task_id, headers):
        return self._request("GET", f"/bureaus/finishing-tasks/{task_id}", headers=headers)

    def list_finishing_tasks(self, headers, params=None):
        return self._request("GET", "/bureaus/finishing-tasks", headers=headers, params=params)

    def schedule_finishing_task(self, task_id, headers):
        return self._request("POST", f"/bureaus/finishing-tasks/{task_id}/schedule", {}, headers)

    def complete_finishing_task(self, task_id, headers):
        return self._request("POST", f"/bureaus/finishing-tasks/{task_id}/complete", {}, headers)

    def skip_finishing_task(self, task_id, headers):
        return self._request("POST", f"/bureaus/finishing-tasks/{task_id}/skip", {}, headers)

    # ─── PrintRun ─────────────────────────────────────
    def create_print_run(self, payload, headers):
        return self._request("POST", "/bureaus/print-runs", payload, headers)

    def get_print_run(self, run_id, headers):
        return self._request("GET", f"/bureaus/print-runs/{run_id}", headers=headers)

    def list_print_runs(self, headers, params=None):
        return self._request("GET", "/bureaus/print-runs", headers=headers, params=params)

    def start_print_run(self, run_id, headers):
        return self._request("POST", f"/bureaus/print-runs/{run_id}/start", {}, headers)

    def complete_print_run(self, run_id, headers):
        return self._request("POST", f"/bureaus/print-runs/{run_id}/complete", {}, headers)

    def fail_print_run(self, run_id, payload, headers):
        return self._request("POST", f"/bureaus/print-runs/{run_id}/fail", payload, headers)

    def adjudicate_print_run(self, run_id, payload, headers):
        return self._request("POST", f"/bureaus/print-runs/{run_id}/adjudicate", payload, headers)

    def cancel_print_run(self, run_id, headers):
        return self._request("POST", f"/bureaus/print-runs/{run_id}/cancel", {}, headers)

    # ─── Shipment ─────────────────────────────────────
    def create_shipment(self, payload, headers):
        return self._request("POST", "/bureaus/shipments", payload, headers)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/bureaus/shipments/{shipment_id}", headers=headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/bureaus/shipments", headers=headers, params=params)


api_client = ApiClient()
