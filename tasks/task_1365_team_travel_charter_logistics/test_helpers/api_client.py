"""API client: one method per endpoint defined in the PRD (§4 Endpoint Definitions).

All endpoints are mounted under the /travel prefix (PRD §4).
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (PRD §2.8)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/travel/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Teams (PRD §3.1)
    # ------------------------------------------------------------------
    def create_team(self, payload, headers):
        return self._request("POST", "/travel/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/travel/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/travel/teams", headers=headers, params=params)

    # ------------------------------------------------------------------
    # Seasons (PRD §3.1)
    # ------------------------------------------------------------------
    def create_season(self, team_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/seasons", payload, headers)

    def list_seasons(self, team_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/seasons",
                             headers=headers, params=params)

    def get_season(self, team_id, season_id, headers):
        return self._request("GET", f"/travel/teams/{team_id}/seasons/{season_id}",
                             headers=headers)

    def close_season(self, team_id, season_id, headers):
        return self._request("POST", f"/travel/teams/{team_id}/seasons/{season_id}/close",
                             {}, headers)

    # ------------------------------------------------------------------
    # Trips (PRD §3.2, §3.9)
    # ------------------------------------------------------------------
    def create_trip(self, team_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips", payload, headers)

    def list_trips(self, team_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/trips",
                             headers=headers, params=params)

    def get_trip(self, team_id, trip_id, headers):
        return self._request("GET", f"/travel/teams/{team_id}/trips/{trip_id}",
                             headers=headers)

    def lock_trip(self, team_id, trip_id, expected_trip_version, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/lock",
                             {"expected_trip_version": expected_trip_version}, headers)

    def close_trip(self, team_id, trip_id, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/close",
                             {}, headers)

    def cancel_trip(self, team_id, trip_id, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/cancel",
                             {}, headers)

    # ------------------------------------------------------------------
    # Travel party members (PRD §3.2)
    # ------------------------------------------------------------------
    def add_member(self, team_id, trip_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/members",
                             payload, headers)

    def get_member(self, team_id, trip_id, member_id, headers):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}",
            headers=headers)

    def list_members(self, team_id, trip_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/trips/{trip_id}/members",
                             headers=headers, params=params)

    def scratch_member(self, team_id, trip_id, member_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/scratch",
            {}, headers)

    # ------------------------------------------------------------------
    # Charter contracts (PRD §3.3)
    # ------------------------------------------------------------------
    def create_charter_contract(self, team_id, trip_id, payload, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts",
            payload, headers)

    def list_charter_contracts(self, team_id, trip_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts",
            headers=headers, params=params)

    def get_charter_contract(self, team_id, trip_id, contract_id, headers):
        return self._request(
            "GET",
            f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts/{contract_id}",
            headers=headers)

    def submit_contract(self, team_id, trip_id, contract_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts/{contract_id}/submit",
            {}, headers)

    def countersign_contract(self, team_id, trip_id, contract_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts/{contract_id}/countersign",
            {}, headers)

    def execute_contract(self, team_id, trip_id, contract_id, expected_contract_version, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts/{contract_id}/execute",
            {"expected_contract_version": expected_contract_version}, headers)

    def cancel_contract(self, team_id, trip_id, contract_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts/{contract_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Flight legs (PRD §3.4)
    # ------------------------------------------------------------------
    def create_flight_leg(self, team_id, trip_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs",
                             payload, headers)

    def get_flight_leg(self, team_id, trip_id, leg_id, headers):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}",
            headers=headers)

    def list_flight_legs(self, team_id, trip_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs",
                             headers=headers, params=params)

    def list_contract_flight_legs(self, team_id, trip_id, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts/{contract_id}/flight-legs",
            headers=headers, params=params)

    def book_leg(self, team_id, trip_id, leg_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/book",
            {}, headers)

    def delay_leg(self, team_id, trip_id, leg_id, delay_minutes, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/delay",
            {"delay_minutes": delay_minutes}, headers)

    def rebook_leg(self, team_id, trip_id, leg_id, scheduled_depart_utc, scheduled_arrive_utc,
                   headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/rebook",
            {"scheduled_depart_utc": scheduled_depart_utc,
             "scheduled_arrive_utc": scheduled_arrive_utc}, headers)

    def depart_leg(self, team_id, trip_id, leg_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/depart",
            {}, headers)

    def arrive_leg(self, team_id, trip_id, leg_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/arrive",
            {}, headers)

    def cancel_leg(self, team_id, trip_id, leg_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Manifest entries (PRD §3.5)
    # ------------------------------------------------------------------
    def add_manifest_entry(self, team_id, trip_id, leg_id, payload, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/manifest",
            payload, headers)

    def list_manifest_entries(self, team_id, trip_id, leg_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/manifest",
            headers=headers, params=params)

    def list_member_manifest_entries(self, team_id, trip_id, member_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/manifest",
            headers=headers, params=params)

    def get_manifest_entry(self, team_id, trip_id, leg_id, entry_id, headers):
        return self._request(
            "GET",
            f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/manifest/{entry_id}",
            headers=headers)

    def confirm_manifest_entry(self, team_id, trip_id, leg_id, entry_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/manifest/{entry_id}/confirm",
            {}, headers)

    def bump_manifest_entry(self, team_id, trip_id, leg_id, entry_id, bump_reason, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/manifest/{entry_id}/bump",
            {"bump_reason": bump_reason}, headers)

    # ------------------------------------------------------------------
    # Hotel blocks (PRD §3.6)
    # ------------------------------------------------------------------
    def create_hotel_block(self, team_id, trip_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks",
                             payload, headers)

    def list_hotel_blocks(self, team_id, trip_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks",
                             headers=headers, params=params)

    def get_hotel_block(self, team_id, trip_id, block_id, headers):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}",
            headers=headers)

    def lock_hotel_block(self, team_id, trip_id, block_id, expected_block_version, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/lock",
            {"expected_block_version": expected_block_version}, headers)

    def release_hotel_block(self, team_id, trip_id, block_id, rooms_to_release, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/release",
            {"rooms_to_release": rooms_to_release}, headers)

    # ------------------------------------------------------------------
    # Room assignments (PRD §3.6)
    # ------------------------------------------------------------------
    def create_room_assignment(self, team_id, trip_id, block_id, payload, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/rooms",
            payload, headers)

    def list_room_assignments(self, team_id, trip_id, block_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/rooms",
            headers=headers, params=params)

    def list_member_room_assignments(self, team_id, trip_id, member_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/rooms",
            headers=headers, params=params)

    def get_room_assignment(self, team_id, trip_id, block_id, room_id, headers):
        return self._request(
            "GET",
            f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/rooms/{room_id}",
            headers=headers)

    def confirm_room_assignment(self, team_id, trip_id, block_id, room_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/rooms/{room_id}/confirm",
            {}, headers)

    def checkin_room(self, team_id, trip_id, block_id, room_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/rooms/{room_id}/checkin",
            {}, headers)

    def checkout_room(self, team_id, trip_id, block_id, room_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/rooms/{room_id}/checkout",
            {}, headers)

    def cancel_room_assignment(self, team_id, trip_id, block_id, room_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/hotel-blocks/{block_id}/rooms/{room_id}/cancel",
            {}, headers)

    # ------------------------------------------------------------------
    # Per-diem ledgers (PRD §3.8)
    # ------------------------------------------------------------------
    def create_per_diem(self, team_id, trip_id, member_id, payload, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/per-diem",
            payload, headers)

    def list_per_diem(self, team_id, trip_id, member_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/per-diem",
            headers=headers, params=params)

    def get_per_diem(self, team_id, trip_id, member_id, ledger_id, headers):
        return self._request(
            "GET",
            f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/per-diem/{ledger_id}",
            headers=headers)

    def approve_per_diem(self, team_id, trip_id, member_id, ledger_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/per-diem/{ledger_id}/approve",
            {}, headers)

    def pay_per_diem(self, team_id, trip_id, member_id, ledger_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/per-diem/{ledger_id}/pay",
            {}, headers)

    def dispute_per_diem(self, team_id, trip_id, member_id, ledger_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/per-diem/{ledger_id}/dispute",
            {}, headers)

    def resolve_per_diem(self, team_id, trip_id, member_id, ledger_id, meals_provided_count,
                         headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/per-diem/{ledger_id}/resolve",
            {"meals_provided_count": meals_provided_count}, headers)

    # ------------------------------------------------------------------
    # Equipment shipments (PRD §3.7)
    # ------------------------------------------------------------------
    def create_equipment(self, team_id, trip_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/equipment",
                             payload, headers)

    def list_equipment(self, team_id, trip_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/trips/{trip_id}/equipment",
                             headers=headers, params=params)

    def list_contract_equipment(self, team_id, trip_id, contract_id, headers, params=None):
        return self._request(
            "GET",
            f"/travel/teams/{team_id}/trips/{trip_id}/charter-contracts/{contract_id}/equipment",
            headers=headers, params=params)

    def get_equipment(self, team_id, trip_id, shipment_id, headers):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/equipment/{shipment_id}",
            headers=headers)

    def load_equipment(self, team_id, trip_id, shipment_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/equipment/{shipment_id}/load",
            {}, headers)

    def deliver_equipment(self, team_id, trip_id, shipment_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/equipment/{shipment_id}/deliver",
            {}, headers)

    def mark_lost_equipment(self, team_id, trip_id, shipment_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/equipment/{shipment_id}/mark-lost",
            {}, headers)

    # ------------------------------------------------------------------
    # Contingency events (PRD §3.9)
    # ------------------------------------------------------------------
    def create_contingency(self, team_id, trip_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/contingencies",
                             payload, headers)

    def list_contingencies(self, team_id, trip_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/trips/{trip_id}/contingencies",
                             headers=headers, params=params)

    def list_leg_contingencies(self, team_id, trip_id, leg_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/flight-legs/{leg_id}/contingencies",
            headers=headers, params=params)

    def get_contingency(self, team_id, trip_id, event_id, headers):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/contingencies/{event_id}",
            headers=headers)

    def mitigate_contingency(self, team_id, trip_id, event_id, resolution_action, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/contingencies/{event_id}/mitigate",
            {"resolution_action": resolution_action}, headers)

    def resolve_contingency(self, team_id, trip_id, event_id, recovery_cost_cents, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/contingencies/{event_id}/resolve",
            {"recovery_cost_cents": recovery_cost_cents}, headers)

    def close_noop_contingency(self, team_id, trip_id, event_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/contingencies/{event_id}/close-noop",
            {}, headers)

    # ------------------------------------------------------------------
    # Credential requests (PRD §3.10)
    # ------------------------------------------------------------------
    def create_credential(self, team_id, trip_id, payload, headers):
        return self._request("POST", f"/travel/teams/{team_id}/trips/{trip_id}/credentials",
                             payload, headers)

    def list_credentials(self, team_id, trip_id, headers, params=None):
        return self._request("GET", f"/travel/teams/{team_id}/trips/{trip_id}/credentials",
                             headers=headers, params=params)

    def list_member_credentials(self, team_id, trip_id, member_id, headers, params=None):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/members/{member_id}/credentials",
            headers=headers, params=params)

    def get_credential(self, team_id, trip_id, cred_id, headers):
        return self._request(
            "GET", f"/travel/teams/{team_id}/trips/{trip_id}/credentials/{cred_id}",
            headers=headers)

    def security_review_credential(self, team_id, trip_id, cred_id, headers):
        return self._request(
            "POST",
            f"/travel/teams/{team_id}/trips/{trip_id}/credentials/{cred_id}/security-review",
            {}, headers)

    def approve_credential(self, team_id, trip_id, cred_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/credentials/{cred_id}/approve",
            {}, headers)

    def deny_credential(self, team_id, trip_id, cred_id, denial_reason, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/credentials/{cred_id}/deny",
            {"denial_reason": denial_reason}, headers)

    def revoke_credential(self, team_id, trip_id, cred_id, headers):
        return self._request(
            "POST", f"/travel/teams/{team_id}/trips/{trip_id}/credentials/{cred_id}/revoke",
            {}, headers)

    # ------------------------------------------------------------------
    # Flat accessors (PRD §2.5, §4)
    # ------------------------------------------------------------------
    def get_season_flat(self, season_id, headers):
        return self._request("GET", f"/travel/seasons/{season_id}", headers=headers)

    def list_seasons_flat(self, headers, params=None):
        return self._request("GET", "/travel/seasons", headers=headers, params=params)

    def get_trip_flat(self, trip_id, headers):
        return self._request("GET", f"/travel/trips/{trip_id}", headers=headers)

    def list_trips_flat(self, headers, params=None):
        return self._request("GET", "/travel/trips", headers=headers, params=params)

    def get_member_flat(self, member_id, headers):
        return self._request("GET", f"/travel/members/{member_id}", headers=headers)

    def list_members_flat(self, headers, params=None):
        return self._request("GET", "/travel/members", headers=headers, params=params)

    def get_charter_contract_flat(self, contract_id, headers):
        return self._request("GET", f"/travel/charter-contracts/{contract_id}", headers=headers)

    def list_charter_contracts_flat(self, headers, params=None):
        return self._request("GET", "/travel/charter-contracts", headers=headers, params=params)

    def get_flight_leg_flat(self, leg_id, headers):
        return self._request("GET", f"/travel/flight-legs/{leg_id}", headers=headers)

    def list_flight_legs_flat(self, headers, params=None):
        return self._request("GET", "/travel/flight-legs", headers=headers, params=params)

    def get_manifest_entry_flat(self, entry_id, headers):
        return self._request("GET", f"/travel/manifest-entries/{entry_id}", headers=headers)

    def list_manifest_entries_flat(self, headers, params=None):
        return self._request("GET", "/travel/manifest-entries", headers=headers, params=params)

    def get_hotel_block_flat(self, block_id, headers):
        return self._request("GET", f"/travel/hotel-blocks/{block_id}", headers=headers)

    def list_hotel_blocks_flat(self, headers, params=None):
        return self._request("GET", "/travel/hotel-blocks", headers=headers, params=params)

    def get_room_flat(self, room_id, headers):
        return self._request("GET", f"/travel/rooms/{room_id}", headers=headers)

    def list_rooms_flat(self, headers, params=None):
        return self._request("GET", "/travel/rooms", headers=headers, params=params)

    def get_per_diem_flat(self, ledger_id, headers):
        return self._request("GET", f"/travel/per-diem/{ledger_id}", headers=headers)

    def list_per_diem_flat(self, headers, params=None):
        return self._request("GET", "/travel/per-diem", headers=headers, params=params)

    def get_equipment_flat(self, shipment_id, headers):
        return self._request("GET", f"/travel/equipment/{shipment_id}", headers=headers)

    def list_equipment_flat(self, headers, params=None):
        return self._request("GET", "/travel/equipment", headers=headers, params=params)

    def get_contingency_flat(self, event_id, headers):
        return self._request("GET", f"/travel/contingencies/{event_id}", headers=headers)

    def list_contingencies_flat(self, headers, params=None):
        return self._request("GET", "/travel/contingencies", headers=headers, params=params)

    def get_credential_flat(self, cred_id, headers):
        return self._request("GET", f"/travel/credentials/{cred_id}", headers=headers)

    def list_credentials_flat(self, headers, params=None):
        return self._request("GET", "/travel/credentials", headers=headers, params=params)


api_client = ApiClient()
