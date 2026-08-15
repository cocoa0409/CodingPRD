"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/v1/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # --- members / waivers / memberships / fines ---
    def create_member(self, payload, headers):
        return self._request("POST", "/v1/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/v1/members/{member_id}", headers=headers)

    def sign_waiver(self, member_id, headers):
        return self._request(
            "POST", f"/v1/members/{member_id}/waiver-sign", {}, headers,
        )

    def create_membership(self, member_id, payload, headers):
        return self._request(
            "POST", f"/v1/members/{member_id}/memberships", payload, headers,
        )

    def get_membership(self, membership_id, headers):
        return self._request(
            "GET", f"/v1/memberships/{membership_id}", headers=headers,
        )

    def list_memberships(self, headers, params=None):
        return self._request(
            "GET", "/v1/memberships", headers=headers, params=params,
        )

    def cancel_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/v1/memberships/{membership_id}/cancel", {}, headers,
        )

    def pay_fine(self, member_id, payload, headers):
        return self._request(
            "POST", f"/v1/members/{member_id}/fine-payments", payload, headers,
        )

    # --- injury reports ---
    def create_injury_report(self, payload, headers):
        return self._request("POST", "/v1/injury-reports", payload, headers)

    def get_injury_report(self, injury_report_id, headers):
        return self._request(
            "GET", f"/v1/injury-reports/{injury_report_id}", headers=headers,
        )

    def list_injury_reports(self, headers, params=None):
        return self._request(
            "GET", "/v1/injury-reports", headers=headers, params=params,
        )

    def clear_injury_report(self, injury_report_id, payload, headers):
        return self._request(
            "POST", f"/v1/injury-reports/{injury_report_id}/clear",
            payload, headers,
        )

    # --- leagues ---
    def create_league(self, payload, headers):
        return self._request("POST", "/v1/leagues", payload, headers)

    def get_league(self, league_id, headers):
        return self._request("GET", f"/v1/leagues/{league_id}", headers=headers)

    def open_registration(self, league_id, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/open-registration", {}, headers,
        )

    def close_registration(self, league_id, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/close-registration", {}, headers,
        )

    def start_season(self, league_id, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/start-season", {}, headers,
        )

    def start_playoffs(self, league_id, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/start-playoffs", {}, headers,
        )

    def cancel_league(self, league_id, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/cancel", {}, headers,
        )

    def register_free_agent(self, league_id, payload, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/free-agents", payload, headers,
        )

    def place_free_agent(self, league_id, payload, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/place-free-agent",
            payload, headers,
        )

    # --- teams / rosters ---
    def create_team(self, payload, headers):
        return self._request("POST", "/v1/teams", payload, headers)

    def get_team(self, team_id, headers):
        return self._request("GET", f"/v1/teams/{team_id}", headers=headers)

    def list_teams(self, headers, params=None):
        return self._request("GET", "/v1/teams", headers=headers, params=params)

    def place_division(self, team_id, payload, headers):
        return self._request(
            "POST", f"/v1/teams/{team_id}/place-division", payload, headers,
        )

    def reinstate_team(self, team_id, headers):
        return self._request(
            "POST", f"/v1/teams/{team_id}/reinstate", {}, headers,
        )

    def withdraw_team(self, team_id, headers):
        return self._request(
            "POST", f"/v1/teams/{team_id}/withdraw", {}, headers,
        )

    def add_roster_entry(self, team_id, payload, headers):
        return self._request(
            "POST", f"/v1/teams/{team_id}/roster-entries", payload, headers,
        )

    def get_roster_entry(self, roster_entry_id, headers):
        return self._request(
            "GET", f"/v1/roster-entries/{roster_entry_id}", headers=headers,
        )

    def list_roster_entries(self, headers, params=None):
        return self._request(
            "GET", "/v1/roster-entries", headers=headers, params=params,
        )

    def remove_roster_entry(self, roster_entry_id, headers):
        return self._request(
            "POST", f"/v1/roster-entries/{roster_entry_id}/remove", {}, headers,
        )

    # --- facilities ---
    def create_facility(self, payload, headers):
        return self._request("POST", "/v1/facilities", payload, headers)

    def get_facility(self, facility_id, headers):
        return self._request(
            "GET", f"/v1/facilities/{facility_id}", headers=headers,
        )

    def create_closure(self, facility_id, payload, headers):
        return self._request(
            "POST", f"/v1/facilities/{facility_id}/closures", payload, headers,
        )

    # --- games ---
    def create_game(self, league_id, payload, headers):
        return self._request(
            "POST", f"/v1/leagues/{league_id}/games", payload, headers,
        )

    def get_game(self, game_id, headers):
        return self._request("GET", f"/v1/games/{game_id}", headers=headers)

    def list_games(self, headers, params=None):
        return self._request("GET", "/v1/games", headers=headers, params=params)

    def reschedule_game(self, game_id, payload, headers):
        return self._request(
            "POST", f"/v1/games/{game_id}/reschedule", payload, headers,
        )

    def submit_score_report(self, game_id, payload, headers):
        return self._request(
            "POST", f"/v1/games/{game_id}/score-reports", payload, headers,
        )

    def finalize_game(self, game_id, payload, headers):
        return self._request(
            "POST", f"/v1/games/{game_id}/finalize", payload, headers,
        )

    def declare_forfeit(self, game_id, payload, headers):
        return self._request(
            "POST", f"/v1/games/{game_id}/declare-forfeit", payload, headers,
        )

    # --- staff / officiating ---
    def create_staff(self, payload, headers):
        return self._request("POST", "/v1/staff", payload, headers)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/v1/staff/{staff_id}", headers=headers)

    def create_officiating_assignment(self, game_id, payload, headers):
        return self._request(
            "POST", f"/v1/games/{game_id}/officiating-assignments",
            payload, headers,
        )

    def get_officiating_assignment(self, officiating_assignment_id, headers):
        return self._request(
            "GET",
            f"/v1/officiating-assignments/{officiating_assignment_id}",
            headers=headers,
        )

    def list_officiating_assignments(self, headers, params=None):
        return self._request(
            "GET", "/v1/officiating-assignments", headers=headers,
            params=params,
        )

    def respond_assignment(self, officiating_assignment_id, payload, headers):
        return self._request(
            "POST",
            f"/v1/officiating-assignments/{officiating_assignment_id}/respond",
            payload, headers,
        )

    def settle_assignment(self, officiating_assignment_id, headers):
        return self._request(
            "POST",
            f"/v1/officiating-assignments/{officiating_assignment_id}/settle",
            {}, headers,
        )

    # --- equipment ---
    def create_equipment_pool(self, payload, headers):
        return self._request("POST", "/v1/equipment-pools", payload, headers)

    def get_equipment_pool(self, equipment_pool_id, headers):
        return self._request(
            "GET", f"/v1/equipment-pools/{equipment_pool_id}", headers=headers,
        )

    def list_equipment_pools(self, headers, params=None):
        return self._request(
            "GET", "/v1/equipment-pools", headers=headers, params=params,
        )

    def create_equipment_checkout(self, payload, headers):
        return self._request(
            "POST", "/v1/equipment-checkouts", payload, headers,
        )

    def get_equipment_checkout(self, equipment_checkout_id, headers):
        return self._request(
            "GET", f"/v1/equipment-checkouts/{equipment_checkout_id}",
            headers=headers,
        )

    def list_equipment_checkouts(self, headers, params=None):
        return self._request(
            "GET", "/v1/equipment-checkouts", headers=headers, params=params,
        )

    def return_equipment_checkout(self, equipment_checkout_id, headers):
        return self._request(
            "POST", f"/v1/equipment-checkouts/{equipment_checkout_id}/return",
            {}, headers,
        )

    def report_equipment_lost(self, equipment_checkout_id, headers):
        return self._request(
            "POST",
            f"/v1/equipment-checkouts/{equipment_checkout_id}/report-lost",
            {}, headers,
        )

    # --- lockers ---
    def create_locker(self, payload, headers):
        return self._request("POST", "/v1/lockers", payload, headers)

    def get_locker(self, locker_id, headers):
        return self._request("GET", f"/v1/lockers/{locker_id}", headers=headers)

    def list_lockers(self, headers, params=None):
        return self._request(
            "GET", "/v1/lockers", headers=headers, params=params,
        )

    def rent_locker(self, locker_id, payload, headers):
        return self._request(
            "POST", f"/v1/lockers/{locker_id}/rent", payload, headers,
        )

    def release_locker(self, locker_id, headers):
        return self._request(
            "POST", f"/v1/lockers/{locker_id}/release", {}, headers,
        )

    # --- fitness classes ---
    def create_fitness_class(self, payload, headers):
        return self._request("POST", "/v1/fitness-classes", payload, headers)

    def get_fitness_class(self, fitness_class_id, headers):
        return self._request(
            "GET", f"/v1/fitness-classes/{fitness_class_id}", headers=headers,
        )

    def list_fitness_classes(self, headers, params=None):
        return self._request(
            "GET", "/v1/fitness-classes", headers=headers, params=params,
        )

    def create_class_registration(self, fitness_class_id, payload, headers):
        return self._request(
            "POST", f"/v1/fitness-classes/{fitness_class_id}/registrations",
            payload, headers,
        )

    def get_class_registration(self, class_registration_id, headers):
        return self._request(
            "GET", f"/v1/class-registrations/{class_registration_id}",
            headers=headers,
        )

    def list_class_registrations(self, headers, params=None):
        return self._request(
            "GET", "/v1/class-registrations", headers=headers, params=params,
        )

    def cancel_class_registration(self, class_registration_id, headers):
        return self._request(
            "POST",
            f"/v1/class-registrations/{class_registration_id}/cancel",
            {}, headers,
        )

    def complete_fitness_class(self, fitness_class_id, payload, headers):
        return self._request(
            "POST", f"/v1/fitness-classes/{fitness_class_id}/complete",
            payload, headers,
        )


api_client = ApiClient()
