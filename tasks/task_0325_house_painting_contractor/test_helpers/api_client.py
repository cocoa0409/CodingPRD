"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── PaintProduct ───────────────────────────────────────────────────
    def create_paint_product(self, payload, headers):
        return self._request("POST", "/painting/paint-products", payload, headers)

    def get_paint_product(self, paint_product_id, headers):
        return self._request("GET", f"/painting/paint-products/{paint_product_id}", headers=headers)

    def list_paint_products(self, headers, params=None):
        return self._request("GET", "/painting/paint-products", headers=headers, params=params)

    # ─── CrewMember ─────────────────────────────────────────────────────
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/painting/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request("GET", f"/painting/crew-members/{crew_member_id}", headers=headers)

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/painting/crew-members", headers=headers, params=params)

    # ─── Equipment ──────────────────────────────────────────────────────
    def create_equipment(self, payload, headers):
        return self._request("POST", "/painting/equipment", payload, headers)

    def get_equipment(self, equipment_id, headers):
        return self._request("GET", f"/painting/equipment/{equipment_id}", headers=headers)

    def list_equipment(self, headers, params=None):
        return self._request("GET", "/painting/equipment", headers=headers, params=params)

    # ─── WeatherWindow ──────────────────────────────────────────────────
    def create_weather_window(self, payload, headers):
        return self._request("POST", "/painting/weather-windows", payload, headers)

    def get_weather_window(self, weather_window_id, headers):
        return self._request("GET", f"/painting/weather-windows/{weather_window_id}", headers=headers)

    def list_weather_windows(self, headers, params=None):
        return self._request("GET", "/painting/weather-windows", headers=headers, params=params)

    # ─── Project ────────────────────────────────────────────────────────
    def create_project(self, payload, headers):
        return self._request("POST", "/painting/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/painting/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/painting/projects", headers=headers, params=params)

    def finalize_estimate(self, project_id, headers):
        return self._request("POST", f"/painting/projects/{project_id}/finalize-estimate", {}, headers)

    def schedule_project(self, project_id, headers):
        return self._request("POST", f"/painting/projects/{project_id}/schedule", {}, headers)

    def start_work(self, project_id, headers):
        return self._request("POST", f"/painting/projects/{project_id}/start-work", {}, headers)

    def request_walkthrough(self, project_id, headers):
        return self._request("POST", f"/painting/projects/{project_id}/request-walkthrough", {}, headers)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/painting/projects/{project_id}/cancel", {}, headers)

    # ─── Surface ────────────────────────────────────────────────────────
    def create_surface(self, payload, headers):
        return self._request("POST", "/painting/surfaces", payload, headers)

    def get_surface(self, surface_id, headers):
        return self._request("GET", f"/painting/surfaces/{surface_id}", headers=headers)

    def list_surfaces(self, headers, params=None):
        return self._request("GET", "/painting/surfaces", headers=headers, params=params)

    # ─── LineItem (computed, read-only) ─────────────────────────────────
    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/painting/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/painting/line-items", headers=headers, params=params)

    # ─── ColorSelection ─────────────────────────────────────────────────
    def create_color_selection(self, payload, headers):
        return self._request("POST", "/painting/color-selections", payload, headers)

    def get_color_selection(self, color_selection_id, headers):
        return self._request("GET", f"/painting/color-selections/{color_selection_id}", headers=headers)

    def list_color_selections(self, headers, params=None):
        return self._request("GET", "/painting/color-selections", headers=headers, params=params)

    def approve_color_selection(self, color_selection_id, headers):
        return self._request("POST", f"/painting/color-selections/{color_selection_id}/approve", {}, headers)

    def reject_color_selection(self, color_selection_id, headers):
        return self._request("POST", f"/painting/color-selections/{color_selection_id}/reject", {}, headers)

    # ─── ChangeOrder ────────────────────────────────────────────────────
    def create_change_order(self, payload, headers):
        return self._request("POST", "/painting/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/painting/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/painting/change-orders", headers=headers, params=params)

    def submit_change_order(self, change_order_id, headers):
        return self._request("POST", f"/painting/change-orders/{change_order_id}/submit", {}, headers)

    def approve_change_order(self, change_order_id, headers):
        return self._request("POST", f"/painting/change-orders/{change_order_id}/approve", {}, headers)

    def reject_change_order(self, change_order_id, headers):
        return self._request("POST", f"/painting/change-orders/{change_order_id}/reject", {}, headers)

    def revise_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/painting/change-orders/{change_order_id}/revise", payload, headers)

    # ─── CrewAssignment ─────────────────────────────────────────────────
    def create_crew_assignment(self, payload, headers):
        return self._request("POST", "/painting/crew-assignments", payload, headers)

    def get_crew_assignment(self, assignment_id, headers):
        return self._request("GET", f"/painting/crew-assignments/{assignment_id}", headers=headers)

    def list_crew_assignments(self, headers, params=None):
        return self._request("GET", "/painting/crew-assignments", headers=headers, params=params)

    def begin_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/painting/crew-assignments/{assignment_id}/begin", {}, headers)

    def complete_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/painting/crew-assignments/{assignment_id}/complete", {}, headers)

    def cancel_crew_assignment(self, assignment_id, headers):
        return self._request("POST", f"/painting/crew-assignments/{assignment_id}/cancel", {}, headers)

    # ─── Payment ────────────────────────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/painting/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/painting/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/painting/payments", headers=headers, params=params)

    # ─── Walkthrough ────────────────────────────────────────────────────
    def get_walkthrough(self, walkthrough_id, headers):
        return self._request("GET", f"/painting/walkthroughs/{walkthrough_id}", headers=headers)

    def list_walkthroughs(self, headers, params=None):
        return self._request("GET", "/painting/walkthroughs", headers=headers, params=params)

    def pass_walkthrough(self, walkthrough_id, headers):
        return self._request("POST", f"/painting/walkthroughs/{walkthrough_id}/pass", {}, headers)

    def fail_walkthrough(self, walkthrough_id, headers):
        return self._request("POST", f"/painting/walkthroughs/{walkthrough_id}/fail", {}, headers)

    def reopen_walkthrough(self, walkthrough_id, payload, headers):
        return self._request("POST", f"/painting/walkthroughs/{walkthrough_id}/reopen", payload, headers)

    # ─── WarrantyClaim ──────────────────────────────────────────────────
    def create_warranty_claim(self, payload, headers):
        return self._request("POST", "/painting/warranty-claims", payload, headers)

    def get_warranty_claim(self, claim_id, headers):
        return self._request("GET", f"/painting/warranty-claims/{claim_id}", headers=headers)

    def list_warranty_claims(self, headers, params=None):
        return self._request("GET", "/painting/warranty-claims", headers=headers, params=params)

    def approve_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/painting/warranty-claims/{claim_id}/approve", {}, headers)

    def deny_warranty_claim(self, claim_id, headers):
        return self._request("POST", f"/painting/warranty-claims/{claim_id}/deny", {}, headers)

    def resolve_warranty_claim(self, claim_id, payload, headers):
        return self._request("POST", f"/painting/warranty-claims/{claim_id}/resolve", payload, headers)

    # ─── Test-driving clock ─────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
