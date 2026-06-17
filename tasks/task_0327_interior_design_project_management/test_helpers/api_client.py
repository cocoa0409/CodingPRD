"""API client: one method per endpoint defined in the PRD (Interior Design PM API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Client -----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    # ----- Project -----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def advance_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/advance", payload, headers)

    def hold_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/hold", {}, headers)

    def resume_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/resume", {}, headers)

    def close_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/close", {}, headers)

    def fee_quote(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}/fee-quote", headers=headers)

    # ----- Payments -----
    def create_payment(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    # ----- Room -----
    def create_room(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/rooms", headers=headers, params=params)

    def present_moodboard_room(self, room_id, headers):
        return self._request("POST", f"/rooms/{room_id}/present-moodboard", {}, headers)

    def approve_room(self, room_id, headers):
        return self._request("POST", f"/rooms/{room_id}/approve", {}, headers)

    def request_rework_room(self, room_id, headers):
        return self._request("POST", f"/rooms/{room_id}/request-rework", {}, headers)

    def reopen_scope_room(self, room_id, headers):
        return self._request("POST", f"/rooms/{room_id}/reopen-scope", {}, headers)

    # ----- MoodBoard -----
    def create_moodboard(self, room_id, payload, headers):
        return self._request("POST", f"/rooms/{room_id}/moodboards", payload, headers)

    def get_moodboard(self, moodboard_id, headers):
        return self._request("GET", f"/moodboards/{moodboard_id}", headers=headers)

    def list_moodboards(self, headers, params=None):
        return self._request("GET", "/moodboards", headers=headers, params=params)

    def present_moodboard(self, moodboard_id, headers):
        return self._request("POST", f"/moodboards/{moodboard_id}/present", {}, headers)

    # ----- FFEItem (catalog) -----
    def create_ffe_item(self, payload, headers):
        return self._request("POST", "/ffe-items", payload, headers)

    def get_ffe_item(self, ffe_item_id, headers):
        return self._request("GET", f"/ffe-items/{ffe_item_id}", headers=headers)

    # ----- DesignSelection -----
    def create_selection(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/selections", payload, headers)

    def get_selection(self, selection_id, headers):
        return self._request("GET", f"/selections/{selection_id}", headers=headers)

    def list_selections(self, headers, params=None):
        return self._request("GET", "/selections", headers=headers, params=params)

    def specify_selection(self, selection_id, headers):
        return self._request("POST", f"/selections/{selection_id}/specify", {}, headers)

    def withdraw_selection(self, selection_id, headers):
        return self._request("POST", f"/selections/{selection_id}/withdraw", {}, headers)

    # ----- Vendor -----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    # ----- ProcurementOrder -----
    def create_order(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def add_order_line(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/lines", payload, headers)

    def get_order_line(self, order_line_id, headers):
        return self._request("GET", f"/order-lines/{order_line_id}", headers=headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/order-lines", headers=headers, params=params)

    def place_order(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/place", payload, headers)

    def ship_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/ship", {}, headers)

    def deliver_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/deliver", {}, headers)

    def close_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/close-order", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/cancel", {}, headers)

    def return_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/return-order", {}, headers)

    # ----- RevisionRequest -----
    def create_revision(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/revisions", payload, headers)

    def get_revision(self, revision_id, headers):
        return self._request("GET", f"/revisions/{revision_id}", headers=headers)

    def list_revisions(self, headers, params=None):
        return self._request("GET", "/revisions", headers=headers, params=params)

    def submit_revision(self, revision_id, headers):
        return self._request("POST", f"/revisions/{revision_id}/submit", {}, headers)

    def request_changes_revision(self, revision_id, headers):
        return self._request("POST", f"/revisions/{revision_id}/request-changes", {}, headers)

    def resolve_revision(self, revision_id, headers):
        return self._request("POST", f"/revisions/{revision_id}/resolve", {}, headers)

    def dismiss_revision(self, revision_id, headers):
        return self._request("POST", f"/revisions/{revision_id}/dismiss", {}, headers)

    # ----- PunchListItem -----
    def create_punch_item(self, order_id, payload, headers):
        return self._request("POST", f"/orders/{order_id}/punch-items", payload, headers)

    def get_punch_item(self, punch_item_id, headers):
        return self._request("GET", f"/punch-items/{punch_item_id}", headers=headers)

    def list_punch_items(self, headers, params=None):
        return self._request("GET", "/punch-items", headers=headers, params=params)

    def resolve_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/punch-items/{punch_item_id}/resolve", {}, headers)

    def waive_punch_item(self, punch_item_id, headers):
        return self._request("POST", f"/punch-items/{punch_item_id}/waive", {}, headers)

    # ----- TimeEntry -----
    def create_time_entry(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/time-entries", payload, headers)

    def get_time_entry(self, time_entry_id, headers):
        return self._request("GET", f"/time-entries/{time_entry_id}", headers=headers)

    def list_time_entries(self, headers, params=None):
        return self._request("GET", "/time-entries", headers=headers, params=params)

    def approve_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/time-entries/{time_entry_id}/approve", {}, headers)

    def reject_time_entry(self, time_entry_id, headers):
        return self._request("POST", f"/time-entries/{time_entry_id}/reject", {}, headers)


api_client = ApiClient()
