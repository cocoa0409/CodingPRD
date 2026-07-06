"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles the
envelope, base URL and header injection.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Config: Package ----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    # ---- Config: Bartender ----
    def create_bartender(self, payload, headers):
        return self._request("POST", "/bartenders", payload, headers)

    def get_bartender(self, bartender_id, headers):
        return self._request("GET", f"/bartenders/{bartender_id}", headers=headers)

    def deactivate_bartender(self, bartender_id, headers):
        return self._request("POST", f"/bartenders/{bartender_id}/deactivate", headers=headers)

    # ---- Config: BarKit ----
    def create_bar_kit(self, payload, headers):
        return self._request("POST", "/bar-kits", payload, headers)

    # ---- Client ----
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    # ---- Event core ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def update_event(self, event_id, payload, headers):
        return self._request("PATCH", f"/events/{event_id}", payload, headers)

    def confirm_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/confirm", headers=headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", headers=headers)

    def start_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/start", headers=headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", headers=headers)

    def close_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/close", headers=headers)

    # ---- Payments ----
    def create_payment(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/payments", payload, headers)

    def list_payments(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/payments", headers=headers, params=params)

    # ---- Compliance ----
    def create_compliance_review(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/compliance-review", payload, headers)

    def list_compliance_reviews(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/compliance-review", headers=headers)

    def submit_review(self, review_id, payload, headers):
        return self._request("POST", f"/compliance-reviews/{review_id}/submit", payload, headers)

    def clear_review(self, review_id, payload, headers):
        return self._request("POST", f"/compliance-reviews/{review_id}/clear", payload, headers)

    def request_changes_review(self, review_id, payload, headers):
        return self._request("POST", f"/compliance-reviews/{review_id}/request-changes", payload, headers)

    # ---- Assignments ----
    def create_assignment(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/assignments", payload, headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/confirm", headers=headers)

    def checkin_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/check-in", headers=headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/cancel", headers=headers)

    def no_show_assignment(self, assignment_id, headers):
        return self._request("POST", f"/assignments/{assignment_id}/no-show", headers=headers)

    # ---- Kit reservations ----
    def create_kit_reservation(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/kit-reservations", payload, headers)

    def list_kit_reservations(self, headers, params=None):
        return self._request("GET", "/kit-reservations", headers=headers, params=params)

    def get_kit_reservation(self, reservation_id, headers):
        return self._request("GET", f"/kit-reservations/{reservation_id}", headers=headers)

    def deploy_kit_reservation(self, reservation_id, headers):
        return self._request("POST", f"/kit-reservations/{reservation_id}/deploy", headers=headers)

    def return_kit_reservation(self, reservation_id, headers):
        return self._request("POST", f"/kit-reservations/{reservation_id}/return", headers=headers)

    def release_kit_reservation(self, reservation_id, headers):
        return self._request("POST", f"/kit-reservations/{reservation_id}/release", headers=headers)

    # ---- Inventory ----
    def create_inventory_plan(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/inventory-plan", {}, headers)

    def list_inventory_plan(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}/inventory-plan", headers=headers)

    # ---- Menu / signature drinks ----
    def create_menu_item(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/menu-items", payload, headers)

    def list_menu_items(self, event_id, headers, params=None):
        return self._request("GET", f"/events/{event_id}/menu-items", headers=headers, params=params)

    # ---- Breakage ----
    def create_breakage_report(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/breakage-reports", payload, headers)

    def list_breakage_reports(self, headers, params=None):
        return self._request("GET", "/breakage-reports", headers=headers, params=params)

    def get_breakage_report(self, report_id, headers):
        return self._request("GET", f"/breakage-reports/{report_id}", headers=headers)

    def settle_breakage_report(self, report_id, headers):
        return self._request("POST", f"/breakage-reports/{report_id}/settle", headers=headers)


api_client = ApiClient()
