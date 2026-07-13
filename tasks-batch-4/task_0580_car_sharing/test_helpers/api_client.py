"""API client: one method per endpoint defined in the Car Sharing PRD §4.

Subclasses the framework GenericApiClient; the base _request() is inherited.
All money is integer cents; dates are YYYY-MM-DD; the logical clock is an
admin-only test-driving capability (PRD §2.6).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------- Hosts
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def suspend_host(self, host_id, headers):
        return self._request("POST", f"/hosts/{host_id}/suspend", {}, headers)

    def reinstate_host(self, host_id, headers):
        return self._request("POST", f"/hosts/{host_id}/reinstate", {}, headers)

    # ------------------------------------------------------------- Guests
    def create_guest(self, payload, headers):
        return self._request("POST", "/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/guests/{guest_id}", headers=headers)

    def submit_verification(self, guest_id, payload, headers):
        return self._request("POST", f"/guests/{guest_id}/submit-verification", payload, headers)

    def verify_guest(self, guest_id, headers):
        return self._request("POST", f"/guests/{guest_id}/verify", {}, headers)

    def reject_guest(self, guest_id, payload, headers):
        return self._request("POST", f"/guests/{guest_id}/reject", payload, headers)

    # -------------------------------------------------- Protection plans
    def create_plan(self, payload, headers):
        return self._request("POST", "/protection-plans", payload, headers)

    def get_plan(self, plan_id, headers):
        return self._request("GET", f"/protection-plans/{plan_id}", headers=headers)

    def list_plans(self, headers, params=None):
        return self._request("GET", "/protection-plans", headers=headers, params=params)

    # ----------------------------------------------------------- Vehicles
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def update_vehicle(self, vehicle_id, payload, headers):
        return self._request("PUT", f"/vehicles/{vehicle_id}", payload, headers)

    def list_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/list", {}, headers)

    def snooze_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/snooze", {}, headers)

    def unlist_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/unlist", {}, headers)

    # ------------------------------------------------ Availability blocks
    def create_availability_block(self, vehicle_id, payload, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/availability-blocks", payload, headers)

    def get_availability_block(self, block_id, headers):
        return self._request("GET", f"/availability-blocks/{block_id}", headers=headers)

    def list_availability_blocks(self, headers, params=None):
        return self._request("GET", "/availability-blocks", headers=headers, params=params)

    # ------------------------------------------------------- Pricing rules
    def create_pricing_rule(self, payload, headers):
        return self._request("POST", "/pricing-rules", payload, headers)

    def get_pricing_rule(self, rule_id, headers):
        return self._request("GET", f"/pricing-rules/{rule_id}", headers=headers)

    def list_pricing_rules(self, headers, params=None):
        return self._request("GET", "/pricing-rules", headers=headers, params=params)

    # -------------------------------------------------------------- Trips
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def approve_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/approve", {}, headers)

    def decline_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/decline", {}, headers)

    def cancel_trip(self, trip_id, headers, payload=None):
        return self._request("POST", f"/trips/{trip_id}/cancel", payload or {}, headers)

    def checkin_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/check-in", payload, headers)

    def checkout_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/check-out", payload, headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/complete", {}, headers)

    def list_inspections(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}/inspections", headers=headers)

    # --------------------------------------------------------- Extensions
    def create_extension(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/extensions", payload, headers)

    def approve_extension(self, extension_id, headers):
        return self._request("POST", f"/extensions/{extension_id}/approve", {}, headers)

    def deny_extension(self, extension_id, headers):
        return self._request("POST", f"/extensions/{extension_id}/deny", {}, headers)

    def get_extension(self, extension_id, headers):
        return self._request("GET", f"/extensions/{extension_id}", headers=headers)

    def list_extensions(self, headers, params=None):
        return self._request("GET", "/extensions", headers=headers, params=params)

    # ------------------------------------------------------------- Claims
    def create_claim(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/claims", payload, headers)

    def start_review_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/start-review", {}, headers)

    def request_info_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/request-info", {}, headers)

    def provide_info_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/provide-info", payload or {}, headers)

    def approve_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/approve", payload or {}, headers)

    def deny_claim(self, claim_id, headers, payload=None):
        return self._request("POST", f"/claims/{claim_id}/deny", payload or {}, headers)

    def settle_claim(self, claim_id, headers):
        return self._request("POST", f"/claims/{claim_id}/settle", {}, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    # ------------------------------------------------------------ Payouts
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def mark_paid_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/mark-paid", {}, headers)

    def mark_failed_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"/payouts/{payout_id}/mark-failed", payload or {}, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    # ------------------------------------------------------ Logical clock
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
