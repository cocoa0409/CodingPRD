"""API client: one method per endpoint defined in the PRD (Section 4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Test-driving capabilities (PRD 3.10) ----
    def set_clock(self, now_utc, headers):
        return self._request("POST", "/_clock/set", {"now_utc": now_utc}, headers)

    def seed_county_distance(self, county_a, county_b, miles, headers):
        return self._request(
            "POST", "/_geo/county_distance",
            {"county_a": county_a, "county_b": county_b, "miles": miles}, headers,
        )

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def recompute_eligibility(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/eligibility/recompute", {}, headers)

    def terminate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/terminate", {}, headers)

    def list_member_eligibility_spans(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/eligibility-spans", headers=headers, params=params)

    def list_member_trips(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/trips", headers=headers, params=params)

    def list_member_standing_orders(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/standing-orders", headers=headers, params=params)

    # ---- EligibilitySpan ----
    def create_eligibility_span(self, payload, headers):
        return self._request("POST", "/eligibility-spans", payload, headers)

    def void_eligibility_span(self, span_id, headers):
        return self._request("POST", f"/eligibility-spans/{span_id}/void", {}, headers)

    # ---- Broker ----
    def create_broker(self, payload, headers):
        return self._request("POST", "/brokers", payload, headers)

    def get_broker(self, broker_id, headers):
        return self._request("GET", f"/brokers/{broker_id}", headers=headers)

    def suspend_broker(self, broker_id, headers):
        return self._request("POST", f"/brokers/{broker_id}/suspend", {}, headers)

    def reinstate_broker(self, broker_id, headers):
        return self._request("POST", f"/brokers/{broker_id}/reinstate", {}, headers)

    def list_broker_drivers(self, broker_id, headers, params=None):
        return self._request("GET", f"/brokers/{broker_id}/drivers", headers=headers, params=params)

    # ---- Driver ----
    def create_driver(self, payload, headers):
        return self._request("POST", "/drivers", payload, headers)

    def get_driver(self, driver_id, headers):
        return self._request("GET", f"/drivers/{driver_id}", headers=headers)

    def driver_offline(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/offline", {}, headers)

    def driver_online(self, driver_id, headers):
        return self._request("POST", f"/drivers/{driver_id}/online", {}, headers)

    # ---- RateSchedule ----
    def create_rate_schedule(self, payload, headers):
        return self._request("POST", "/rate-schedules", payload, headers)

    def get_rate_schedule(self, rate_id, headers):
        return self._request("GET", f"/rate-schedules/{rate_id}", headers=headers)

    # ---- TripRequest ----
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def schedule_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/schedule", {}, headers)

    def assign_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/assign", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", {}, headers)

    def reconcile_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/reconcile", {}, headers)

    def reconcile_override_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/reconcile/override", {}, headers)

    def list_trip_legs(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/legs", headers=headers, params=params)

    def list_trip_assignments(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/assignments", headers=headers, params=params)

    def list_trip_claims(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/claims", headers=headers, params=params)

    def list_trip_encounters(self, trip_id, headers, params=None):
        return self._request("GET", f"/trips/{trip_id}/encounters", headers=headers, params=params)

    # ---- Assignment ----
    def get_assignment(self, assignment_id, headers):
        return self._request("GET", f"/assignments/{assignment_id}", headers=headers)

    def list_assignments(self, headers, params=None):
        return self._request("GET", "/assignments", headers=headers, params=params)

    # ---- Leg ----
    def get_leg(self, leg_id, headers):
        return self._request("GET", f"/legs/{leg_id}", headers=headers)

    def leg_ready(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/ready", {}, headers)

    def leg_cancel_ready(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/cancel-ready", {}, headers)

    def leg_depart(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/depart", {}, headers)

    def leg_arrive(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/arrive", {}, headers)

    def leg_pickup(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/pickup", {}, headers)

    def leg_dropoff(self, leg_id, odometer_loaded_miles, headers):
        return self._request(
            "POST", f"/legs/{leg_id}/dropoff",
            {"odometer_loaded_miles": odometer_loaded_miles}, headers,
        )

    def leg_dropoff_raw(self, leg_id, payload, headers):
        """Drop-off with an arbitrary body (for required-field / malformed tests)."""
        return self._request("POST", f"/legs/{leg_id}/dropoff", payload, headers)

    def leg_no_show(self, leg_id, headers):
        return self._request("POST", f"/legs/{leg_id}/no-show", {}, headers)

    # ---- StandingOrder ----
    def create_standing_order(self, payload, headers):
        return self._request("POST", "/standing-orders", payload, headers)

    def get_standing_order(self, so_id, headers):
        return self._request("GET", f"/standing-orders/{so_id}", headers=headers)

    def generate_standing_order(self, so_id, payload, headers):
        return self._request("POST", f"/standing-orders/{so_id}/generate", payload, headers)

    def pause_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/pause", {}, headers)

    def resume_standing_order(self, so_id, headers):
        return self._request("POST", f"/standing-orders/{so_id}/resume", {}, headers)

    # ---- Claim / Encounter ----
    def create_claim(self, payload, headers):
        return self._request("POST", "/claims", payload, headers)

    def get_claim(self, claim_id, headers):
        return self._request("GET", f"/claims/{claim_id}", headers=headers)

    def list_claims(self, headers, params=None):
        return self._request("GET", "/claims", headers=headers, params=params)

    def create_encounter(self, payload, headers):
        return self._request("POST", "/encounters", payload, headers)

    def get_encounter(self, encounter_id, headers):
        return self._request("GET", f"/encounters/{encounter_id}", headers=headers)


api_client = ApiClient()
