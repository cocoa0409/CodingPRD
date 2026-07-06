"""API client: one method per endpoint defined in the PRD (PRD §4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Configuration: Officers (PRD §3.1) ──────────────────────
    def create_officer(self, payload, headers):
        return self._request("POST", "/officers", payload, headers)

    def get_officer(self, officer_id, headers):
        return self._request("GET", f"/officers/{officer_id}", headers=headers)

    # ─── Configuration: Beats (PRD §3.1) ─────────────────────────
    def create_beat(self, payload, headers):
        return self._request("POST", "/beats", payload, headers)

    def get_beat(self, beat_id, headers):
        return self._request("GET", f"/beats/{beat_id}", headers=headers)

    # ─── Configuration: Violation Codes (PRD §3.1) ───────────────
    def create_violation_code(self, payload, headers):
        return self._request("POST", "/violation-codes", payload, headers)

    def get_violation_code(self, vc_id, headers):
        return self._request("GET", f"/violation-codes/{vc_id}", headers=headers)

    def retire_violation_code(self, vc_id, headers):
        return self._request(
            "POST", f"/violation-codes/{vc_id}/retire", {}, headers
        )

    # ─── Configuration: Hearing Rooms (PRD §3.1) ─────────────────
    def create_hearing_room(self, payload, headers):
        return self._request("POST", "/hearing-rooms", payload, headers)

    def get_hearing_room(self, room_id, headers):
        return self._request("GET", f"/hearing-rooms/{room_id}", headers=headers)

    # ─── Shifts (PRD §3.2) ───────────────────────────────────────
    def create_shift(self, payload, headers):
        return self._request("POST", "/shifts", payload, headers)

    def get_shift(self, shift_id, headers):
        return self._request("GET", f"/shifts/{shift_id}", headers=headers)

    def list_shifts(self, headers, params=None):
        return self._request("GET", "/shifts", headers=headers, params=params)

    def close_shift(self, shift_id, headers):
        return self._request("POST", f"/shifts/{shift_id}/close", {}, headers)

    # ─── Vehicles (PRD §3.4, §3.7) ───────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def create_adjustment(self, vehicle_id, payload, headers):
        return self._request(
            "POST", f"/vehicles/{vehicle_id}/adjustments", payload, headers
        )

    # ─── Citations (PRD §3.3, §3.7) ──────────────────────────────
    def create_citation(self, payload, headers):
        return self._request("POST", "/citations", payload, headers)

    def get_citation(self, citation_id, headers):
        return self._request("GET", f"/citations/{citation_id}", headers=headers)

    def list_citations(self, headers, params=None):
        return self._request("GET", "/citations", headers=headers, params=params)

    def reassess_citation(self, citation_id, payload, headers):
        return self._request(
            "POST", f"/citations/{citation_id}/reassess", payload, headers
        )

    def void_citation(self, citation_id, headers):
        return self._request("POST", f"/citations/{citation_id}/void", {}, headers)

    # ─── Payments (PRD §3.5) ─────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def settle_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/settle", {}, headers)

    def refund_payment(self, payment_id, headers):
        return self._request("POST", f"/payments/{payment_id}/refund", {}, headers)

    # ─── Contests (PRD §3.6) ─────────────────────────────────────
    def create_contest(self, payload, headers):
        return self._request("POST", "/contests", payload, headers)

    def get_contest(self, contest_id, headers):
        return self._request("GET", f"/contests/{contest_id}", headers=headers)

    def list_contests(self, headers, params=None):
        return self._request("GET", "/contests", headers=headers, params=params)

    # ─── Hearings (PRD §3.6) ─────────────────────────────────────
    def create_hearing(self, payload, headers):
        return self._request("POST", "/hearings", payload, headers)

    def get_hearing(self, hearing_id, headers):
        return self._request("GET", f"/hearings/{hearing_id}", headers=headers)

    def list_hearings(self, headers, params=None):
        return self._request("GET", "/hearings", headers=headers, params=params)

    def adjourn_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/adjourn", payload, headers
        )

    def decide_hearing(self, hearing_id, payload, headers):
        return self._request(
            "POST", f"/hearings/{hearing_id}/decide", payload, headers
        )

    # ─── Boot / Tow orders (PRD §3.8) ────────────────────────────
    def create_boot_tow_order(self, payload, headers):
        return self._request("POST", "/boot-tow-orders", payload, headers)

    def get_boot_tow_order(self, order_id, headers):
        return self._request("GET", f"/boot-tow-orders/{order_id}", headers=headers)

    def list_boot_tow_orders(self, headers, params=None):
        return self._request(
            "GET", "/boot-tow-orders", headers=headers, params=params
        )

    def apply_boot_tow_order(self, order_id, headers):
        return self._request(
            "POST", f"/boot-tow-orders/{order_id}/apply", {}, headers
        )

    def release_boot_tow_order(self, order_id, headers):
        return self._request(
            "POST", f"/boot-tow-orders/{order_id}/release", {}, headers
        )

    # ─── Registration holds (PRD §3.8) ───────────────────────────
    def get_registration_hold(self, hold_id, headers):
        return self._request(
            "GET", f"/registration-holds/{hold_id}", headers=headers
        )

    def list_registration_holds(self, headers, params=None):
        return self._request(
            "GET", "/registration-holds", headers=headers, params=params
        )

    # ─── Logical clock (PRD §2.5) ────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
