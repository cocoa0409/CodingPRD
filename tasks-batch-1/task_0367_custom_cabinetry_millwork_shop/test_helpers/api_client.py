"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() is inherited.
Nested action paths express the shop -> customer -> project ownership tree;
flat read aliases provide single-resource GET + FK-filtered list reachability.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Shop / config ---
    def create_shop(self, payload, headers):
        return self._request("POST", "/shops", payload, headers)

    def get_shop(self, shop_id, headers):
        return self._request("GET", f"/shops/{shop_id}", headers=headers)

    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # --- Material ---
    def create_material(self, shop_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/materials", payload, headers)

    def get_material(self, shop_id, material_id, headers):
        return self._request("GET", f"/shops/{shop_id}/materials/{material_id}", headers=headers)

    def list_materials(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/materials", headers=headers, params=params)

    def restock_material(self, shop_id, material_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/materials/{material_id}/restock", payload, headers)

    # --- Machine ---
    def create_machine(self, shop_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/machines", payload, headers)

    def get_machine(self, shop_id, machine_id, headers):
        return self._request("GET", f"/shops/{shop_id}/machines/{machine_id}", headers=headers)

    def update_machine(self, shop_id, machine_id, payload, headers):
        return self._request("PATCH", f"/shops/{shop_id}/machines/{machine_id}", payload, headers)

    # --- Customer ---
    def create_customer(self, shop_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/customers", payload, headers)

    def get_customer(self, shop_id, customer_id, headers):
        return self._request("GET", f"/shops/{shop_id}/customers/{customer_id}", headers=headers)

    def update_customer(self, shop_id, customer_id, payload, headers):
        return self._request("PATCH", f"/shops/{shop_id}/customers/{customer_id}", payload, headers)

    def list_customers(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/customers", headers=headers, params=params)

    # --- Project ---
    def create_project(self, shop_id, customer_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/customers/{customer_id}/projects", payload, headers)

    def get_project(self, shop_id, project_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}", headers=headers)

    def list_projects(self, shop_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects", headers=headers, params=params)

    def list_customer_projects(self, shop_id, customer_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/customers/{customer_id}/projects", headers=headers, params=params)

    def get_cut_list(self, shop_id, project_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/cut-list", headers=headers)

    def measure_project(self, shop_id, project_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/measure", {}, headers)

    def quote_project(self, shop_id, project_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/quote", {}, headers)

    def revise_project(self, shop_id, project_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/revise", {}, headers)

    def contract_project(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/contract", payload, headers)

    def mark_ready(self, shop_id, project_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/mark-ready", {}, headers)

    def close_project(self, shop_id, project_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/close", {}, headers)

    def cancel_project(self, shop_id, project_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/cancel", {}, headers)

    # --- CabinetSpec ---
    def create_spec(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/specs", payload, headers)

    def get_spec(self, shop_id, project_id, spec_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/specs/{spec_id}", headers=headers)

    def list_specs(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/specs", headers=headers, params=params)

    def delete_spec(self, shop_id, project_id, spec_id, headers):
        return self._request("DELETE", f"/shops/{shop_id}/projects/{project_id}/specs/{spec_id}", headers=headers)

    def list_specs_by_material(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/specs-by-material", headers=headers, params=params)

    # --- FinishSelection ---
    def create_finish_selection(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/finish-selections", payload, headers)

    def list_finish_selections(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/finish-selections", headers=headers, params=params)

    def get_finish_selection(self, shop_id, project_id, finish_selection_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/finish-selections/{finish_selection_id}", headers=headers)

    # --- MaterialReservation ---
    def create_reservation(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/material-reservations", payload, headers)

    def get_reservation(self, shop_id, project_id, reservation_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/material-reservations/{reservation_id}", headers=headers)

    def list_reservations(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/material-reservations", headers=headers, params=params)

    def commit_reservation(self, shop_id, project_id, reservation_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/material-reservations/{reservation_id}/commit", {}, headers)

    def release_reservation(self, shop_id, project_id, reservation_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/material-reservations/{reservation_id}/release", {}, headers)

    # --- BuildJob ---
    def create_build_job(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/build-jobs", payload, headers)

    def get_build_job(self, shop_id, project_id, build_job_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/build-jobs/{build_job_id}", headers=headers)

    def list_build_jobs(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/build-jobs", headers=headers, params=params)

    def start_build_job(self, shop_id, project_id, build_job_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/build-jobs/{build_job_id}/start", {}, headers)

    def complete_build_job(self, shop_id, project_id, build_job_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/build-jobs/{build_job_id}/complete", {}, headers)

    def cancel_build_job(self, shop_id, project_id, build_job_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/build-jobs/{build_job_id}/cancel", {}, headers)

    # --- ChangeOrder ---
    def create_change_order(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/change-orders", payload, headers)

    def get_change_order(self, shop_id, project_id, change_order_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/change-orders", headers=headers, params=params)

    def submit_change_order(self, shop_id, project_id, change_order_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/change-orders/{change_order_id}/submit", payload, headers)

    def request_revision_change_order(self, shop_id, project_id, change_order_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/change-orders/{change_order_id}/request-revision", {}, headers)

    def resubmit_change_order(self, shop_id, project_id, change_order_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/change-orders/{change_order_id}/resubmit", {}, headers)

    def approve_change_order(self, shop_id, project_id, change_order_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/change-orders/{change_order_id}/approve", payload, headers)

    def reject_change_order(self, shop_id, project_id, change_order_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/change-orders/{change_order_id}/reject", {}, headers)

    def cancel_change_order(self, shop_id, project_id, change_order_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/change-orders/{change_order_id}/cancel", {}, headers)

    # --- Draw ---
    def create_draw(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/draws", payload, headers)

    def get_draw(self, shop_id, project_id, draw_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/draws/{draw_id}", headers=headers)

    def list_draws(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/draws", headers=headers, params=params)

    def issue_draw(self, shop_id, project_id, draw_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/draws/{draw_id}/issue", {}, headers)

    def pay_draw(self, shop_id, project_id, draw_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/draws/{draw_id}/pay", {}, headers)

    def void_draw(self, shop_id, project_id, draw_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/draws/{draw_id}/void", {}, headers)

    # --- Installation ---
    def create_installation(self, shop_id, project_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations", payload, headers)

    def get_installation(self, shop_id, project_id, installation_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}", headers=headers)

    def list_installations(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/installations", headers=headers, params=params)

    def start_installation(self, shop_id, project_id, installation_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/start", {}, headers)

    def walkthrough_installation(self, shop_id, project_id, installation_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/walkthrough", {}, headers)

    def reopen_installation(self, shop_id, project_id, installation_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/reopen", {}, headers)

    def complete_installation(self, shop_id, project_id, installation_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/complete", {}, headers)

    def cancel_installation(self, shop_id, project_id, installation_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/cancel", {}, headers)

    # --- PunchItem ---
    def create_punch_item(self, shop_id, project_id, installation_id, payload, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/punch-items", payload, headers)

    def get_punch_item(self, shop_id, project_id, installation_id, punch_item_id, headers):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/punch-items/{punch_item_id}", headers=headers)

    def list_punch_items(self, shop_id, project_id, installation_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/punch-items", headers=headers, params=params)

    def list_project_punch_items(self, shop_id, project_id, headers, params=None):
        return self._request("GET", f"/shops/{shop_id}/projects/{project_id}/punch-items", headers=headers, params=params)

    def resolve_punch_item(self, shop_id, project_id, installation_id, punch_item_id, headers):
        return self._request("POST", f"/shops/{shop_id}/projects/{project_id}/installations/{installation_id}/punch-items/{punch_item_id}/resolve", {}, headers)

    # --- Flat read aliases (single-resource GET + FK-filtered list) ---
    def flat_get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    def flat_list_customers(self, headers, params=None):
        return self._request("GET", "/customers", headers=headers, params=params)

    def flat_get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def flat_list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def flat_get_spec(self, spec_id, headers):
        return self._request("GET", f"/specs/{spec_id}", headers=headers)

    def flat_list_specs(self, headers, params=None):
        return self._request("GET", "/specs", headers=headers, params=params)

    def flat_get_material(self, material_id, headers):
        return self._request("GET", f"/materials/{material_id}", headers=headers)

    def flat_list_materials(self, headers, params=None):
        return self._request("GET", "/materials", headers=headers, params=params)

    def flat_get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/material-reservations/{reservation_id}", headers=headers)

    def flat_list_reservations(self, headers, params=None):
        return self._request("GET", "/material-reservations", headers=headers, params=params)

    def flat_get_machine(self, machine_id, headers):
        return self._request("GET", f"/machines/{machine_id}", headers=headers)

    def flat_list_machines(self, headers, params=None):
        return self._request("GET", "/machines", headers=headers, params=params)

    def flat_get_build_job(self, build_job_id, headers):
        return self._request("GET", f"/build-jobs/{build_job_id}", headers=headers)

    def flat_list_build_jobs(self, headers, params=None):
        return self._request("GET", "/build-jobs", headers=headers, params=params)

    def flat_get_finish_selection(self, finish_selection_id, headers):
        return self._request("GET", f"/finish-selections/{finish_selection_id}", headers=headers)

    def flat_list_finish_selections(self, headers, params=None):
        return self._request("GET", "/finish-selections", headers=headers, params=params)

    def flat_get_draw(self, draw_id, headers):
        return self._request("GET", f"/draws/{draw_id}", headers=headers)

    def flat_list_draws(self, headers, params=None):
        return self._request("GET", "/draws", headers=headers, params=params)

    def flat_get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def flat_list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def flat_get_installation(self, installation_id, headers):
        return self._request("GET", f"/installations/{installation_id}", headers=headers)

    def flat_list_installations(self, headers, params=None):
        return self._request("GET", "/installations", headers=headers, params=params)

    def flat_get_punch_item(self, punch_item_id, headers):
        return self._request("GET", f"/punch-items/{punch_item_id}", headers=headers)

    def flat_list_punch_items(self, headers, params=None):
        return self._request("GET", "/punch-items", headers=headers, params=params)


api_client = ApiClient()
