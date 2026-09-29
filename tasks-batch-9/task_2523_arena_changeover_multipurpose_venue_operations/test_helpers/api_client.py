"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---------------------------------------------------------------- clock
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # --------------------------------------------------------------- venues
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/venues/{venue_id}", headers=headers)

    # ------------------------------------------------ configuration profiles
    def create_configuration_profile(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/configuration-profiles", payload, headers
        )

    def list_configuration_profiles(self, venue_id, headers, params=None):
        return self._request(
            "GET",
            f"/venues/{venue_id}/configuration-profiles",
            headers=headers,
            params=params,
        )

    # -------------------------------------------------------- anchor tenants
    def create_anchor_tenant(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/anchor-tenants", payload, headers
        )

    def list_anchor_tenants(self, venue_id, headers, params=None):
        return self._request(
            "GET", f"/venues/{venue_id}/anchor-tenants", headers=headers, params=params
        )

    # ------------------------------------------------------ equipment assets
    def create_equipment_asset(self, venue_id, payload, headers):
        return self._request(
            "POST", f"/venues/{venue_id}/equipment-assets", payload, headers
        )

    def list_venue_equipment_assets(self, venue_id, headers, params=None):
        return self._request(
            "GET",
            f"/venues/{venue_id}/equipment-assets",
            headers=headers,
            params=params,
        )

    def get_equipment_asset(self, asset_id, headers):
        return self._request("GET", f"/equipment-assets/{asset_id}", headers=headers)

    def equipment_asset_maintenance(self, asset_id, payload, headers):
        return self._request(
            "POST", f"/equipment-assets/{asset_id}/maintenance", payload, headers
        )

    # ------------------------------------------------------------ ice sheets
    def create_ice_sheet(self, venue_id, payload, headers):
        return self._request("POST", f"/venues/{venue_id}/ice-sheets", payload, headers)

    def list_ice_sheets(self, venue_id, headers, params=None):
        return self._request(
            "GET", f"/venues/{venue_id}/ice-sheets", headers=headers, params=params
        )

    def transition_ice_sheet(self, sheet_id, payload, headers):
        return self._request(
            "POST", f"/ice-sheets/{sheet_id}/transition", payload, headers
        )

    # --------------------------------------------------------- event bookings
    def create_event_booking(self, payload, headers):
        return self._request("POST", "/event-bookings", payload, headers)

    def get_event_booking(self, booking_id, headers):
        return self._request("GET", f"/event-bookings/{booking_id}", headers=headers)

    def list_event_bookings(self, headers, params=None):
        return self._request("GET", "/event-bookings", headers=headers, params=params)

    def hold_event_booking(self, booking_id, headers, payload=None):
        return self._request(
            "POST", f"/event-bookings/{booking_id}/hold", payload or {}, headers
        )

    def confirm_event_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/event-bookings/{booking_id}/confirm", payload, headers
        )

    def release_event_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/event-bookings/{booking_id}/release", payload, headers
        )

    def hold_expiry_sweep(self, venue_id, headers, payload=None):
        return self._request(
            "POST", f"/venues/{venue_id}/hold-expiry-sweep", payload or {}, headers
        )

    # -------------------------------------------------------- hold challenges
    def create_hold_challenge(self, payload, headers):
        return self._request("POST", "/hold-challenges", payload, headers)

    def get_hold_challenge(self, challenge_id, headers):
        return self._request("GET", f"/hold-challenges/{challenge_id}", headers=headers)

    def list_hold_challenges(self, headers, params=None):
        return self._request("GET", "/hold-challenges", headers=headers, params=params)

    def rule_hold_challenge(self, challenge_id, payload, headers):
        return self._request(
            "POST", f"/hold-challenges/{challenge_id}/rule", payload, headers
        )

    def withdraw_hold_challenge(self, challenge_id, headers, payload=None):
        return self._request(
            "POST", f"/hold-challenges/{challenge_id}/withdraw", payload or {}, headers
        )

    # ------------------------------------------------------ changeover orders
    def create_changeover_order(self, payload, headers):
        return self._request("POST", "/changeover-orders", payload, headers)

    def get_changeover_order(self, order_id, headers):
        return self._request("GET", f"/changeover-orders/{order_id}", headers=headers)

    def list_changeover_orders(self, headers, params=None):
        return self._request(
            "GET", "/changeover-orders", headers=headers, params=params
        )

    def progress_changeover_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/changeover-orders/{order_id}/progress", payload, headers
        )

    def rework_changeover_order(self, order_id, payload, headers):
        return self._request(
            "POST", f"/changeover-orders/{order_id}/rework", payload, headers
        )

    def signoff_changeover_order(self, order_id, headers, payload=None):
        return self._request(
            "POST", f"/changeover-orders/{order_id}/signoff", payload or {}, headers
        )

    def get_changeover_readiness(self, order_id, headers):
        return self._request(
            "GET", f"/changeover-orders/{order_id}/readiness", headers=headers
        )

    # ------------------------------------------------ dock slot reservations
    def create_dock_slot_reservation(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/event-bookings/{booking_id}/dock-slot-reservations",
            payload, headers,
        )

    def list_dock_slot_reservations(self, booking_id, headers, params=None):
        return self._request(
            "GET",
            f"/event-bookings/{booking_id}/dock-slot-reservations",
            headers=headers,
            params=params,
        )

    def cancel_dock_slot_reservation(self, reservation_id, headers, payload=None):
        return self._request(
            "POST",
            f"/dock-slot-reservations/{reservation_id}/cancel",
            payload or {},
            headers,
        )

    # ----------------------------------------------------------- labor calls
    def create_labor_call(self, payload, headers):
        return self._request("POST", "/labor-calls", payload, headers)

    def get_labor_call(self, call_id, headers):
        return self._request("GET", f"/labor-calls/{call_id}", headers=headers)

    def list_labor_calls(self, headers, params=None):
        return self._request("GET", "/labor-calls", headers=headers, params=params)

    def close_labor_call(self, call_id, payload, headers):
        return self._request("POST", f"/labor-calls/{call_id}/close", payload, headers)

    def cancel_labor_call(self, call_id, headers, payload=None):
        return self._request(
            "POST", f"/labor-calls/{call_id}/cancel", payload or {}, headers
        )

    # ------------------------------------------------------ equipment issues
    def create_equipment_issue(self, payload, headers):
        return self._request("POST", "/equipment-issues", payload, headers)

    def get_equipment_issue(self, issue_id, headers):
        return self._request("GET", f"/equipment-issues/{issue_id}", headers=headers)

    def list_equipment_issues(self, headers, params=None):
        return self._request("GET", "/equipment-issues", headers=headers, params=params)

    def return_equipment_issue(self, issue_id, headers, payload=None):
        return self._request(
            "POST", f"/equipment-issues/{issue_id}/return", payload or {}, headers
        )


api_client = ApiClient()
