"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Customer ---
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # --- Project ---
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def cancel_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", {}, headers)

    # --- Estimate ---
    def create_estimate(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/estimates", payload, headers)

    def list_estimates(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/estimates", headers=headers, params=params)

    def price_estimate(self, project_id, estimate_id, headers):
        return self._request("POST", f"/projects/{project_id}/estimates/{estimate_id}/price", {}, headers)

    def accept_estimate(self, project_id, estimate_id, headers):
        return self._request("POST", f"/projects/{project_id}/estimates/{estimate_id}/accept", {}, headers)

    # --- LineItem ---
    def create_line_item(self, payload, headers):
        return self._request("POST", "/line-items", payload, headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    # --- SiteMeasure ---
    def create_site_measure(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/site-measures", payload, headers)

    def list_site_measures(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/site-measures", headers=headers, params=params)

    def approve_site_measure(self, project_id, site_measure_id, headers):
        return self._request("POST", f"/projects/{project_id}/site-measures/{site_measure_id}/approve", {}, headers)

    # --- Permit ---
    def create_permit(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/permits", payload, headers)

    def list_permits(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/permits", headers=headers, params=params)

    def submit_permit(self, project_id, permit_id, headers):
        return self._request("POST", f"/projects/{project_id}/permits/{permit_id}/submit", {}, headers)

    def decide_permit(self, project_id, permit_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/permits/{permit_id}/decide", payload, headers)

    # --- HoaApproval ---
    def create_hoa_approval(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/hoa-approvals", payload, headers)

    def list_hoa_approvals(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/hoa-approvals", headers=headers, params=params)

    def decide_hoa_approval(self, project_id, hoa_approval_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/hoa-approvals/{hoa_approval_id}/decide", payload, headers)

    # --- MaterialOrder ---
    def create_material_order(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/material-orders", payload, headers)

    def list_material_orders(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/material-orders", headers=headers, params=params)

    def confirm_material_order(self, project_id, material_order_id, headers):
        return self._request("POST", f"/projects/{project_id}/material-orders/{material_order_id}/confirm", {}, headers)

    def deliver_material_order(self, project_id, material_order_id, headers):
        return self._request("POST", f"/projects/{project_id}/material-orders/{material_order_id}/deliver", {}, headers)

    def cancel_material_order(self, project_id, material_order_id, headers):
        return self._request("POST", f"/projects/{project_id}/material-orders/{material_order_id}/cancel", {}, headers)

    # --- CrewBooking ---
    def create_crew_booking(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/crew-bookings", payload, headers)

    def list_crew_bookings(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/crew-bookings", headers=headers, params=params)

    def confirm_crew_booking(self, project_id, crew_booking_id, headers):
        return self._request("POST", f"/projects/{project_id}/crew-bookings/{crew_booking_id}/confirm", {}, headers)

    def cancel_crew_booking(self, project_id, crew_booking_id, headers):
        return self._request("POST", f"/projects/{project_id}/crew-bookings/{crew_booking_id}/cancel", {}, headers)

    # --- ChangeOrder ---
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers)

    def get_change_order(self, change_order_id, headers):
        return self._request("GET", f"/change-orders/{change_order_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def apply_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/apply", {}, headers)

    def decide_change_order(self, change_order_id, payload, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/decide", payload, headers)

    def withdraw_change_order(self, change_order_id, headers):
        return self._request("POST", f"/change-orders/{change_order_id}/withdraw", {}, headers)

    # --- Draw ---
    def list_draws(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/draws", headers=headers, params=params)

    def invoice_draw(self, project_id, draw_id, headers):
        return self._request("POST", f"/projects/{project_id}/draws/{draw_id}/invoice", {}, headers)

    def pay_draw(self, project_id, draw_id, headers):
        return self._request("POST", f"/projects/{project_id}/draws/{draw_id}/pay", {}, headers)

    # --- Warranty ---
    def list_warranties(self, project_id, headers, params=None):
        return self._request("GET", f"/projects/{project_id}/warranties", headers=headers, params=params)

    def update_warranty(self, project_id, warranty_id, payload, headers):
        return self._request("PATCH", f"/projects/{project_id}/warranties/{warranty_id}", payload, headers)

    def claim_warranty(self, project_id, warranty_id, headers):
        return self._request("POST", f"/projects/{project_id}/warranties/{warranty_id}/claim", {}, headers)

    def resolve_warranty(self, project_id, warranty_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/warranties/{warranty_id}/resolve", payload, headers)

    # --- Clock (test-driving) ---
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
