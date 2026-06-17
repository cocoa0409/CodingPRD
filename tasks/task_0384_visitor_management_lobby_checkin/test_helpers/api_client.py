"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Site ----
    def create_site(self, payload, headers):
        return self._request("POST", "/sites", payload, headers)

    def get_site(self, site_id, headers):
        return self._request("GET", f"/sites/{site_id}", headers=headers)

    # ---- Floor ----
    def create_floor(self, payload, headers):
        return self._request("POST", "/floors", payload, headers)

    def get_floor(self, floor_id, headers):
        return self._request("GET", f"/floors/{floor_id}", headers=headers)

    def list_floors(self, headers, params=None):
        return self._request("GET", "/floors", headers=headers, params=params)

    # ---- Host ----
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def list_hosts(self, headers, params=None):
        return self._request("GET", "/hosts", headers=headers, params=params)

    # ---- WatchlistEntry ----
    def create_watchlist_entry(self, payload, headers):
        return self._request("POST", "/watchlist-entries", payload, headers)

    def get_watchlist_entry(self, entry_id, headers):
        return self._request("GET", f"/watchlist-entries/{entry_id}", headers=headers)

    def list_watchlist_entries(self, headers, params=None):
        return self._request("GET", "/watchlist-entries", headers=headers, params=params)

    # ---- MeetingRoom ----
    def create_meeting_room(self, payload, headers):
        return self._request("POST", "/meeting-rooms", payload, headers)

    def get_meeting_room(self, room_id, headers):
        return self._request("GET", f"/meeting-rooms/{room_id}", headers=headers)

    def list_meeting_rooms(self, headers, params=None):
        return self._request("GET", "/meeting-rooms", headers=headers, params=params)

    # ---- ParkingSpace ----
    def create_parking_space(self, payload, headers):
        return self._request("POST", "/parking-spaces", payload, headers)

    def get_parking_space(self, space_id, headers):
        return self._request("GET", f"/parking-spaces/{space_id}", headers=headers)

    def list_parking_spaces(self, headers, params=None):
        return self._request("GET", "/parking-spaces", headers=headers, params=params)

    # ---- ContractorPass ----
    def create_contractor_pass(self, payload, headers):
        return self._request("POST", "/contractor-passes", payload, headers)

    def get_contractor_pass(self, pass_id, headers):
        return self._request("GET", f"/contractor-passes/{pass_id}", headers=headers)

    def list_contractor_passes(self, headers, params=None):
        return self._request("GET", "/contractor-passes", headers=headers, params=params)

    def suspend_contractor_pass(self, pass_id, headers):
        return self._request("POST", f"/contractor-passes/{pass_id}/suspend", headers=headers)

    def reactivate_contractor_pass(self, pass_id, headers):
        return self._request("POST", f"/contractor-passes/{pass_id}/reactivate", headers=headers)

    def revoke_contractor_pass(self, pass_id, headers):
        return self._request("POST", f"/contractor-passes/{pass_id}/revoke", headers=headers)

    def get_contractor_pass_billing(self, pass_id, headers):
        return self._request("GET", f"/contractor-passes/{pass_id}/billing", headers=headers)

    # ---- Visit ----
    def create_visit(self, payload, headers):
        return self._request("POST", "/visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/visits", headers=headers, params=params)

    def update_visit(self, visit_id, payload, headers):
        return self._request("PATCH", f"/visits/{visit_id}", payload, headers)

    def screen_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/visits/{visit_id}/screen", payload if payload is not None else {}, headers)

    def clearance_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/clearance", payload, headers)

    def sign_in_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/visits/{visit_id}/sign-in", payload, headers)

    def sign_out_visit(self, visit_id, headers, payload=None):
        return self._request("POST", f"/visits/{visit_id}/sign-out", payload if payload is not None else {}, headers)

    # ---- Agreement ----
    def create_agreement(self, payload, headers):
        return self._request("POST", "/agreements", payload, headers)

    def get_agreement(self, agreement_id, headers):
        return self._request("GET", f"/agreements/{agreement_id}", headers=headers)

    def list_agreements(self, headers, params=None):
        return self._request("GET", "/agreements", headers=headers, params=params)

    def sign_agreement(self, agreement_id, payload, headers):
        return self._request("POST", f"/agreements/{agreement_id}/sign", payload, headers)

    # ---- DeliveryLog ----
    def create_delivery(self, payload, headers):
        return self._request("POST", "/deliveries", payload, headers)

    def get_delivery(self, delivery_id, headers):
        return self._request("GET", f"/deliveries/{delivery_id}", headers=headers)

    def list_deliveries(self, headers, params=None):
        return self._request("GET", "/deliveries", headers=headers, params=params)

    def pickup_delivery(self, delivery_id, headers, payload=None):
        return self._request("POST", f"/deliveries/{delivery_id}/pickup", payload if payload is not None else {}, headers)

    # ---- EvacuationEvent ----
    def create_evacuation_event(self, payload, headers):
        return self._request("POST", "/evacuation-events", payload, headers)

    def get_evacuation_event(self, event_id, headers):
        return self._request("GET", f"/evacuation-events/{event_id}", headers=headers)

    def list_evacuation_events(self, headers, params=None):
        return self._request("GET", "/evacuation-events", headers=headers, params=params)

    # ---- Test-driving clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set", payload, headers)


api_client = ApiClient()
