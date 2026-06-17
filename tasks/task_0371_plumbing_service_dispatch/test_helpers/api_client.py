"""API client: one method per endpoint defined in the PRD (§4).

All routes are mounted under the /plumbing prefix. The base _request() method
is inherited from GenericApiClient.
"""
from prd_bench_local_runner.testing import GenericApiClient

PREFIX = "/plumbing"


class ApiClient(GenericApiClient):
    # ─── Clock control (test-driving, §3.10) ──────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", f"{PREFIX}/_clock/set",
                             {"to_iso8601": to_iso8601}, headers)

    # ─── Membership plans ─────────────────────────────────────────────
    def create_membership_plan(self, payload, headers):
        return self._request("POST", f"{PREFIX}/membership-plans", payload, headers)

    def get_membership_plan(self, plan_id, headers):
        return self._request("GET", f"{PREFIX}/membership-plans/{plan_id}", headers=headers)

    # ─── Flat-rate items ──────────────────────────────────────────────
    def create_flat_rate_item(self, payload, headers):
        return self._request("POST", f"{PREFIX}/flat-rate-items", payload, headers)

    def get_flat_rate_item(self, item_id, headers):
        return self._request("GET", f"{PREFIX}/flat-rate-items/{item_id}", headers=headers)

    # ─── Parts ────────────────────────────────────────────────────────
    def create_part(self, payload, headers):
        return self._request("POST", f"{PREFIX}/parts", payload, headers)

    def get_part(self, part_id, headers):
        return self._request("GET", f"{PREFIX}/parts/{part_id}", headers=headers)

    # ─── Customers ────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", f"{PREFIX}/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"{PREFIX}/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/customers", headers=headers, params=params)

    def patch_customer(self, customer_id, payload, headers):
        return self._request("PATCH", f"{PREFIX}/customers/{customer_id}", payload, headers)

    # ─── Technicians ──────────────────────────────────────────────────
    def create_technician(self, payload, headers):
        return self._request("POST", f"{PREFIX}/technicians", payload, headers)

    def get_technician(self, technician_id, headers):
        return self._request("GET", f"{PREFIX}/technicians/{technician_id}", headers=headers)

    def set_technician_status(self, technician_id, payload, headers):
        return self._request("POST", f"{PREFIX}/technicians/{technician_id}/set-status",
                             payload, headers)

    def get_callback_rate(self, technician_id, headers):
        return self._request("GET", f"{PREFIX}/technicians/{technician_id}/callback-rate",
                             headers=headers)

    def list_technician_truck_stock(self, technician_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/technicians/{technician_id}/truck-stock",
                             headers=headers, params=params)

    # ─── Truck stock ──────────────────────────────────────────────────
    def create_truck_stock(self, payload, headers):
        return self._request("POST", f"{PREFIX}/truck-stock", payload, headers)

    def list_truck_stock(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/truck-stock", headers=headers, params=params)

    def get_truck_stock(self, ts_id, headers):
        return self._request("GET", f"{PREFIX}/truck-stock/{ts_id}", headers=headers)

    # ─── Inspectors ───────────────────────────────────────────────────
    def create_inspector(self, payload, headers):
        return self._request("POST", f"{PREFIX}/inspectors", payload, headers)

    def get_inspector(self, inspector_id, headers):
        return self._request("GET", f"{PREFIX}/inspectors/{inspector_id}", headers=headers)

    # ─── Service jobs ─────────────────────────────────────────────────
    def create_service_job(self, payload, headers):
        return self._request("POST", f"{PREFIX}/service-jobs", payload, headers)

    def get_service_job(self, job_id, headers):
        return self._request("GET", f"{PREFIX}/service-jobs/{job_id}", headers=headers)

    def list_service_jobs(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-jobs", headers=headers, params=params)

    def start_work(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/service-jobs/{job_id}/start-work",
                             {}, headers)

    def complete_job(self, job_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-jobs/{job_id}/complete",
                             payload, headers)

    def cancel_job(self, job_id, headers):
        return self._request("POST", f"{PREFIX}/service-jobs/{job_id}/cancel", {}, headers)

    # ─── Dispatch assignments ─────────────────────────────────────────
    def create_dispatch_assignment(self, payload, headers):
        return self._request("POST", f"{PREFIX}/dispatch-assignments", payload, headers)

    def get_dispatch_assignment(self, asg_id, headers):
        return self._request("GET", f"{PREFIX}/dispatch-assignments/{asg_id}", headers=headers)

    def list_dispatch_assignments(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/dispatch-assignments",
                             headers=headers, params=params)

    def confirm_assignment(self, asg_id, headers):
        return self._request("POST", f"{PREFIX}/dispatch-assignments/{asg_id}/confirm",
                             {}, headers)

    def depart_assignment(self, asg_id, headers):
        return self._request("POST", f"{PREFIX}/dispatch-assignments/{asg_id}/depart",
                             {}, headers)

    def arrive_assignment(self, asg_id, headers):
        return self._request("POST", f"{PREFIX}/dispatch-assignments/{asg_id}/arrive",
                             {}, headers)

    def cancel_assignment(self, asg_id, headers):
        return self._request("POST", f"{PREFIX}/dispatch-assignments/{asg_id}/cancel",
                             {}, headers)

    # ─── Estimates ────────────────────────────────────────────────────
    def create_estimate(self, job_id, payload, headers):
        return self._request("POST", f"{PREFIX}/service-jobs/{job_id}/estimates",
                             payload, headers)

    def list_job_estimates(self, job_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-jobs/{job_id}/estimates",
                             headers=headers, params=params)

    def get_estimate(self, est_id, headers):
        return self._request("GET", f"{PREFIX}/estimates/{est_id}", headers=headers)

    def add_estimate_line(self, est_id, payload, headers):
        return self._request("POST", f"{PREFIX}/estimates/{est_id}/lines", payload, headers)

    def list_estimate_lines(self, est_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/estimates/{est_id}/lines",
                             headers=headers, params=params)

    def get_estimate_line(self, line_id, headers):
        return self._request("GET", f"{PREFIX}/estimate-lines/{line_id}", headers=headers)

    def list_estimate_lines_filtered(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/estimate-lines",
                             headers=headers, params=params)

    def present_estimate(self, est_id, headers):
        return self._request("POST", f"{PREFIX}/estimates/{est_id}/present", {}, headers)

    def revise_estimate(self, est_id, headers):
        return self._request("POST", f"{PREFIX}/estimates/{est_id}/revise", {}, headers)

    def approve_estimate(self, est_id, headers):
        return self._request("POST", f"{PREFIX}/estimates/{est_id}/approve", {}, headers)

    def decline_estimate(self, est_id, headers):
        return self._request("POST", f"{PREFIX}/estimates/{est_id}/decline", {}, headers)

    # ─── Permits & inspections ────────────────────────────────────────
    def list_job_permits(self, job_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-jobs/{job_id}/permits",
                             headers=headers, params=params)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}", headers=headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"{PREFIX}/permits/{permit_id}/issue", {}, headers)

    def schedule_inspection(self, permit_id, payload, headers):
        return self._request("POST", f"{PREFIX}/permits/{permit_id}/inspections",
                             payload, headers)

    def list_permit_inspections(self, permit_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/permits/{permit_id}/inspections",
                             headers=headers, params=params)

    def list_inspections(self, headers, params=None):
        return self._request("GET", f"{PREFIX}/inspections", headers=headers, params=params)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"{PREFIX}/inspections/{inspection_id}", headers=headers)

    def record_inspection(self, inspection_id, payload, headers):
        return self._request("POST", f"{PREFIX}/inspections/{inspection_id}/record",
                             payload, headers)

    # ─── Invoices ─────────────────────────────────────────────────────
    def list_job_invoices(self, job_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-jobs/{job_id}/invoices",
                             headers=headers, params=params)

    def get_invoice(self, invoice_id, headers):
        return self._request("GET", f"{PREFIX}/invoices/{invoice_id}", headers=headers)

    # ─── Callbacks ────────────────────────────────────────────────────
    def create_callback(self, payload, headers):
        return self._request("POST", f"{PREFIX}/callbacks", payload, headers)

    def get_callback(self, callback_id, headers):
        return self._request("GET", f"{PREFIX}/callbacks/{callback_id}", headers=headers)

    def list_job_callbacks(self, job_id, headers, params=None):
        return self._request("GET", f"{PREFIX}/service-jobs/{job_id}/callbacks",
                             headers=headers, params=params)

    def accept_callback(self, callback_id, headers):
        return self._request("POST", f"{PREFIX}/callbacks/{callback_id}/accept", {}, headers)

    def reject_callback(self, callback_id, headers):
        return self._request("POST", f"{PREFIX}/callbacks/{callback_id}/reject", {}, headers)


api_client = ApiClient()
