"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----- Members -----
    def register_member(self, payload, headers):
        return self._request("POST", "/members/register", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def sign_waiver(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/sign-waiver", payload, headers)

    def expire_waiver(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/expire-waiver", {}, headers)

    def complete_training(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/complete-training", payload, headers)

    def list_member_reservations(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/reservations", headers=headers, params=params)

    # ----- Guides -----
    def create_guide(self, payload, headers):
        return self._request("POST", "/guides", payload, headers)

    def get_guide(self, guide_id, headers):
        return self._request("GET", f"/guides/{guide_id}", headers=headers)

    def list_guide_assignments(self, guide_id, headers, params=None):
        return self._request("GET", f"/guides/{guide_id}/assignments", headers=headers, params=params)

    # ----- Trails -----
    def create_trail(self, payload, headers):
        return self._request("POST", "/trails", payload, headers)

    def get_trail(self, trail_id, headers):
        return self._request("GET", f"/trails/{trail_id}", headers=headers)

    def post_closure(self, trail_id, payload, headers):
        return self._request("POST", f"/trails/{trail_id}/closure", payload, headers)

    def list_trail_closures(self, trail_id, headers, params=None):
        return self._request("GET", f"/trails/{trail_id}/closures", headers=headers, params=params)

    def list_trail_departures(self, trail_id, headers, params=None):
        return self._request("GET", f"/trails/{trail_id}/tour-departures", headers=headers, params=params)

    # ----- Units -----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def maintenance_unit(self, unit_id, payload, headers):
        return self._request("POST", f"/units/{unit_id}/maintenance", payload, headers)

    # ----- Gear -----
    def create_gear_item(self, payload, headers):
        return self._request("POST", "/gear-items", payload, headers)

    def get_gear_item(self, gear_id, headers):
        return self._request("GET", f"/gear-items/{gear_id}", headers=headers)

    # ----- Tour Departures -----
    def create_departure(self, payload, headers):
        return self._request("POST", "/tour-departures", payload, headers)

    def get_departure(self, departure_id, headers):
        return self._request("GET", f"/tour-departures/{departure_id}", headers=headers)

    def list_departure_reservations(self, departure_id, headers, params=None):
        return self._request("GET", f"/tour-departures/{departure_id}/reservations", headers=headers, params=params)

    def list_departure_guide_assignments(self, departure_id, headers, params=None):
        return self._request("GET", f"/tour-departures/{departure_id}/guide-assignments", headers=headers, params=params)

    def assign_guide(self, departure_id, payload, headers):
        return self._request("POST", f"/tour-departures/{departure_id}/assign-guide", payload, headers)

    def unassign_guide(self, departure_id, payload, headers):
        return self._request("POST", f"/tour-departures/{departure_id}/unassign-guide", payload, headers)

    def lock_departure(self, departure_id, headers):
        return self._request("POST", f"/tour-departures/{departure_id}/lock", {}, headers)

    def depart_departure(self, departure_id, headers):
        return self._request("POST", f"/tour-departures/{departure_id}/depart", {}, headers)

    def complete_departure(self, departure_id, headers):
        return self._request("POST", f"/tour-departures/{departure_id}/complete", {}, headers)

    def cancel_departure(self, departure_id, headers):
        return self._request("POST", f"/tour-departures/{departure_id}/cancel", {}, headers)

    # ----- Reservations -----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/confirm", payload, headers)

    def check_out_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-out", {}, headers)

    def return_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/reservations/{reservation_id}/return", payload, headers)

    def no_show_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/no-show", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    def get_settlement(self, settlement_id, headers):
        return self._request("GET", f"/settlements/{settlement_id}", headers=headers)

    def get_reservation_settlement(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}/settlement", headers=headers)

    # ----- Test-driving -----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
