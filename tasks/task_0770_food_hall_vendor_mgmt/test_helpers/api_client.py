"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (test-driving) --------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ---- FoodHall ----------------------------------------------------------
    def create_food_hall(self, payload, headers):
        return self._request("POST", "/food-halls", payload, headers)

    def get_food_hall(self, food_hall_id, headers):
        return self._request("GET", f"/food-halls/{food_hall_id}", headers=headers)

    # ---- Vendor ------------------------------------------------------------
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def activate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/activate", {}, headers)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    def reinstate_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/reinstate", {}, headers)

    # ---- Stall -------------------------------------------------------------
    def create_stall(self, payload, headers):
        return self._request("POST", "/stalls", payload, headers)

    def get_stall(self, stall_id, headers):
        return self._request("GET", f"/stalls/{stall_id}", headers=headers)

    def list_stalls(self, headers, params=None):
        return self._request("GET", "/stalls", headers=headers, params=params)

    def list_stall_permits(self, stall_id, headers, params=None):
        return self._request("GET", f"/stalls/{stall_id}/permits", headers=headers, params=params)

    def list_stall_inspections(self, stall_id, headers, params=None):
        return self._request("GET", f"/stalls/{stall_id}/inspections", headers=headers, params=params)

    def get_compliance_grade(self, stall_id, method, headers):
        return self._request("GET", f"/stalls/{stall_id}/compliance-grade",
                             headers=headers, params={"method": method})

    # ---- Lease -------------------------------------------------------------
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def activate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/activate", {}, headers)

    def renew_lease(self, lease_id, new_end_date, headers):
        return self._request("POST", f"/leases/{lease_id}/renew",
                             {"new_end_date": new_end_date}, headers)

    def terminate_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/terminate", {}, headers)

    # ---- HealthPermit ------------------------------------------------------
    def create_permit(self, payload, headers):
        return self._request("POST", "/permits", payload, headers)

    def get_permit(self, permit_id, headers):
        return self._request("GET", f"/permits/{permit_id}", headers=headers)

    def issue_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/issue", {}, headers)

    def revoke_permit(self, permit_id, headers):
        return self._request("POST", f"/permits/{permit_id}/revoke", {}, headers)

    # ---- Inspection --------------------------------------------------------
    def create_inspection(self, payload, headers):
        return self._request("POST", "/inspections", payload, headers)

    def get_inspection(self, inspection_id, headers):
        return self._request("GET", f"/inspections/{inspection_id}", headers=headers)

    def conduct_inspection(self, inspection_id, score, headers):
        return self._request("POST", f"/inspections/{inspection_id}/conduct",
                             {"score": score}, headers)

    # ---- Order -------------------------------------------------------------
    def create_order(self, payload, headers):
        return self._request("POST", "/orders", payload, headers)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/orders/{order_id}", headers=headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/orders", headers=headers, params=params)

    def accept_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/accept", {}, headers)

    def fulfill_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/fulfill", {}, headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/orders/{order_id}/reject", {}, headers)

    # ---- SeatingAllocation -------------------------------------------------
    def create_seating_allocation(self, payload, headers):
        return self._request("POST", "/seating-allocations", payload, headers)

    def get_seating_allocation(self, seating_id, headers):
        return self._request("GET", f"/seating-allocations/{seating_id}", headers=headers)

    def list_seating_allocations(self, headers, params=None):
        return self._request("GET", "/seating-allocations", headers=headers, params=params)

    def release_seating_allocation(self, seating_id, headers):
        return self._request("POST", f"/seating-allocations/{seating_id}/release", {}, headers)

    # ---- MarketingEvent ----------------------------------------------------
    def create_marketing_event(self, payload, headers):
        return self._request("POST", "/marketing-events", payload, headers)

    def get_marketing_event(self, event_id, headers):
        return self._request("GET", f"/marketing-events/{event_id}", headers=headers)

    def list_marketing_events(self, headers, params=None):
        return self._request("GET", "/marketing-events", headers=headers, params=params)

    def schedule_marketing_event(self, event_id, headers):
        return self._request("POST", f"/marketing-events/{event_id}/schedule", {}, headers)

    def cancel_marketing_event(self, event_id, headers):
        return self._request("POST", f"/marketing-events/{event_id}/cancel", {}, headers)

    # ---- Settlement --------------------------------------------------------
    def create_settlement(self, payload, headers):
        return self._request("POST", "/settlements", payload, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def list_settlements(self, headers, params=None):
        return self._request("GET", "/settlements", headers=headers, params=params)

    def finalize_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/finalize", {}, headers)

    def dispute_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/dispute", {}, headers)

    def resolve_dispute_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/resolve-dispute", {}, headers)

    def void_settlement(self, settlement_id, headers):
        return self._request("POST", f"/settlements/{settlement_id}/void", {}, headers)


api_client = ApiClient()
