"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Hotel ----
    def create_hotel(self, payload, headers):
        return self._request("POST", "/pms/hotels", payload, headers)

    def get_hotel(self, hotel_id, headers):
        return self._request("GET", f"/pms/hotels/{hotel_id}", headers=headers)

    # ---- RoomType ----
    def create_room_type(self, payload, headers):
        return self._request("POST", "/pms/room-types", payload, headers)

    def get_room_type(self, room_type_id, headers):
        return self._request("GET", f"/pms/room-types/{room_type_id}", headers=headers)

    def list_room_types(self, headers, params=None):
        return self._request("GET", "/pms/room-types", headers=headers, params=params)

    # ---- Room ----
    def create_room(self, payload, headers):
        return self._request("POST", "/pms/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/pms/rooms/{room_id}", headers=headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/pms/rooms", headers=headers, params=params)

    def room_housekeeping(self, room_id, payload, headers):
        return self._request("POST", f"/pms/rooms/{room_id}/housekeeping", payload, headers)

    # ---- RatePlan ----
    def create_rate_plan(self, payload, headers):
        return self._request("POST", "/pms/rate-plans", payload, headers)

    def get_rate_plan(self, rate_plan_id, headers):
        return self._request("GET", f"/pms/rate-plans/{rate_plan_id}", headers=headers)

    def list_rate_plans(self, headers, params=None):
        return self._request("GET", "/pms/rate-plans", headers=headers, params=params)

    def close_rate_plan(self, rate_plan_id, payload, headers):
        return self._request("POST", f"/pms/rate-plans/{rate_plan_id}/close", payload, headers)

    # ---- CorporateAccount ----
    def create_corporate_account(self, payload, headers):
        return self._request("POST", "/pms/corporate-accounts", payload, headers)

    def get_corporate_account(self, account_id, headers):
        return self._request("GET", f"/pms/corporate-accounts/{account_id}", headers=headers)

    def list_corporate_accounts(self, headers, params=None):
        return self._request("GET", "/pms/corporate-accounts", headers=headers, params=params)

    def suspend_corporate_account(self, account_id, payload, headers):
        return self._request("POST", f"/pms/corporate-accounts/{account_id}/suspend", payload, headers)

    def reinstate_corporate_account(self, account_id, payload, headers):
        return self._request("POST", f"/pms/corporate-accounts/{account_id}/reinstate", payload, headers)

    # ---- Guest ----
    def create_guest(self, payload, headers):
        return self._request("POST", "/pms/guests", payload, headers)

    def get_guest(self, guest_id, headers):
        return self._request("GET", f"/pms/guests/{guest_id}", headers=headers)

    def list_guests(self, headers, params=None):
        return self._request("GET", "/pms/guests", headers=headers, params=params)

    # ---- GroupBlock ----
    def create_group_block(self, payload, headers):
        return self._request("POST", "/pms/group-blocks", payload, headers)

    def get_group_block(self, block_id, headers):
        return self._request("GET", f"/pms/group-blocks/{block_id}", headers=headers)

    def list_group_blocks(self, headers, params=None):
        return self._request("GET", "/pms/group-blocks", headers=headers, params=params)

    def close_group_block(self, block_id, payload, headers):
        return self._request("POST", f"/pms/group-blocks/{block_id}/close", payload, headers)

    # ---- Reservation ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/pms/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/pms/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/pms/reservations", headers=headers, params=params)

    def confirm_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/pms/reservations/{reservation_id}/confirm", payload or {}, headers)

    def assign_room(self, reservation_id, payload, headers):
        return self._request("POST", f"/pms/reservations/{reservation_id}/assign-room", payload, headers)

    def upgrade_reservation(self, reservation_id, payload, headers):
        return self._request("POST", f"/pms/reservations/{reservation_id}/upgrade", payload, headers)

    def check_in(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/pms/reservations/{reservation_id}/check-in", payload or {}, headers)

    def check_out(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/pms/reservations/{reservation_id}/check-out", payload or {}, headers)

    def cancel_reservation(self, reservation_id, headers, payload=None):
        return self._request("POST", f"/pms/reservations/{reservation_id}/cancel", payload or {}, headers)

    # ---- Folio + Incidentals ----
    def get_folio(self, folio_id, headers):
        return self._request("GET", f"/pms/folios/{folio_id}", headers=headers)

    def list_folios(self, headers, params=None):
        return self._request("GET", "/pms/folios", headers=headers, params=params)

    def dispute_folio(self, folio_id, headers, payload=None):
        return self._request("POST", f"/pms/folios/{folio_id}/dispute", payload or {}, headers)

    def resolve_folio(self, folio_id, headers, payload=None):
        return self._request("POST", f"/pms/folios/{folio_id}/resolve", payload or {}, headers)

    def create_incidental(self, payload, headers):
        return self._request("POST", "/pms/incidentals", payload, headers)

    def get_incidental(self, incidental_id, headers):
        return self._request("GET", f"/pms/incidentals/{incidental_id}", headers=headers)

    def list_incidentals(self, headers, params=None):
        return self._request("GET", "/pms/incidentals", headers=headers, params=params)

    def void_incidental(self, incidental_id, payload, headers):
        return self._request("POST", f"/pms/incidentals/{incidental_id}/void", payload, headers)

    # ---- Night audit ----
    def create_night_audit_run(self, payload, headers):
        return self._request("POST", "/pms/night-audit-runs", payload, headers)

    def get_night_audit_run(self, run_id, headers):
        return self._request("GET", f"/pms/night-audit-runs/{run_id}", headers=headers)

    def list_night_audit_runs(self, headers, params=None):
        return self._request("GET", "/pms/night-audit-runs", headers=headers, params=params)

    def complete_night_audit_run(self, run_id, payload, headers):
        return self._request("POST", f"/pms/night-audit-runs/{run_id}/complete", payload, headers)

    def abort_night_audit_run(self, run_id, payload, headers):
        return self._request("POST", f"/pms/night-audit-runs/{run_id}/abort", payload, headers)

    # ---- Availability read ----
    def get_availability(self, headers, params=None):
        return self._request("GET", "/pms/availability", headers=headers, params=params)


api_client = ApiClient()
