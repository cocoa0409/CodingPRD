"""API client: one method per endpoint defined in the PRD (§4).

All paths are mounted under the service prefix `/boathouse`.
"""

from prd_bench_local_runner.testing import GenericApiClient

BASE = "/boathouse"


class ApiClient(GenericApiClient):
    # --- Logical clock -----------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", f"{BASE}/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --- Members ----------------------------------------------------------
    def create_member(self, payload, headers):
        return self._request("POST", f"{BASE}/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"{BASE}/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", f"{BASE}/members", headers=headers, params=params)

    def update_member_certifications(self, member_id, payload, headers):
        return self._request(
            "PATCH", f"{BASE}/members/{member_id}/certifications", payload, headers
        )

    def transition_member(self, member_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/members/{member_id}/status-transitions", payload, headers
        )

    def list_member_dues_invoices(self, member_id, headers, params=None):
        return self._request(
            "GET", f"{BASE}/members/{member_id}/dues-invoices", headers=headers, params=params
        )

    # --- Dues invoices ----------------------------------------------------
    def create_dues_invoice(self, payload, headers):
        return self._request("POST", f"{BASE}/dues-invoices", payload, headers)

    def get_dues_invoice(self, invoice_id, headers):
        return self._request("GET", f"{BASE}/dues-invoices/{invoice_id}", headers=headers)

    def pay_dues_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/dues-invoices/{invoice_id}/payments", payload, headers
        )

    def true_up_dues_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/dues-invoices/{invoice_id}/true-up", payload, headers
        )

    def void_dues_invoice(self, invoice_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/dues-invoices/{invoice_id}/void", payload, headers
        )

    def run_dues_delinquency(self, payload, headers):
        return self._request("POST", f"{BASE}/ops/dues-delinquency-run", payload, headers)

    # --- Shells -----------------------------------------------------------
    def create_shell(self, payload, headers):
        return self._request("POST", f"{BASE}/shells", payload, headers)

    def get_shell(self, shell_id, headers):
        return self._request("GET", f"{BASE}/shells/{shell_id}", headers=headers)

    def list_shells(self, headers, params=None):
        return self._request("GET", f"{BASE}/shells", headers=headers, params=params)

    def retire_shell(self, shell_id, payload, headers):
        return self._request("POST", f"{BASE}/shells/{shell_id}/retire", payload, headers)

    # --- Damage reports ---------------------------------------------------
    def create_damage_report(self, payload, headers):
        return self._request("POST", f"{BASE}/damage-reports", payload, headers)

    def get_damage_report(self, report_id, headers):
        return self._request("GET", f"{BASE}/damage-reports/{report_id}", headers=headers)

    def list_damage_reports(self, headers, params=None):
        return self._request("GET", f"{BASE}/damage-reports", headers=headers, params=params)

    def triage_damage_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/damage-reports/{report_id}/triage", payload, headers
        )

    def schedule_repair(self, report_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/damage-reports/{report_id}/schedule-repair", payload, headers
        )

    def verify_repair(self, report_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/damage-reports/{report_id}/verify-repair", payload, headers
        )

    def condemn_damage_report(self, report_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/damage-reports/{report_id}/condemn", payload, headers
        )

    # --- Water condition readings ----------------------------------------
    def create_water_condition_reading(self, payload, headers):
        return self._request("POST", f"{BASE}/water-condition-readings", payload, headers)

    def get_water_condition_reading(self, reading_id, headers):
        return self._request(
            "GET", f"{BASE}/water-condition-readings/{reading_id}", headers=headers
        )

    def list_water_condition_readings(self, headers, params=None):
        return self._request(
            "GET", f"{BASE}/water-condition-readings", headers=headers, params=params
        )

    # --- Water sessions ---------------------------------------------------
    def create_water_session(self, payload, headers):
        return self._request("POST", f"{BASE}/water-sessions", payload, headers)

    def get_water_session(self, session_id, headers):
        return self._request("GET", f"{BASE}/water-sessions/{session_id}", headers=headers)

    def list_water_sessions(self, headers, params=None):
        return self._request("GET", f"{BASE}/water-sessions", headers=headers, params=params)

    def clear_water_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/water-sessions/{session_id}/clear", payload, headers
        )

    def launch_water_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/water-sessions/{session_id}/launch", payload, headers
        )

    def return_water_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/water-sessions/{session_id}/return", payload, headers
        )

    def cancel_water_session(self, session_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/water-sessions/{session_id}/cancel", payload, headers
        )

    # --- Regattas ---------------------------------------------------------
    def create_regatta(self, payload, headers):
        return self._request("POST", f"{BASE}/regattas", payload, headers)

    def get_regatta(self, regatta_id, headers):
        return self._request("GET", f"{BASE}/regattas/{regatta_id}", headers=headers)

    def list_regattas(self, headers, params=None):
        return self._request("GET", f"{BASE}/regattas", headers=headers, params=params)

    def transition_regatta(self, regatta_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/regattas/{regatta_id}/status-transitions", payload, headers
        )

    # --- Regatta entries --------------------------------------------------
    def create_regatta_entry(self, payload, headers):
        return self._request("POST", f"{BASE}/regatta-entries", payload, headers)

    def get_regatta_entry(self, entry_id, headers):
        return self._request("GET", f"{BASE}/regatta-entries/{entry_id}", headers=headers)

    def list_regatta_entries(self, headers, params=None):
        return self._request("GET", f"{BASE}/regatta-entries", headers=headers, params=params)

    def declare_lineup(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/regatta-entries/{entry_id}/lineup", payload, headers
        )

    def submit_regatta_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/regatta-entries/{entry_id}/submit", payload, headers
        )

    def confirm_regatta_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/regatta-entries/{entry_id}/confirm", payload, headers
        )

    def scratch_regatta_entry(self, entry_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/regatta-entries/{entry_id}/scratch", payload, headers
        )

    # --- Lineup seats -----------------------------------------------------
    def get_lineup_seat(self, seat_id, headers):
        return self._request("GET", f"{BASE}/lineup-seats/{seat_id}", headers=headers)

    def list_lineup_seats(self, headers, params=None):
        return self._request("GET", f"{BASE}/lineup-seats", headers=headers, params=params)

    def weigh_in_lineup_seat(self, seat_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/lineup-seats/{seat_id}/weigh-in", payload, headers
        )

    # --- Heats ------------------------------------------------------------
    def create_heat(self, payload, headers):
        return self._request("POST", f"{BASE}/heats", payload, headers)

    def get_heat(self, heat_id, headers):
        return self._request("GET", f"{BASE}/heats/{heat_id}", headers=headers)

    def list_heats(self, headers, params=None):
        return self._request("GET", f"{BASE}/heats", headers=headers, params=params)

    def assign_lanes(self, heat_id, payload, headers):
        return self._request("POST", f"{BASE}/heats/{heat_id}/assign-lanes", payload, headers)

    def post_heat_results(self, heat_id, payload, headers):
        return self._request("POST", f"{BASE}/heats/{heat_id}/results", payload, headers)

    def officialize_heat(self, heat_id, payload, headers):
        return self._request("POST", f"{BASE}/heats/{heat_id}/officialize", payload, headers)

    # --- Race lanes -------------------------------------------------------
    def get_race_lane(self, lane_id, headers):
        return self._request("GET", f"{BASE}/race-lanes/{lane_id}", headers=headers)

    def list_race_lanes(self, headers, params=None):
        return self._request("GET", f"{BASE}/race-lanes", headers=headers, params=params)

    # --- Protests ---------------------------------------------------------
    def create_protest(self, payload, headers):
        return self._request("POST", f"{BASE}/protests", payload, headers)

    def get_protest(self, protest_id, headers):
        return self._request("GET", f"{BASE}/protests/{protest_id}", headers=headers)

    def list_protests(self, headers, params=None):
        return self._request("GET", f"{BASE}/protests", headers=headers, params=params)

    def open_protest_review(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/protests/{protest_id}/open-review", payload, headers
        )

    def rule_on_protest(self, protest_id, payload, headers):
        return self._request("POST", f"{BASE}/protests/{protest_id}/rule", payload, headers)

    def withdraw_protest(self, protest_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/protests/{protest_id}/withdraw", payload, headers
        )

    # --- Trailer loads ----------------------------------------------------
    def create_trailer_load(self, payload, headers):
        return self._request("POST", f"{BASE}/trailer-loads", payload, headers)

    def get_trailer_load(self, trailer_id, headers):
        return self._request("GET", f"{BASE}/trailer-loads/{trailer_id}", headers=headers)

    def list_trailer_loads(self, headers, params=None):
        return self._request("GET", f"{BASE}/trailer-loads", headers=headers, params=params)

    def create_rack_assignment(self, trailer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trailer-loads/{trailer_id}/rack-assignments", payload, headers
        )

    def create_rack_release(self, trailer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trailer-loads/{trailer_id}/rack-releases", payload, headers
        )

    def transition_trailer_load(self, trailer_id, payload, headers):
        return self._request(
            "POST", f"{BASE}/trailer-loads/{trailer_id}/transitions", payload, headers
        )


api_client = ApiClient()
