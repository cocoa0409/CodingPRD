"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ── Clock ───────────────────────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ── Members ─────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def clear_velocity(self, member_id, expected_member_version, headers):
        return self._request(
            "POST", f"/members/{member_id}/clear-velocity",
            {"expected_member_version": expected_member_version}, headers,
        )

    # ── Properties ──────────────────────────────────────────────────
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def list_property_members(self, property_id, headers, params=None):
        return self._request(
            "GET", f"/properties/{property_id}/members",
            headers=headers, params=params,
        )

    # ── Hosts ───────────────────────────────────────────────────────
    def create_host(self, payload, headers):
        return self._request("POST", "/hosts", payload, headers)

    def get_host(self, host_id, headers):
        return self._request("GET", f"/hosts/{host_id}", headers=headers)

    def list_hosts(self, headers, params=None):
        return self._request("GET", "/hosts", headers=headers, params=params)

    # ── Host Assignments ────────────────────────────────────────────
    def create_host_assignment(self, payload, headers):
        return self._request("POST", "/host-assignments", payload, headers)

    def get_host_assignment(self, ha_id, headers):
        return self._request("GET", f"/host-assignments/{ha_id}", headers=headers)

    def list_host_assignments(self, headers, params=None):
        return self._request(
            "GET", "/host-assignments", headers=headers, params=params,
        )

    def approve_host_assignment(self, ha_id, headers):
        return self._request(
            "POST", f"/host-assignments/{ha_id}/approve", {}, headers,
        )

    def reject_host_assignment(self, ha_id, headers):
        return self._request(
            "POST", f"/host-assignments/{ha_id}/reject", {}, headers,
        )

    def revoke_host_assignment(self, ha_id, headers):
        return self._request(
            "POST", f"/host-assignments/{ha_id}/revoke", {}, headers,
        )

    # ── Gaming Sessions ─────────────────────────────────────────────
    def create_gaming_session(self, payload, headers):
        return self._request("POST", "/gaming-sessions", payload, headers)

    def get_gaming_session(self, session_id, headers):
        return self._request(
            "GET", f"/gaming-sessions/{session_id}", headers=headers,
        )

    def list_gaming_sessions(self, headers, params=None):
        return self._request(
            "GET", "/gaming-sessions", headers=headers, params=params,
        )

    # ── Comp Room Bookings ──────────────────────────────────────────
    def create_comp_room_booking(self, payload, headers):
        return self._request("POST", "/comp-room-bookings", payload, headers)

    def get_comp_room_booking(self, booking_id, headers):
        return self._request(
            "GET", f"/comp-room-bookings/{booking_id}", headers=headers,
        )

    def list_comp_room_bookings(self, headers, params=None):
        return self._request(
            "GET", "/comp-room-bookings", headers=headers, params=params,
        )

    def confirm_comp_room_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/comp-room-bookings/{booking_id}/confirm", {}, headers,
        )

    def check_in_comp_room_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/comp-room-bookings/{booking_id}/check-in", {}, headers,
        )

    def check_out_comp_room_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/comp-room-bookings/{booking_id}/check-out", {}, headers,
        )

    def cancel_comp_room_booking(self, booking_id, headers):
        return self._request(
            "POST", f"/comp-room-bookings/{booking_id}/cancel", {}, headers,
        )

    def revert_comp_room_booking_to_pending(self, booking_id, headers):
        return self._request(
            "POST", f"/comp-room-bookings/{booking_id}/revert-to-pending",
            {}, headers,
        )

    # ── Self Exclusions ─────────────────────────────────────────────
    def create_self_exclusion(self, payload, headers):
        return self._request("POST", "/self-exclusions", payload, headers)

    def get_self_exclusion(self, se_id, headers):
        return self._request("GET", f"/self-exclusions/{se_id}", headers=headers)

    def list_self_exclusions(self, headers, params=None):
        return self._request(
            "GET", "/self-exclusions", headers=headers, params=params,
        )

    def reinstate_self_exclusion(self, se_id, headers):
        return self._request(
            "POST", f"/self-exclusions/{se_id}/reinstate", {}, headers,
        )

    # ── Velocity Alerts ─────────────────────────────────────────────
    def get_velocity_alert(self, alert_id, headers):
        return self._request(
            "GET", f"/velocity-alerts/{alert_id}", headers=headers,
        )

    def list_velocity_alerts(self, headers, params=None):
        return self._request(
            "GET", "/velocity-alerts", headers=headers, params=params,
        )

    # ── Annual Reset Runs ───────────────────────────────────────────
    def create_annual_reset_run(self, payload, headers):
        return self._request("POST", "/annual-reset-runs", payload, headers)

    def get_annual_reset_run(self, ar_id, headers):
        return self._request(
            "GET", f"/annual-reset-runs/{ar_id}", headers=headers,
        )

    def list_annual_reset_runs(self, headers, params=None):
        return self._request(
            "GET", "/annual-reset-runs", headers=headers, params=params,
        )

    def execute_annual_reset_run(self, ar_id, headers):
        return self._request(
            "POST", f"/annual-reset-runs/{ar_id}/execute", {}, headers,
        )

    def cancel_annual_reset_run(self, ar_id, headers):
        return self._request(
            "POST", f"/annual-reset-runs/{ar_id}/cancel", {}, headers,
        )


api_client = ApiClient()
