"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- EmployerProgram ----
    def create_employer_program(self, payload, headers):
        return self._request("POST", "/employer-programs", payload, headers)

    def get_employer_program(self, program_id, headers):
        return self._request("GET", f"/employer-programs/{program_id}", headers=headers)

    def freeze_employer_program(self, program_id, headers):
        return self._request("POST", f"/employer-programs/{program_id}/freeze", {}, headers)

    def unfreeze_employer_program(self, program_id, headers):
        return self._request("POST", f"/employer-programs/{program_id}/unfreeze", {}, headers)

    def list_program_ledger(self, program_id, headers, params=None):
        return self._request("GET", f"/employer-programs/{program_id}/ledger", headers=headers, params=params)

    # ---- Member ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member_reliability(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/reliability", headers=headers, params=params)

    def adjust_member_wallet(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/wallet/adjustments", payload, headers)

    # ---- Vehicle ----
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    # ---- Pool ----
    def create_pool(self, payload, headers):
        return self._request("POST", "/pools", payload, headers)

    def get_pool(self, pool_id, headers):
        return self._request("GET", f"/pools/{pool_id}", headers=headers)

    def list_pools(self, headers, params=None):
        return self._request("GET", "/pools", headers=headers, params=params)

    def activate_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/activate", {}, headers)

    def suspend_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/suspend", {}, headers)

    def close_pool(self, pool_id, headers):
        return self._request("POST", f"/pools/{pool_id}/close", {}, headers)

    # ---- MatchRequest ----
    def create_match_request(self, payload, headers):
        return self._request("POST", "/match-requests", payload, headers)

    def get_match_request(self, mr_id, headers):
        return self._request("GET", f"/match-requests/{mr_id}", headers=headers)

    def list_match_requests(self, headers, params=None):
        return self._request("GET", "/match-requests", headers=headers, params=params)

    def match_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/match", {}, headers)

    def reject_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/reject", {}, headers)

    def confirm_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/confirm", {}, headers)

    def cancel_match_request(self, mr_id, headers):
        return self._request("POST", f"/match-requests/{mr_id}/cancel", {}, headers)

    # ---- Membership ----
    def create_membership(self, payload, headers):
        return self._request("POST", "/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def end_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/end", {}, headers)

    # ---- Trip ----
    def create_trip(self, payload, headers):
        return self._request("POST", "/trips", payload, headers)

    def get_trip(self, trip_id, headers):
        return self._request("GET", f"/trips/{trip_id}", headers=headers)

    def list_trips(self, headers, params=None):
        return self._request("GET", "/trips", headers=headers, params=params)

    def open_boarding_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/open-boarding", {}, headers)

    def depart_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/depart", {}, headers)

    def complete_trip(self, trip_id, payload, headers):
        return self._request("POST", f"/trips/{trip_id}/complete", payload, headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/trips/{trip_id}/cancel", {}, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", {}, headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/no-show", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    # ---- GuaranteedRideHome ----
    def create_grh_claim(self, payload, headers):
        return self._request("POST", "/grh-claims", payload, headers)

    def get_grh_claim(self, grh_id, headers):
        return self._request("GET", f"/grh-claims/{grh_id}", headers=headers)

    def list_grh_claims(self, headers, params=None):
        return self._request("GET", "/grh-claims", headers=headers, params=params)

    def approve_grh_claim(self, grh_id, headers):
        return self._request("POST", f"/grh-claims/{grh_id}/approve", {}, headers)

    def reimburse_grh_claim(self, grh_id, headers):
        return self._request("POST", f"/grh-claims/{grh_id}/reimburse", {}, headers)

    def deny_grh_claim(self, grh_id, payload, headers):
        return self._request("POST", f"/grh-claims/{grh_id}/deny", payload, headers)

    # ---- ReliabilityEvent (read) ----
    def get_reliability_event(self, event_id, headers):
        return self._request("GET", f"/reliability-events/{event_id}", headers=headers)

    def list_reliability_events(self, headers, params=None):
        return self._request("GET", "/reliability-events", headers=headers, params=params)

    # ---- SubsidyLedgerEntry (read) ----
    def get_subsidy_ledger_entry(self, entry_id, headers):
        return self._request("GET", f"/subsidy-ledger-entries/{entry_id}", headers=headers)

    def list_subsidy_ledger_entries(self, headers, params=None):
        return self._request("GET", "/subsidy-ledger-entries", headers=headers, params=params)

    # ---- Test-driving / operational ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)

    def run_batch(self, headers):
        return self._request("POST", "/_batch/run", {}, headers)

    def healthz(self, headers=None):
        return self._request("GET", "/healthz", headers=headers)


api_client = ApiClient()
