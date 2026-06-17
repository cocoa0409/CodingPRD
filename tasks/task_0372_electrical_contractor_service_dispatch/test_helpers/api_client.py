"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Customer ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/v1/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/v1/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/v1/customers", headers=headers, params=params)

    # ---- Technician ----
    def create_technician(self, payload, headers):
        return self._request("POST", "/v1/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"/v1/technicians/{technician_id}", headers=headers)

    def list_technicians(self, headers, params=None):
        return self._request("GET", "/v1/technicians", headers=headers, params=params)

    # ---- MembershipPlan ----
    def create_membership_plan(self, payload, headers):
        return self._request("POST", "/v1/membership-plans", payload, headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"/v1/membership-plans/{plan_id}", headers=headers)

    def list_membership_plans(self, headers, params=None):
        return self._request("GET", "/v1/membership-plans", headers=headers, params=params)

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/v1/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/v1/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/v1/memberships", headers=headers, params=params)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/v1/memberships/{membership_id}/cancel", {}, headers)

    # ---- MaterialSku ----
    def create_material_sku(self, payload, headers):
        return self._request("POST", "/v1/material-skus", payload, headers)

    def get_material_sku(self, sku_id, headers):
        return self._request("GET", f"/v1/material-skus/{sku_id}", headers=headers)

    def list_material_skus(self, headers, params=None):
        return self._request("GET", "/v1/material-skus", headers=headers, params=params)

    # ---- TruckStockItem ----
    def create_truck_stock_item(self, payload, headers):
        return self._request("POST", "/v1/truck-stock-items", payload, headers)

    def get_truck_stock_item(self, stock_item_id, headers):
        return self._request("GET", f"/v1/truck-stock-items/{stock_item_id}", headers=headers)

    def list_truck_stock_items(self, headers, params=None):
        return self._request("GET", "/v1/truck-stock-items", headers=headers, params=params)

    def restock_truck_stock_item(self, stock_item_id, payload, headers):
        return self._request("POST", f"/v1/truck-stock-items/{stock_item_id}/restock", payload, headers)

    # ---- ServiceJob ----
    def create_service_job(self, payload, headers):
        return self._request("POST", "/v1/service-jobs", payload, headers)

    def get_service_job(self, job_id, headers):
        return self._request("GET", f"/v1/service-jobs/{job_id}", headers=headers)

    def list_service_jobs(self, headers, params=None):
        return self._request("GET", "/v1/service-jobs", headers=headers, params=params)

    def complete_service_job(self, job_id, payload, headers):
        return self._request("POST", f"/v1/service-jobs/{job_id}/complete", payload, headers)

    def invoice_service_job(self, job_id, headers):
        return self._request("POST", f"/v1/service-jobs/{job_id}/invoice", {}, headers)

    def close_service_job(self, job_id, headers):
        return self._request("POST", f"/v1/service-jobs/{job_id}/close", {}, headers)

    def cancel_service_job(self, job_id, headers):
        return self._request("POST", f"/v1/service-jobs/{job_id}/cancel", {}, headers)

    # ---- Estimate ----
    def create_estimate(self, payload, headers):
        return self._request("POST", "/v1/estimates", payload, headers)

    def get_estimate(self, estimate_id, headers):
        return self._request("GET", f"/v1/estimates/{estimate_id}", headers=headers)

    def list_estimates(self, headers, params=None):
        return self._request("GET", "/v1/estimates", headers=headers, params=params)

    def send_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/send", {}, headers)

    def accept_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/accept", {}, headers)

    def reject_estimate(self, estimate_id, headers):
        return self._request("POST", f"/v1/estimates/{estimate_id}/reject", {}, headers)

    # ---- Dispatch ----
    def create_dispatch(self, payload, headers):
        return self._request("POST", "/v1/dispatches", payload, headers)

    def get_dispatch(self, dispatch_id, headers):
        return self._request("GET", f"/v1/dispatches/{dispatch_id}", headers=headers)

    def list_dispatches(self, headers, params=None):
        return self._request("GET", "/v1/dispatches", headers=headers, params=params)

    def depart_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/v1/dispatches/{dispatch_id}/depart", {}, headers)

    def arrive_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/v1/dispatches/{dispatch_id}/arrive", {}, headers)

    def reschedule_dispatch(self, dispatch_id, payload, headers):
        return self._request("POST", f"/v1/dispatches/{dispatch_id}/reschedule", payload, headers)

    def cancel_dispatch(self, dispatch_id, headers):
        return self._request("POST", f"/v1/dispatches/{dispatch_id}/cancel", {}, headers)

    # ---- Permit ----
    def create_permit(self, payload, headers):
        return self._request("POST", "/v1/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/v1/permits/{permit_id}", headers=headers)

    def list_permits(self, headers, params=None):
        return self._request("GET", "/v1/permits", headers=headers, params=params)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/issue", {}, headers)

    def schedule_inspection(self, permit_id, payload, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/schedule-inspection", payload, headers)

    def record_inspection(self, permit_id, payload, headers):
        return self._request("POST", f"/v1/permits/{permit_id}/record-inspection", payload, headers)

    # ---- MaterialUsage ----
    def create_material_usage(self, payload, headers):
        return self._request("POST", "/v1/material-usages", payload, headers)

    def get_material_usage(self, usage_id, headers):
        return self._request("GET", f"/v1/material-usages/{usage_id}", headers=headers)

    def list_material_usages(self, headers, params=None):
        return self._request("GET", "/v1/material-usages", headers=headers, params=params)

    def void_material_usage(self, usage_id, headers):
        return self._request("POST", f"/v1/material-usages/{usage_id}/void", {}, headers)

    # ---- Invoice ----
    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"/v1/invoices/{invoice_id}", headers=headers)

    def list_invoices(self, headers, params=None):
        return self._request("GET", "/v1/invoices", headers=headers, params=params)

    # ---- Callback ----
    def create_callback(self, payload, headers):
        return self._request("POST", "/v1/callbacks", payload, headers)

    def get_callback(self, callback_id, headers):
        return self._request("GET", f"/v1/callbacks/{callback_id}", headers=headers)

    def list_callbacks(self, headers, params=None):
        return self._request("GET", "/v1/callbacks", headers=headers, params=params)

    def resolve_callback(self, callback_id, headers):
        return self._request("POST", f"/v1/callbacks/{callback_id}/resolve", {}, headers)

    # ---- Dispatch queue (computed read) ----
    def get_dispatch_queue(self, headers, params=None):
        return self._request("GET", "/v1/dispatch-queue", headers=headers, params=params)

    # ---- Test-driving: system clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/v1/_clock/set", payload, headers)


api_client = ApiClient()
