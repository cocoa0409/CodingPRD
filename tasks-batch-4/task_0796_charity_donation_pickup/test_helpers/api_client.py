"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CharityPartner ----
    def create_partner(self, payload, headers):
        return self._request("POST", "/partners", payload, headers)

    def get_partner(self, partner_id, headers):
        return self._request("GET", f"/partners/{partner_id}", headers=headers)

    def update_partner(self, partner_id, payload, headers):
        return self._request("PATCH", f"/partners/{partner_id}", payload, headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    # ---- Route ----
    def create_route(self, payload, headers):
        return self._request("POST", "/routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/routes", headers=headers, params=params)

    def open_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/open", {}, headers)

    def close_route(self, route_id, headers):
        return self._request("POST", f"/routes/{route_id}/close", {}, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/routes/{route_id}/stops", headers=headers, params=params)

    # ---- Donor ----
    def create_donor(self, payload, headers):
        return self._request("POST", "/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/donors/{donor_id}", headers=headers)

    # ---- PickupRequest ----
    def create_pickup_request(self, payload, headers):
        return self._request("POST", "/pickup-requests", payload, headers)

    def get_pickup_request(self, request_id, headers):
        return self._request("GET", f"/pickup-requests/{request_id}", headers=headers)

    def list_pickup_requests(self, headers, params=None):
        return self._request("GET", "/pickup-requests", headers=headers, params=params)

    def add_item(self, request_id, payload, headers):
        return self._request("POST", f"/pickup-requests/{request_id}/items", payload, headers)

    def list_items(self, request_id, headers, params=None):
        return self._request("GET", f"/pickup-requests/{request_id}/items", headers=headers, params=params)

    def list_request_stops(self, request_id, headers, params=None):
        return self._request("GET", f"/pickup-requests/{request_id}/stops", headers=headers, params=params)

    def list_request_haul_invoices(self, request_id, headers, params=None):
        return self._request("GET", f"/pickup-requests/{request_id}/haul-invoices", headers=headers, params=params)

    def schedule_pickup(self, request_id, payload, headers):
        return self._request("POST", f"/pickup-requests/{request_id}/schedule", payload, headers)

    def complete_pickup(self, request_id, payload, headers):
        return self._request("POST", f"/pickup-requests/{request_id}/complete", payload, headers)

    def no_show_pickup(self, request_id, headers):
        return self._request("POST", f"/pickup-requests/{request_id}/no-show", {}, headers)

    def cancel_pickup(self, request_id, headers):
        return self._request("POST", f"/pickup-requests/{request_id}/cancel", {}, headers)

    # ---- DonationItem ----
    def appraise_item(self, item_id, payload, headers):
        return self._request("PATCH", f"/donation-items/{item_id}", payload, headers)

    # ---- DonationReceipt ----
    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/donation-receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/donation-receipts", headers=headers, params=params)

    def void_receipt(self, receipt_id, headers):
        return self._request("POST", f"/donation-receipts/{receipt_id}/void", {}, headers)

    # ---- HaulInvoice ----
    def pay_invoice(self, invoice_id, headers):
        return self._request("POST", f"/haul-invoices/{invoice_id}/pay", {}, headers)

    # ---- RecurringPlan ----
    def create_recurring_plan(self, payload, headers):
        return self._request("POST", "/recurring-plans", payload, headers)

    def get_recurring_plan(self, plan_id, headers):
        return self._request("GET", f"/recurring-plans/{plan_id}", headers=headers)

    def list_recurring_plans(self, headers, params=None):
        return self._request("GET", "/recurring-plans", headers=headers, params=params)

    def pause_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/pause", {}, headers)

    def resume_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/resume", {}, headers)

    def cancel_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/cancel", {}, headers)

    def generate_plan(self, plan_id, headers):
        return self._request("POST", f"/recurring-plans/{plan_id}/generate", {}, headers)

    # ---- Test-driving: logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
