"""API client: one method per endpoint defined in the PRD (section 4).

All paths carry the /api prefix. Methods return raw requests.Response so
tests can assert status codes through the framework validators.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Donors
    # ------------------------------------------------------------------
    def create_donor(self, payload, headers):
        return self._request("POST", "/api/donors", payload, headers)

    def get_donor(self, donor_id, headers):
        return self._request("GET", f"/api/donors/{donor_id}", headers=headers)

    def update_donor(self, donor_id, payload, headers):
        return self._request("PATCH", f"/api/donors/{donor_id}", payload, headers)

    # ------------------------------------------------------------------
    # Donation batches
    # ------------------------------------------------------------------
    def create_batch(self, payload, headers):
        return self._request("POST", "/api/donation-batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/api/donation-batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/api/donation-batches", headers=headers, params=params)

    def add_item(self, batch_id, payload, headers):
        return self._request("POST", f"/api/donation-batches/{batch_id}/items",
                             payload, headers)

    def list_batch_items(self, batch_id, headers, params=None):
        return self._request("GET", f"/api/donation-batches/{batch_id}/items",
                             headers=headers, params=params)

    def begin_sort(self, batch_id, headers):
        return self._request("POST", f"/api/donation-batches/{batch_id}/begin-sort",
                             {}, headers)

    def complete_sort(self, batch_id, headers):
        return self._request("POST", f"/api/donation-batches/{batch_id}/complete-sort",
                             {}, headers)

    def revalue_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/api/donation-batches/{batch_id}/revalue",
                             payload, headers)

    def close_batch(self, batch_id, headers):
        return self._request("POST", f"/api/donation-batches/{batch_id}/close",
                             {}, headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/api/donation-batches/{batch_id}/cancel",
                             {}, headers)

    def issue_receipt(self, batch_id, headers):
        return self._request("POST", f"/api/donation-batches/{batch_id}/receipt",
                             {}, headers)

    # ------------------------------------------------------------------
    # Donation items
    # ------------------------------------------------------------------
    def get_item(self, item_id, headers):
        return self._request("GET", f"/api/items/{item_id}", headers=headers)

    def list_items(self, headers, params=None):
        return self._request("GET", "/api/items", headers=headers, params=params)

    def triage_item(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/triage", payload, headers)

    def price_item(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/price", {}, headers)

    def to_floor_item(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/to-floor", {}, headers)

    def hold_item(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/hold", {}, headers)

    def release_hold_item(self, item_id, headers):
        return self._request("POST", f"/api/items/{item_id}/release-hold", {}, headers)

    def shrink_item(self, item_id, payload, headers):
        return self._request("POST", f"/api/items/{item_id}/shrink", payload, headers)

    # ------------------------------------------------------------------
    # Pricing guidelines
    # ------------------------------------------------------------------
    def create_guideline(self, payload, headers):
        return self._request("POST", "/api/pricing-guidelines", payload, headers)

    def get_guideline(self, guideline_id, headers):
        return self._request("GET", f"/api/pricing-guidelines/{guideline_id}",
                             headers=headers)

    def list_guidelines(self, headers, params=None):
        return self._request("GET", "/api/pricing-guidelines", headers=headers,
                             params=params)

    # ------------------------------------------------------------------
    # Salvage vendors and bales
    # ------------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/api/salvage-vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/api/salvage-vendors/{vendor_id}", headers=headers)

    def get_bale(self, bale_id, headers):
        return self._request("GET", f"/api/salvage-bales/{bale_id}", headers=headers)

    def list_bales(self, headers, params=None):
        return self._request("GET", "/api/salvage-bales", headers=headers, params=params)

    def seal_bale(self, bale_id, payload, headers):
        return self._request("POST", f"/api/salvage-bales/{bale_id}/seal",
                             payload, headers)

    def ship_bale(self, bale_id, headers):
        return self._request("POST", f"/api/salvage-bales/{bale_id}/ship", {}, headers)

    def settle_bale(self, bale_id, payload, headers):
        return self._request("POST", f"/api/salvage-bales/{bale_id}/settle",
                             payload, headers)

    # ------------------------------------------------------------------
    # Till sessions and sales
    # ------------------------------------------------------------------
    def create_till_session(self, payload, headers):
        return self._request("POST", "/api/till-sessions", payload, headers)

    def get_till_session(self, session_id, headers):
        return self._request("GET", f"/api/till-sessions/{session_id}", headers=headers)

    def list_till_sessions(self, headers, params=None):
        return self._request("GET", "/api/till-sessions", headers=headers, params=params)

    def count_till_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/till-sessions/{session_id}/count",
                             payload, headers)

    def approve_variance(self, session_id, headers):
        return self._request("POST", f"/api/till-sessions/{session_id}/approve-variance",
                             {}, headers)

    def close_till_session(self, session_id, headers):
        return self._request("POST", f"/api/till-sessions/{session_id}/close",
                             {}, headers)

    def create_sale(self, payload, headers):
        return self._request("POST", "/api/sales", payload, headers)

    def get_sale(self, sale_id, headers):
        return self._request("GET", f"/api/sales/{sale_id}", headers=headers)

    def list_sales(self, headers, params=None):
        return self._request("GET", "/api/sales", headers=headers, params=params)

    def void_sale(self, sale_id, payload, headers):
        return self._request("POST", f"/api/sales/{sale_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Pickup routes and stops
    # ------------------------------------------------------------------
    def create_route(self, payload, headers):
        return self._request("POST", "/api/pickup-routes", payload, headers)

    def get_route(self, route_id, headers):
        return self._request("GET", f"/api/pickup-routes/{route_id}", headers=headers)

    def list_routes(self, headers, params=None):
        return self._request("GET", "/api/pickup-routes", headers=headers, params=params)

    def add_stop(self, route_id, payload, headers):
        return self._request("POST", f"/api/pickup-routes/{route_id}/stops",
                             payload, headers)

    def list_route_stops(self, route_id, headers, params=None):
        return self._request("GET", f"/api/pickup-routes/{route_id}/stops",
                             headers=headers, params=params)

    def get_stop(self, stop_id, headers):
        return self._request("GET", f"/api/pickup-stops/{stop_id}", headers=headers)

    def list_stops(self, headers, params=None):
        return self._request("GET", "/api/pickup-stops", headers=headers, params=params)

    def publish_route(self, route_id, headers):
        return self._request("POST", f"/api/pickup-routes/{route_id}/publish",
                             {}, headers)

    def unpublish_route(self, route_id, headers):
        return self._request("POST", f"/api/pickup-routes/{route_id}/unpublish",
                             {}, headers)

    def start_route(self, route_id, headers):
        return self._request("POST", f"/api/pickup-routes/{route_id}/start", {}, headers)

    def complete_route(self, route_id, headers):
        return self._request("POST", f"/api/pickup-routes/{route_id}/complete",
                             {}, headers)

    def cancel_route(self, route_id, headers):
        return self._request("POST", f"/api/pickup-routes/{route_id}/cancel",
                             {}, headers)

    def depart_stop(self, stop_id, headers):
        return self._request("POST", f"/api/pickup-stops/{stop_id}/depart", {}, headers)

    def complete_stop(self, stop_id, headers):
        return self._request("POST", f"/api/pickup-stops/{stop_id}/complete", {}, headers)

    def no_show_stop(self, stop_id, headers):
        return self._request("POST", f"/api/pickup-stops/{stop_id}/no-show", {}, headers)

    def reschedule_stop(self, stop_id, payload, headers):
        return self._request("POST", f"/api/pickup-stops/{stop_id}/reschedule",
                             payload, headers)

    # ------------------------------------------------------------------
    # Workers, shifts, assignments
    # ------------------------------------------------------------------
    def create_worker(self, payload, headers):
        return self._request("POST", "/api/workers", payload, headers)

    def get_worker(self, worker_id, headers):
        return self._request("GET", f"/api/workers/{worker_id}", headers=headers)

    def update_worker(self, worker_id, payload, headers):
        return self._request("PATCH", f"/api/workers/{worker_id}", payload, headers)

    def create_shift(self, payload, headers):
        return self._request("POST", "/api/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/api/shifts/{shift_id}", headers=headers)

    def assign_worker(self, shift_id, payload, headers):
        return self._request("POST", f"/api/shifts/{shift_id}/assignments",
                             payload, headers)

    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/api/shift-assignments/{assignment_id}",
                             headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/api/shift-assignments", headers=headers,
                             params=params)

    def confirm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/shift-assignments/{assignment_id}/confirm",
                             {}, headers)

    def complete_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/shift-assignments/{assignment_id}/complete",
                             {}, headers)

    def no_show_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/shift-assignments/{assignment_id}/no-show",
                             {}, headers)

    def cancel_assignment(self, assignment_id, headers):
        return self._request("POST", f"/api/shift-assignments/{assignment_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Weekly cycles, mission transfers, tax receipts
    # ------------------------------------------------------------------
    def create_cycle(self, headers):
        return self._request("POST", "/api/cycles", {}, headers)

    def list_cycles(self, headers, params=None):
        return self._request("GET", "/api/cycles", headers=headers, params=params)

    def get_cycle(self, cycle_id, headers):
        return self._request("GET", f"/api/cycles/{cycle_id}", headers=headers)

    def run_markdown(self, cycle_id, headers):
        return self._request("POST", f"/api/cycles/{cycle_id}/run-markdown", {}, headers)

    def close_cycle(self, cycle_id, headers):
        return self._request("POST", f"/api/cycles/{cycle_id}/close", {}, headers)

    def create_mission_transfer(self, cycle_id, payload, headers):
        return self._request("POST", f"/api/cycles/{cycle_id}/mission-transfers",
                             payload, headers)

    def get_transfer(self, transfer_id, headers):
        return self._request("GET", f"/api/mission-transfers/{transfer_id}",
                             headers=headers)

    def list_transfers(self, headers, params=None):
        return self._request("GET", "/api/mission-transfers", headers=headers,
                             params=params)

    def approve_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/mission-transfers/{transfer_id}/approve",
                             {}, headers)

    def disburse_transfer(self, transfer_id, headers):
        return self._request("POST", f"/api/mission-transfers/{transfer_id}/disburse",
                             {}, headers)

    def get_receipt(self, receipt_id, headers):
        return self._request("GET", f"/api/tax-receipts/{receipt_id}", headers=headers)

    def list_receipts(self, headers, params=None):
        return self._request("GET", "/api/tax-receipts", headers=headers, params=params)

    def void_receipt(self, receipt_id, headers):
        return self._request("POST", f"/api/tax-receipts/{receipt_id}/void", {}, headers)


api_client = ApiClient()
