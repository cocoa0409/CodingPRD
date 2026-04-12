"""API client: one method per endpoint from scaffold Table 5."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """PRD-specific API client for Meeting Room Management System."""

    # -----------------------------------------------------------------------
    # Rooms
    # -----------------------------------------------------------------------

    def create_room(self, payload: dict, headers: dict):
        """POST /rooms - Create a new meeting room."""
        return self._request("POST", "/rooms", payload, headers)

    def list_rooms(self, headers: dict, params: dict | None = None):
        """GET /rooms - List all rooms with optional filters."""
        return self._request("GET", "/rooms", headers=headers, params=params)

    def get_room(self, room_id: str, headers: dict):
        """GET /rooms/{room_id} - Get room details."""
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def update_room(self, room_id: str, payload: dict, headers: dict):
        """PUT /rooms/{room_id} - Update room details."""
        return self._request("PUT", f"/rooms/{room_id}", payload, headers)

    def run_ops(self, room_id: str, headers: dict):
        """POST /rooms/{room_id}/run_ops - Run operations housekeeping."""
        return self._request("POST", f"/rooms/{room_id}/run_ops", headers=headers)

    # -----------------------------------------------------------------------
    # Bookings
    # -----------------------------------------------------------------------

    def create_booking(self, payload: dict, headers: dict):
        """POST /bookings - Create a new booking."""
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers: dict, params: dict | None = None):
        """GET /bookings - List bookings with optional filters."""
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id: str, headers: dict):
        """GET /bookings/{booking_id} - Get booking details."""
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def approve_booking(self, booking_id: str, headers: dict):
        """POST /bookings/{booking_id}/approve - Approve a PENDING_APPROVAL booking."""
        return self._request("POST", f"/bookings/{booking_id}/approve", headers=headers)

    def reject_booking(self, booking_id: str, payload: dict, headers: dict):
        """POST /bookings/{booking_id}/reject - Reject a PENDING_APPROVAL booking."""
        return self._request("POST", f"/bookings/{booking_id}/reject", payload, headers)

    def check_in_booking(self, booking_id: str, headers: dict):
        """POST /bookings/{booking_id}/check-in - Check in to a confirmed booking."""
        return self._request("POST", f"/bookings/{booking_id}/check-in", headers=headers)

    def check_out_booking(self, booking_id: str, headers: dict):
        """POST /bookings/{booking_id}/check-out - Check out of a booking."""
        return self._request("POST", f"/bookings/{booking_id}/check-out", headers=headers)

    def cancel_booking(self, booking_id: str, headers: dict):
        """POST /bookings/{booking_id}/cancel - Cancel a booking."""
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    # -----------------------------------------------------------------------
    # Series
    # -----------------------------------------------------------------------

    def create_series(self, payload: dict, headers: dict):
        """POST /series - Create a recurring booking series."""
        return self._request("POST", "/series", payload, headers)

    def get_series(self, series_id: str, headers: dict):
        """GET /series/{series_id} - Get series details."""
        return self._request("GET", f"/series/{series_id}", headers=headers)

    def cancel_series(self, series_id: str, headers: dict):
        """POST /series/{series_id}/cancel - Cancel entire series."""
        return self._request("POST", f"/series/{series_id}/cancel", headers=headers)

    # -----------------------------------------------------------------------
    # Waitlist
    # -----------------------------------------------------------------------

    def create_waitlist(self, payload: dict, headers: dict):
        """POST /waitlist - Join the waitlist for a room and time slot."""
        return self._request("POST", "/waitlist", payload, headers)

    def list_waitlist(self, headers: dict, params: dict | None = None):
        """GET /waitlist - List waitlist entries with optional filters."""
        return self._request("GET", "/waitlist", headers=headers, params=params)

    def cancel_waitlist(self, waitlist_id: str, headers: dict):
        """DELETE /waitlist/{waitlist_id} - Cancel a waitlist entry."""
        return self._request("DELETE", f"/waitlist/{waitlist_id}", headers=headers)

    # -----------------------------------------------------------------------
    # Audit Logs
    # -----------------------------------------------------------------------

    def list_audit_logs(self, headers: dict, params: dict | None = None):
        """GET /audit-logs - List audit log entries."""
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    def get_audit_log(self, log_id: str, headers: dict):
        """GET /audit-logs/{log_id} - Get a single audit log entry."""
        return self._request("GET", f"/audit-logs/{log_id}", headers=headers)


api_client = ApiClient()
