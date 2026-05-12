"""API client: one method per endpoint defined in the PRD §4.

Subclasses GenericApiClient. Endpoint methods accept already-built header
dicts (constructed with build_user_headers / make_<role>_headers) so callers
can thread role-bound identity through the call.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Venue ────────────────────────────────────────────────────────────
    def create_venue(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/venues", payload, headers)

    def list_venues(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/venues", headers=headers, params=params)

    def get_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    def update_venue(self, venue_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/venues/{venue_id}", payload, headers)

    def suspend_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/suspend", headers=headers)

    def resume_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/resume", headers=headers)

    def close_venue(self, venue_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/close", headers=headers)

    # ─── Room ─────────────────────────────────────────────────────────────
    def create_room(self, venue_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/rooms", payload, headers)

    def list_rooms(self, venue_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/venues/{venue_id}/rooms", headers=headers, params=params)

    def get_room(self, venue_id: str, room_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/venues/{venue_id}/rooms/{room_id}", headers=headers)

    # ─── MaintenanceWindow ────────────────────────────────────────────────
    def create_maintenance_window(self, venue_id: str, room_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/rooms/{room_id}/maintenance-windows", payload, headers)

    def list_maintenance_windows(self, venue_id: str, room_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/venues/{venue_id}/rooms/{room_id}/maintenance-windows", headers=headers, params=params)

    # ─── Theme ────────────────────────────────────────────────────────────
    def create_theme(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/themes", payload, headers)

    def publish_theme(self, theme_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/themes/{theme_id}/publish", headers=headers)

    def publish_theme_revision(self, theme_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/themes/{theme_id}/publish-revision", payload, headers)

    def retire_theme(self, theme_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/themes/{theme_id}/retire", headers=headers)

    def get_theme(self, theme_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/themes/{theme_id}", headers=headers)

    def list_themes(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/themes", headers=headers, params=params)

    # ─── SessionSlot ──────────────────────────────────────────────────────
    def create_session_slot(self, venue_id: str, room_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/venues/{venue_id}/rooms/{room_id}/session-slots", payload, headers)

    def list_session_slots(self, venue_id: str, room_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/venues/{venue_id}/rooms/{room_id}/session-slots", headers=headers, params=params)

    def get_session_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/session-slots/{slot_id}", headers=headers)

    def start_session_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/session-slots/{slot_id}/start", headers=headers)

    def complete_session_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/session-slots/{slot_id}/complete", headers=headers)

    def cancel_session_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/session-slots/{slot_id}/cancel", headers=headers)

    # ─── Booking ──────────────────────────────────────────────────────────
    def create_booking(self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/session-slots/{slot_id}/bookings", payload, headers)

    def confirm_deposit(self, booking_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/confirm-deposit", payload or {}, headers)

    def cancel_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/cancel", headers=headers)

    def check_in_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/check-in", headers=headers)

    def refund_booking(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/refund", payload, headers)

    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    # ─── WaitlistEntry ────────────────────────────────────────────────────
    def create_waitlist_entry(self, slot_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/session-slots/{slot_id}/waitlist-entries", payload, headers)

    def cancel_waitlist_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/waitlist-entries/{entry_id}/cancel", headers=headers)

    def list_waitlist_entries(self, slot_id: str, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", f"/session-slots/{slot_id}/waitlist-entries", headers=headers, params=params)

    # ─── Player ───────────────────────────────────────────────────────────
    def create_player(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/players", payload, headers)

    def get_player(self, player_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/players/{player_id}", headers=headers)

    # ─── StaffMember ──────────────────────────────────────────────────────
    def create_staff_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/staff-members", payload, headers)

    def get_staff_member(self, staff_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/staff-members/{staff_id}", headers=headers)

    # ─── StaffAssignment ──────────────────────────────────────────────────
    def create_staff_assignment(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/staff-assignments", payload, headers)

    def handoff_staff_assignment(self, assignment_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/staff-assignments/{assignment_id}/handoff", payload, headers)

    def get_staff_assignment(self, assignment_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/staff-assignments/{assignment_id}", headers=headers)

    # ─── Review ───────────────────────────────────────────────────────────
    def create_review(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/bookings/{booking_id}/reviews", payload, headers)

    def patch_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/reviews/{review_id}", payload, headers)

    def resubmit_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/reviews/{review_id}/resubmit", headers=headers)

    def moderate_review(self, review_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/reviews/{review_id}/moderate", payload, headers)

    def get_review(self, review_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    # ─── SettlementRun ────────────────────────────────────────────────────
    def create_settlement_run(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/settlement-runs", payload, headers)

    def finalize_settlement_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/settlement-runs/{run_id}/finalize", headers=headers)

    def get_settlement_run(self, run_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/settlement-runs/{run_id}", headers=headers)

    # ─── AuditLog ─────────────────────────────────────────────────────────
    def list_audit_log(self, headers: Dict[str, str], params: Optional[Dict[str, Any]] = None):
        return self._request("GET", "/audit-log", headers=headers, params=params)

    # ─── Test-driving endpoints ───────────────────────────────────────────
    def advance_clock(self, to_timestamp: str, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"to_timestamp": to_timestamp}, headers)

    def emit_payment_confirmed(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/payment-confirmed", payload, headers)

    def emit_script_authorization_revoked(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/_events/script-authorization-revoked", payload, headers)


api_client = ApiClient()
