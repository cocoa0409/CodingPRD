"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Partner agencies
    # ------------------------------------------------------------------
    def create_agency(self, payload, headers):
        return self._request("POST", "/partner-agencies", payload, headers)

    def list_agencies(self, headers, params=None):
        return self._request("GET", "/partner-agencies", headers=headers, params=params)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/partner-agencies/{agency_id}", headers=headers)

    def patch_agency(self, agency_id, payload, headers):
        return self._request("PATCH", f"/partner-agencies/{agency_id}", payload, headers)

    def suspend_agency(self, agency_id, headers):
        return self._request("POST", f"/partner-agencies/{agency_id}/suspend", {}, headers)

    def list_agency_allocation_lines(self, agency_id, headers, params=None):
        return self._request("GET", f"/partner-agencies/{agency_id}/allocation-lines",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Grants
    # ------------------------------------------------------------------
    def create_grant(self, payload, headers):
        return self._request("POST", "/grants", payload, headers)

    def get_grant(self, grant_id, headers):
        return self._request("GET", f"/grants/{grant_id}", headers=headers)

    def close_grant(self, grant_id, headers):
        return self._request("POST", f"/grants/{grant_id}/close", {}, headers)

    def get_impact_report(self, grant_id, headers, params=None):
        return self._request("GET", f"/grants/{grant_id}/impact-report",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------
    def initialize_inventory(self, payload, headers):
        return self._request("POST", "/inventory/initialize", payload, headers)

    def get_inventory(self, headers):
        return self._request("GET", "/inventory", headers=headers)

    def create_inventory_adjustment(self, payload, headers):
        return self._request("POST", "/inventory/adjustments", payload, headers)

    def get_inventory_forecast(self, headers, params=None):
        return self._request("GET", "/inventory/forecast", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Intake batches
    # ------------------------------------------------------------------
    def create_intake_batch(self, payload, headers):
        return self._request("POST", "/intake-batches", payload, headers)

    def list_intake_batches(self, headers, params=None):
        return self._request("GET", "/intake-batches", headers=headers, params=params)

    def get_intake_batch(self, batch_id, headers):
        return self._request("GET", f"/intake-batches/{batch_id}", headers=headers)

    def post_intake_batch(self, batch_id, headers):
        return self._request("POST", f"/intake-batches/{batch_id}/post", {}, headers)

    def recount_intake_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/intake-batches/{batch_id}/recount", payload, headers)

    def void_intake_batch(self, batch_id, payload, headers):
        return self._request("POST", f"/intake-batches/{batch_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Purchase orders
    # ------------------------------------------------------------------
    def create_purchase_order(self, payload, headers):
        return self._request("POST", "/purchase-orders", payload, headers)

    def list_purchase_orders(self, headers, params=None):
        return self._request("GET", "/purchase-orders", headers=headers, params=params)

    def get_purchase_order(self, po_id, headers):
        return self._request("GET", f"/purchase-orders/{po_id}", headers=headers)

    def submit_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/submit", {}, headers)

    def receive_purchase_order(self, po_id, payload, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/receive", payload, headers)

    def cancel_purchase_order(self, po_id, headers):
        return self._request("POST", f"/purchase-orders/{po_id}/cancel", {}, headers)

    # ------------------------------------------------------------------
    # Allocation runs
    # ------------------------------------------------------------------
    def create_allocation_run(self, payload, headers):
        return self._request("POST", "/allocation-runs", payload, headers)

    def get_allocation_run(self, run_id, headers):
        return self._request("GET", f"/allocation-runs/{run_id}", headers=headers)

    def list_allocation_run_lines(self, run_id, headers, params=None):
        return self._request("GET", f"/allocation-runs/{run_id}/lines",
                             headers=headers, params=params)

    def compute_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/compute", {}, headers)

    def publish_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/publish", {}, headers)

    def finalize_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/finalize", {}, headers)

    def retract_allocation_run(self, run_id, headers):
        return self._request("POST", f"/allocation-runs/{run_id}/retract", {}, headers)

    # ------------------------------------------------------------------
    # Distribution events and issuances
    # ------------------------------------------------------------------
    def create_distribution_event(self, payload, headers):
        return self._request("POST", "/distribution-events", payload, headers)

    def list_distribution_events(self, headers, params=None):
        return self._request("GET", "/distribution-events", headers=headers, params=params)

    def get_distribution_event(self, event_id, headers):
        return self._request("GET", f"/distribution-events/{event_id}", headers=headers)

    def open_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/open", {}, headers)

    def lock_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/lock", {}, headers)

    def unlock_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/unlock", {}, headers)

    def complete_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/complete", {}, headers)

    def cancel_distribution_event(self, event_id, headers):
        return self._request("POST", f"/distribution-events/{event_id}/cancel", {}, headers)

    def record_issuance(self, event_id, payload, headers):
        return self._request("POST", f"/distribution-events/{event_id}/issuances",
                             payload, headers)

    def list_event_issuances(self, event_id, headers, params=None):
        return self._request("GET", f"/distribution-events/{event_id}/issuances",
                             headers=headers, params=params)

    def void_issuance(self, issuance_id, payload, headers):
        return self._request("POST", f"/issuances/{issuance_id}/void", payload, headers)

    # ------------------------------------------------------------------
    # Client households
    # ------------------------------------------------------------------
    def create_household(self, payload, headers):
        return self._request("POST", "/households", payload, headers)

    def get_household(self, household_id, headers):
        return self._request("GET", f"/households/{household_id}", headers=headers)

    def patch_household(self, household_id, payload, headers):
        return self._request("PATCH", f"/households/{household_id}", payload, headers)

    def list_household_issuances(self, household_id, headers, params=None):
        return self._request("GET", f"/households/{household_id}/issuances",
                             headers=headers, params=params)

    # ------------------------------------------------------------------
    # Volunteer shifts
    # ------------------------------------------------------------------
    def create_volunteer_shift(self, payload, headers):
        return self._request("POST", "/volunteer-shifts", payload, headers)

    def signup_volunteer(self, shift_id, payload, headers):
        return self._request("POST", f"/volunteer-shifts/{shift_id}/signups",
                             payload, headers)

    def withdraw_volunteer(self, shift_id, payload, headers):
        return self._request("POST", f"/volunteer-shifts/{shift_id}/withdraw",
                             payload, headers)


api_client = ApiClient()
