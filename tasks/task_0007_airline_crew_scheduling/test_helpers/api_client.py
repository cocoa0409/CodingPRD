"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- CrewMembers ----
    def create_crew_member(self, payload, headers):
        return self._request("POST", "/crew-members", payload, headers)

    def get_crew_member(self, crew_member_id, headers):
        return self._request(
            "GET", f"/crew-members/{crew_member_id}", headers=headers
        )

    def list_crew_members(self, headers, params=None):
        return self._request("GET", "/crew-members", headers=headers, params=params)

    # ---- Pairings ----
    def create_pairing(self, payload, headers):
        return self._request("POST", "/pairings", payload, headers)

    def get_pairing(self, pairing_id, headers):
        return self._request("GET", f"/pairings/{pairing_id}", headers=headers)

    def list_pairings(self, headers, params=None):
        return self._request("GET", "/pairings", headers=headers, params=params)

    def open_pairing_bidding(self, pairing_id, headers):
        return self._request(
            "POST", f"/pairings/{pairing_id}/open-bidding", {}, headers
        )

    def close_pairing_bidding(self, pairing_id, headers):
        return self._request(
            "POST", f"/pairings/{pairing_id}/close-bidding", {}, headers
        )

    def award_pairing(self, pairing_id, payload, headers):
        return self._request(
            "POST", f"/pairings/{pairing_id}/award", payload, headers
        )

    def complete_pairing(self, pairing_id, headers):
        return self._request(
            "POST", f"/pairings/{pairing_id}/complete", {}, headers
        )

    def cancel_pairing(self, pairing_id, headers):
        return self._request(
            "POST", f"/pairings/{pairing_id}/cancel", {}, headers
        )

    # ---- FlightLegs ----
    def create_flight_leg(self, pairing_id, payload, headers):
        return self._request(
            "POST", f"/pairings/{pairing_id}/flight-legs", payload, headers
        )

    def list_flight_legs(self, pairing_id, headers, params=None):
        return self._request(
            "GET",
            f"/pairings/{pairing_id}/flight-legs",
            headers=headers,
            params=params,
        )

    # ---- Bids ----
    def create_bid(self, payload, headers):
        return self._request("POST", "/bids", payload, headers)

    def list_bids(self, headers, params=None):
        return self._request("GET", "/bids", headers=headers, params=params)

    def get_bid(self, bid_id, headers):
        return self._request("GET", f"/bids/{bid_id}", headers=headers)

    def withdraw_bid(self, bid_id, headers):
        return self._request(
            "POST", f"/bids/{bid_id}/withdraw", {}, headers
        )

    # ---- Assignments ----
    def list_assignments(self, headers, params=None):
        return self._request(
            "GET", "/assignments", headers=headers, params=params
        )

    def get_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/assignments/{assignment_id}", headers=headers
        )

    def confirm_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/assignments/{assignment_id}/confirm", {}, headers
        )

    # ---- SickCalls ----
    def create_sick_call(self, payload, headers):
        return self._request("POST", "/sick-calls", payload, headers)

    def list_sick_calls(self, headers, params=None):
        return self._request("GET", "/sick-calls", headers=headers, params=params)

    def get_sick_call(self, sick_call_id, headers):
        return self._request(
            "GET", f"/sick-calls/{sick_call_id}", headers=headers
        )

    def acknowledge_sick_call(self, sick_call_id, headers):
        return self._request(
            "POST", f"/sick-calls/{sick_call_id}/acknowledge", {}, headers
        )

    # ---- ReserveCallups ----
    def list_reserve_callups(self, headers, params=None):
        return self._request(
            "GET", "/reserve-callups", headers=headers, params=params
        )

    def get_reserve_callup(self, callup_id, headers):
        return self._request(
            "GET", f"/reserve-callups/{callup_id}", headers=headers
        )

    def accept_reserve_callup(self, callup_id, headers):
        return self._request(
            "POST", f"/reserve-callups/{callup_id}/accept", {}, headers
        )

    def decline_reserve_callup(self, callup_id, headers):
        return self._request(
            "POST", f"/reserve-callups/{callup_id}/decline", {}, headers
        )

    # ---- TripTrades ----
    def create_trip_trade(self, payload, headers):
        return self._request("POST", "/trip-trades", payload, headers)

    def list_trip_trades(self, headers, params=None):
        return self._request(
            "GET", "/trip-trades", headers=headers, params=params
        )

    def get_trip_trade(self, trade_id, headers):
        return self._request(
            "GET", f"/trip-trades/{trade_id}", headers=headers
        )

    def countersign_trip_trade(self, trade_id, headers):
        return self._request(
            "POST", f"/trip-trades/{trade_id}/countersign", {}, headers
        )

    def reject_trip_trade(self, trade_id, payload, headers):
        return self._request(
            "POST", f"/trip-trades/{trade_id}/reject", payload, headers
        )

    def withdraw_trip_trade(self, trade_id, headers):
        return self._request(
            "POST", f"/trip-trades/{trade_id}/withdraw", {}, headers
        )

    def approve_trip_trade(self, trade_id, headers):
        return self._request(
            "POST", f"/trip-trades/{trade_id}/approve", {}, headers
        )

    def execute_trip_trade(self, trade_id, payload, headers):
        return self._request(
            "POST", f"/trip-trades/{trade_id}/execute", payload, headers
        )

    # ---- Test-driving clock (PRD §2.6) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
