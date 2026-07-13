"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Client ---
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # --- Organizer ---
    def create_organizer(self, payload, headers):
        return self._request("POST", "/organizers", payload, headers)

    def get_organizer(self, organizer_id, headers):
        return self._request("GET", f"/organizers/{organizer_id}", headers=headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def activate_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/activate", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers)

    # --- Session ---
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def complete_session(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/complete", payload, headers)

    def patch_session(self, session_id, payload, headers):
        return self._request("PATCH", f"/sessions/{session_id}", payload, headers)

    # --- InventoryItem ---
    def create_inventory_item(self, payload, headers):
        return self._request("POST", "/inventory-items", payload, headers)

    def list_inventory_items(self, headers, params=None):
        return self._request("GET", "/inventory-items", headers=headers, params=params)

    def get_inventory_item(self, item_id, headers):
        return self._request("GET", f"/inventory-items/{item_id}", headers=headers)

    def schedule_inventory_item(self, item_id, headers):
        return self._request("POST", f"/inventory-items/{item_id}/schedule", {}, headers)

    def confirm_inventory_item(self, item_id, payload, headers):
        return self._request("POST", f"/inventory-items/{item_id}/confirm", payload, headers)

    # --- ProductLine ---
    def create_product_line(self, payload, headers):
        return self._request("POST", "/product-lines", payload, headers)

    def list_product_lines(self, headers, params=None):
        return self._request("GET", "/product-lines", headers=headers, params=params)

    def get_product_line(self, product_id, headers):
        return self._request("GET", f"/product-lines/{product_id}", headers=headers)

    def patch_product_line(self, product_id, payload, headers):
        return self._request("PATCH", f"/product-lines/{product_id}", payload, headers)

    # --- Invoice ---
    def create_invoice(self, payload, headers):
        return self._request("POST", "/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/invoices/{invoice_id}", headers=headers)

    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/invoices/{invoice_id}/pay", {}, headers)

    def patch_invoice(self, invoice_id, payload, headers):
        return self._request("PATCH", f"/invoices/{invoice_id}", payload, headers)

    # --- MaintenancePlan ---
    def create_maintenance_plan(self, payload, headers):
        return self._request("POST", "/maintenance-plans", payload, headers)

    def list_maintenance_plans(self, headers, params=None):
        return self._request("GET", "/maintenance-plans", headers=headers, params=params)

    def get_maintenance_plan(self, plan_id, headers):
        return self._request("GET", f"/maintenance-plans/{plan_id}", headers=headers)

    def patch_maintenance_plan(self, plan_id, payload, headers):
        return self._request("PATCH", f"/maintenance-plans/{plan_id}", payload, headers)


api_client = ApiClient()
