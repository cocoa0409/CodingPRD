"""API client: one method per endpoint defined in the PRD (section 4)."""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/retail-reset"


class ApiClient(GenericApiClient):
    # --- Clients ---
    def create_client(self, payload, headers):
        return self._request("POST", f"{PREFIX}/clients", payload, headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients", headers=headers, params=params)

    def get_client(self, client_id, headers):
        return self._request("GET", f"{PREFIX}/clients/{client_id}", headers=headers)

    # --- Stores ---
    def create_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/stores", payload, headers)

    def list_stores(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/stores", headers=headers, params=params)

    def get_store(self, store_id, headers):
        return self._request("GET", f"{PREFIX}/stores/{store_id}", headers=headers)

    # --- Field reps ---
    def create_rep(self, payload, headers):
        return self._request("POST", f"{PREFIX}/reps", payload, headers)

    def list_reps(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/reps", headers=headers, params=params)

    def get_rep(self, rep_id, headers):
        return self._request("GET", f"{PREFIX}/reps/{rep_id}", headers=headers)

    # --- Projects ---
    def create_project(self, payload, headers):
        return self._request("POST", f"{PREFIX}/projects", payload, headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"{PREFIX}/projects/{project_id}", headers=headers)

    def scope_project(self, project_id, payload, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/scope", payload, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"{PREFIX}/projects/{project_id}/cancel", {}, headers)

    # --- Project store list ---
    def create_project_store(self, payload, headers):
        return self._request("POST", f"{PREFIX}/project-stores", payload, headers)

    def list_project_stores(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/project-stores", headers=headers, params=params)

    def get_project_store(self, project_store_id, headers):
        return self._request("GET", f"{PREFIX}/project-stores/{project_store_id}", headers=headers)

    def drop_project_store(self, project_store_id, headers):
        return self._request("POST", f"{PREFIX}/project-stores/{project_store_id}/drop", {}, headers)

    def list_project_store_rows_of_project(self, project_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/projects/{project_id}/project-stores",
                             headers=headers, params=params)

    # --- Assignments ---
    def create_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}", headers=headers)

    def depart_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/depart", {}, headers)

    def check_in_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/check-in", {}, headers)

    def check_out_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/check-out", {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"{PREFIX}/assignments/{assignment_id}/cancel", {}, headers)

    # --- Store visits ---
    def list_store_visits(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/store-visits", headers=headers, params=params)

    def get_store_visit(self, visit_id, headers):
        return self._request("GET", f"{PREFIX}/store-visits/{visit_id}", headers=headers)

    def list_assignment_store_visits(self, assignment_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/assignments/{assignment_id}/store-visits",
                             headers=headers, params=params)

    def verify_store_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/store-visits/{visit_id}/verify", {}, headers)

    def reject_store_visit(self, visit_id, headers):
        return self._request("POST", f"{PREFIX}/store-visits/{visit_id}/reject", {}, headers)

    # --- Photo evidence ---
    def upload_photo(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/store-visits/{visit_id}/photos", payload, headers)

    def list_photos(self, visit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/store-visits/{visit_id}/photos",
                             headers=headers, params=params)

    # --- Exception reports ---
    def create_exception(self, visit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/store-visits/{visit_id}/exceptions",
                             payload, headers)

    def list_exceptions(self, visit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/store-visits/{visit_id}/exceptions",
                             headers=headers, params=params)

    def resolve_exception(self, exception_id, payload, headers):
        return self._request("POST", f"{PREFIX}/exceptions/{exception_id}/resolve",
                             payload, headers)

    def get_exception(self, exception_id, headers):
        return self._request("GET", f"{PREFIX}/exceptions/{exception_id}", headers=headers)

    # --- Rework authorizations ---
    def create_rework_authorization(self, payload, headers):
        return self._request("POST", f"{PREFIX}/rework-authorizations", payload, headers)

    def list_rework_authorizations(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/rework-authorizations",
                             headers=headers, params=params)

    def get_rework_authorization(self, auth_id, headers):
        return self._request("GET", f"{PREFIX}/rework-authorizations/{auth_id}", headers=headers)

    def approve_rework_authorization(self, auth_id, headers):
        return self._request("POST", f"{PREFIX}/rework-authorizations/{auth_id}/approve",
                             {}, headers)

    def deny_rework_authorization(self, auth_id, headers):
        return self._request("POST", f"{PREFIX}/rework-authorizations/{auth_id}/deny",
                             {}, headers)

    # --- Fixture shipments ---
    def create_fixture_shipment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/fixture-shipments", payload, headers)

    def list_fixture_shipments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/fixture-shipments", headers=headers, params=params)

    def get_fixture_shipment(self, shipment_id, headers):
        return self._request("GET", f"{PREFIX}/fixture-shipments/{shipment_id}", headers=headers)

    def scan_fixture_shipment(self, shipment_id, payload, headers):
        return self._request("POST", f"{PREFIX}/fixture-shipments/{shipment_id}/scan",
                             payload, headers)

    # --- Mileage logs ---
    def create_mileage_log(self, payload, headers):
        return self._request("POST", f"{PREFIX}/mileage-logs", payload, headers)

    def list_mileage_logs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/mileage-logs", headers=headers, params=params)

    def get_mileage_log(self, log_id, headers):
        return self._request("GET", f"{PREFIX}/mileage-logs/{log_id}", headers=headers)

    def list_rep_mileage_logs(self, rep_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/reps/{rep_id}/mileage-logs",
                             headers=headers, params=params)

    def approve_mileage_log(self, log_id, headers):
        return self._request("POST", f"{PREFIX}/mileage-logs/{log_id}/approve", {}, headers)

    def reject_mileage_log(self, log_id, headers):
        return self._request("POST", f"{PREFIX}/mileage-logs/{log_id}/reject", {}, headers)

    def pay_mileage_log(self, log_id, headers):
        return self._request("POST", f"{PREFIX}/mileage-logs/{log_id}/pay", {}, headers)

    # --- Invoices ---
    def create_invoice(self, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices", payload, headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/invoices", headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    def list_client_invoices(self, client_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/clients/{client_id}/invoices",
                             headers=headers, params=params)

    def finalize_invoice(self, invoice_id, payload, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/finalize",
                             payload, headers)

    def void_invoice(self, invoice_id, headers):
        return self._request("POST", f"{PREFIX}/invoices/{invoice_id}/void", {}, headers)

    # --- Logical clock (test-driving) ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
