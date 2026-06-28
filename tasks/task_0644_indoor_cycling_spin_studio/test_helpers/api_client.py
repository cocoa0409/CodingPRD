"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ---- Studio ----
    def create_studio(self, payload, headers):
        return self._request("POST", "/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studios/{studio_id}", headers=headers)

    def list_studios(self, headers, params=None):
        return self._request("GET", "/studios", headers=headers, params=params)

    # ---- Room ----
    def create_room(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def list_rooms(self, studio_id, headers, params=None):
        return self._request("GET", f"/studios/{studio_id}/rooms", headers=headers, params=params)

    # ---- Bike ----
    def create_bike(self, studio_id, room_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/rooms/{room_id}/bikes", payload, headers
        )

    def list_bikes(self, room_id, headers, params=None):
        return self._request("GET", f"/rooms/{room_id}/bikes", headers=headers, params=params)

    def retire_bike(self, studio_id, room_id, bike_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/rooms/{room_id}/bikes/{bike_id}/retire",
            {},
            headers,
        )

    # ---- Instructor ----
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    # ---- ClassSession ----
    def create_session(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def cancel_session(self, studio_id, session_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/sessions/{session_id}/cancel", {}, headers
        )

    def complete_session(self, studio_id, session_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/sessions/{session_id}/complete", {}, headers
        )

    # ---- Member ----
    def register_member(self, payload, headers):
        return self._request("POST", "/members/register", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def reinstate_member(self, member_id, headers):
        return self._request("POST", f"/members/{member_id}/reinstate", {}, headers)

    # ---- CreditPack ----
    def create_credit_pack(self, payload, headers):
        return self._request("POST", "/credit-packs", payload, headers)

    def get_credit_pack(self, pack_id, headers):
        return self._request("GET", f"/credit-packs/{pack_id}", headers=headers)

    def list_credit_packs(self, headers, params=None):
        return self._request("GET", "/credit-packs", headers=headers, params=params)

    def refund_credit_pack(self, pack_id, payload, headers):
        return self._request("POST", f"/credit-packs/{pack_id}/refund", payload, headers)

    # ---- Reservation ----
    def create_reservation(self, studio_id, session_id, payload, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/sessions/{session_id}/reservations",
            payload,
            headers,
        )

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def cancel_reservation(self, studio_id, session_id, reservation_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/sessions/{session_id}/reservations/{reservation_id}/cancel",
            {},
            headers,
        )

    def check_in_reservation(self, studio_id, session_id, reservation_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/sessions/{session_id}/reservations/{reservation_id}/check-in",
            {},
            headers,
        )

    def return_shoe(self, reservation_id, headers):
        return self._request(
            "POST", f"/reservations/{reservation_id}/return-shoe", {}, headers
        )

    # ---- Waitlist ----
    def join_waitlist(self, studio_id, session_id, payload, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/sessions/{session_id}/waitlist", payload, headers
        )

    def get_waitlist_entry(self, entry_id, headers):
        return self._request("GET", f"/waitlist-entries/{entry_id}", headers=headers)

    def list_waitlist_entries(self, headers, params=None):
        return self._request("GET", "/waitlist-entries", headers=headers, params=params)

    def leave_waitlist(self, studio_id, session_id, entry_id, headers):
        return self._request(
            "POST",
            f"/studios/{studio_id}/sessions/{session_id}/waitlist/{entry_id}/leave",
            {},
            headers,
        )

    # ---- Product / Retail ----
    def create_product(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/products", payload, headers)

    def get_product(self, product_id, headers):
        return self._request("GET", f"/products/{product_id}", headers=headers)

    def list_products(self, headers, params=None):
        return self._request("GET", "/products", headers=headers, params=params)

    def discontinue_product(self, studio_id, product_id, headers):
        return self._request(
            "POST", f"/studios/{studio_id}/products/{product_id}/discontinue", {}, headers
        )

    def create_retail_order(self, payload, headers):
        return self._request("POST", "/retail-orders", payload, headers)

    def get_retail_order(self, order_id, headers):
        return self._request("GET", f"/retail-orders/{order_id}", headers=headers)

    def list_retail_orders(self, headers, params=None):
        return self._request("GET", "/retail-orders", headers=headers, params=params)

    # ---- PenaltyCharge ----
    def get_penalty_charge(self, charge_id, headers):
        return self._request("GET", f"/penalty-charges/{charge_id}", headers=headers)

    def list_penalty_charges(self, headers, params=None):
        return self._request("GET", "/penalty-charges", headers=headers, params=params)

    def waive_penalty_charge(self, charge_id, headers):
        return self._request("POST", f"/penalty-charges/{charge_id}/waive", {}, headers)


api_client = ApiClient()
