"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- identity / registration ----
    def register_client(self, payload, headers=None):
        return self._request("POST", "/clients/register", payload, headers=headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def register_staff(self, payload, headers=None):
        return self._request("POST", "/staff/register", payload, headers=headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/staff/{staff_id}", headers=headers)

    # ---- project ----
    def create_project(self, payload, headers):
        return self._request("POST", "/projects", payload, headers=headers)

    def list_projects(self, headers, params=None):
        return self._request("GET", "/projects", headers=headers, params=params)

    def get_project(self, project_id, headers):
        return self._request("GET", f"/projects/{project_id}", headers=headers)

    def complete_project(self, project_id, headers):
        return self._request("POST", f"/projects/{project_id}/complete", {}, headers=headers)

    def cancel_project(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/cancel", payload, headers=headers)

    # ---- measurement ----
    def create_measurement(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/measurements", payload, headers=headers)

    def get_measurement(self, measurement_id, headers):
        return self._request("GET", f"/measurements/{measurement_id}", headers=headers)

    def list_measurements(self, headers, params=None):
        return self._request("GET", "/measurements", headers=headers, params=params)

    # ---- estimate + line items ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/estimates", payload, headers=headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/estimates", headers=headers, params=params)

    def create_line_item(self, estimate_id, payload, headers):
        return self._request("POST", f"/estimates/{estimate_id}/line-items", payload, headers=headers)

    def get_line_item(self, line_item_id, headers):
        return self._request("GET", f"/line-items/{line_item_id}", headers=headers)

    def list_line_items(self, headers, params=None):
        return self._request("GET", "/line-items", headers=headers, params=params)

    def baseline_estimate(self, estimate_id, headers):
        return self._request("POST", f"/estimates/{estimate_id}/baseline", {}, headers=headers)

    # ---- permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers=headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, payload, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", payload, headers=headers)

    def reject_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/reject", {}, headers=headers)

    # ---- HOA ----
    def create_hoa_approval(self, payload, headers):
        return self._request("POST", "/hoa-approvals", payload, headers=headers)

    def get_hoa_approval(self, hoa_id, headers):
        return self._request("GET", f"/hoa-approvals/{hoa_id}", headers=headers)

    def list_hoa_approvals(self, headers, params=None):
        return self._request("GET", "/hoa-approvals", headers=headers, params=params)

    def approve_hoa(self, hoa_id, headers):
        return self._request("POST", f"/hoa-approvals/{hoa_id}/approve", {}, headers=headers)

    def deny_hoa(self, hoa_id, headers):
        return self._request("POST", f"/hoa-approvals/{hoa_id}/deny", {}, headers=headers)

    # ---- material order ----
    def create_material_order(self, payload, headers):
        return self._request("POST", "/material-orders", payload, headers=headers)

    def get_material_order(self, mo_id, headers):
        return self._request("GET", f"/material-orders/{mo_id}", headers=headers)

    def list_material_orders(self, headers, params=None):
        return self._request("GET", "/material-orders", headers=headers, params=params)

    def confirm_material_order(self, mo_id, payload, headers):
        return self._request("POST", f"/material-orders/{mo_id}/confirm", payload, headers=headers)

    def backorder_material_order(self, mo_id, payload, headers):
        return self._request("POST", f"/material-orders/{mo_id}/backorder", payload, headers=headers)

    def deliver_material_order(self, mo_id, headers):
        return self._request("POST", f"/material-orders/{mo_id}/deliver", {}, headers=headers)

    def cancel_material_order(self, mo_id, headers):
        return self._request("POST", f"/material-orders/{mo_id}/cancel", {}, headers=headers)

    # ---- change order ----
    def create_change_order(self, payload, headers):
        return self._request("POST", "/change-orders", payload, headers=headers)

    def get_change_order(self, co_id, headers):
        return self._request("GET", f"/change-orders/{co_id}", headers=headers)

    def list_change_orders(self, headers, params=None):
        return self._request("GET", "/change-orders", headers=headers, params=params)

    def sign_change_order(self, co_id, headers):
        return self._request("POST", f"/change-orders/{co_id}/sign", {}, headers=headers)

    def negotiate_change_order(self, co_id, headers):
        return self._request("POST", f"/change-orders/{co_id}/negotiate", {}, headers=headers)

    def revise_change_order(self, co_id, payload, headers):
        return self._request("POST", f"/change-orders/{co_id}/revise", payload, headers=headers)

    def approve_change_order(self, co_id, payload, headers):
        return self._request("POST", f"/change-orders/{co_id}/approve", payload, headers=headers)

    def reject_change_order(self, co_id, headers):
        return self._request("POST", f"/change-orders/{co_id}/reject", {}, headers=headers)

    def withdraw_change_order(self, co_id, headers):
        return self._request("POST", f"/change-orders/{co_id}/withdraw", {}, headers=headers)

    # ---- crew + work schedule ----
    def create_crew(self, payload, headers):
        return self._request("POST", "/crews", payload, headers=headers)

    def get_crew(self, crew_id, headers):
        return self._request("GET", f"/crews/{crew_id}", headers=headers)

    def create_work_schedule(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/work-schedules", payload, headers=headers)

    def get_work_schedule(self, ws_id, headers):
        return self._request("GET", f"/work-schedules/{ws_id}", headers=headers)

    def list_work_schedules(self, headers, params=None):
        return self._request("GET", "/work-schedules", headers=headers, params=params)

    def confirm_work_schedule(self, ws_id, headers):
        return self._request("POST", f"/work-schedules/{ws_id}/confirm", {}, headers=headers)

    def reweather_work_schedule(self, ws_id, payload, headers):
        return self._request("POST", f"/work-schedules/{ws_id}/reweather", payload, headers=headers)

    def start_work_schedule(self, ws_id, headers):
        return self._request("POST", f"/work-schedules/{ws_id}/start", {}, headers=headers)

    def complete_work_schedule(self, ws_id, headers):
        return self._request("POST", f"/work-schedules/{ws_id}/complete", {}, headers=headers)

    def cancel_work_schedule(self, ws_id, headers):
        return self._request("POST", f"/work-schedules/{ws_id}/cancel", {}, headers=headers)

    # ---- progress draw ----
    def create_progress_draw(self, project_id, payload, headers):
        return self._request("POST", f"/projects/{project_id}/progress-draws", payload, headers=headers)

    def get_progress_draw(self, draw_id, headers):
        return self._request("GET", f"/progress-draws/{draw_id}", headers=headers)

    def list_progress_draws(self, headers, params=None):
        return self._request("GET", "/progress-draws", headers=headers, params=params)

    def approve_progress_draw(self, draw_id, headers):
        return self._request("POST", f"/progress-draws/{draw_id}/approve", {}, headers=headers)

    def release_progress_draw(self, draw_id, payload, headers):
        return self._request("POST", f"/progress-draws/{draw_id}/release", payload, headers=headers)

    def clawback_progress_draw(self, draw_id, payload, headers):
        return self._request("POST", f"/progress-draws/{draw_id}/clawback", payload, headers=headers)

    def reject_progress_draw(self, draw_id, headers):
        return self._request("POST", f"/progress-draws/{draw_id}/reject", {}, headers=headers)

    # ---- warranty ----
    def get_warranty(self, warranty_id, headers):
        return self._request("GET", f"/warranties/{warranty_id}", headers=headers)

    def list_warranties(self, headers, params=None):
        return self._request("GET", "/warranties", headers=headers, params=params)

    # ---- financing ----
    def create_financing_application(self, payload, headers):
        return self._request("POST", "/financing-applications", payload, headers=headers)

    def get_financing_application(self, fa_id, headers):
        return self._request("GET", f"/financing-applications/{fa_id}", headers=headers)

    def list_financing_applications(self, headers, params=None):
        return self._request("GET", "/financing-applications", headers=headers, params=params)

    def decide_financing_application(self, fa_id, headers):
        return self._request("POST", f"/financing-applications/{fa_id}/decide", {}, headers=headers)

    # ---- test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers=headers)


api_client = ApiClient()
