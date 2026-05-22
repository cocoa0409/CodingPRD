"""API client: one method per endpoint defined by the gym membership PRD (§4)."""

from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Concrete client. Every method returns the raw requests.Response."""

    # ──────────────── Members ────────────────

    def create_member(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/members", payload, headers)

    def login_member(self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/members/{member_id}/login", payload, headers)

    def list_members(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/members", headers=headers, params=params)

    def get_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def suspend_member(
        self, member_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]
    ):
        return self._request("POST", f"/members/{member_id}/suspend", payload or {}, headers)

    def resume_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/members/{member_id}/resume", headers=headers)

    def cancel_member(self, member_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/members/{member_id}/cancel", headers=headers)

    # ──────────────── Subscriptions ────────────────

    def create_subscription(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/members/{member_id}/subscriptions", payload, headers
        )

    def list_subscriptions(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/members/{member_id}/subscriptions", headers=headers, params=params
        )

    def get_subscription(self, member_id: str, sub_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/members/{member_id}/subscriptions/{sub_id}", headers=headers
        )

    def reinstate_subscription(
        self, member_id: str, sub_id: str, headers: Dict[str, str]
    ):
        return self._request(
            "POST",
            f"/members/{member_id}/subscriptions/{sub_id}/reinstate",
            headers=headers,
        )

    # ──────────────── Payment attempts ────────────────

    def create_payment_attempt(
        self,
        member_id: str,
        sub_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/members/{member_id}/subscriptions/{sub_id}/payment-attempts",
            payload,
            headers,
        )

    def list_payment_attempts(
        self,
        member_id: str,
        sub_id: str,
        headers: Dict[str, str],
        params: Optional[Dict] = None,
    ):
        return self._request(
            "GET",
            f"/members/{member_id}/subscriptions/{sub_id}/payment-attempts",
            headers=headers,
            params=params,
        )

    # ──────────────── Stores ────────────────

    def list_stores(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/stores", headers=headers, params=params)

    def create_class_session(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stores/{store_id}/class-sessions", payload, headers
        )

    def list_class_sessions(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/stores/{store_id}/class-sessions", headers=headers, params=params
        )

    def get_class_session(self, store_id: str, session_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/stores/{store_id}/class-sessions/{session_id}", headers=headers
        )

    def cancel_class_session(self, store_id: str, session_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/stores/{store_id}/class-sessions/{session_id}/cancel",
            headers=headers,
        )

    def create_equipment_pool(
        self, store_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request(
            "POST", f"/stores/{store_id}/equipment-pools", payload, headers
        )

    def list_equipment_pools(
        self, store_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET",
            f"/stores/{store_id}/equipment-pools",
            headers=headers,
            params=params,
        )

    # ──────────────── Trainers ────────────────

    def create_trainer(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/trainers", payload, headers)

    def list_trainers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/trainers", headers=headers, params=params)

    def get_trainer(self, trainer_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/trainers/{trainer_id}", headers=headers)

    # ──────────────── Bookings ────────────────

    def create_booking(
        self, member_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/members/{member_id}/bookings", payload, headers)

    def list_bookings(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/members/{member_id}/bookings", headers=headers, params=params
        )

    def get_booking(self, member_id: str, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "GET", f"/members/{member_id}/bookings/{booking_id}", headers=headers
        )

    def confirm_booking(self, member_id: str, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/members/{member_id}/bookings/{booking_id}/confirm",
            headers=headers,
        )

    def check_in_booking(
        self,
        member_id: str,
        booking_id: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            f"/members/{member_id}/bookings/{booking_id}/check-in",
            payload,
            headers,
        )

    def cancel_booking(self, member_id: str, booking_id: str, headers: Dict[str, str]):
        return self._request(
            "POST",
            f"/members/{member_id}/bookings/{booking_id}/cancel",
            headers=headers,
        )

    # ──────────────── Coupons ────────────────

    def create_coupon(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/coupons", payload, headers)

    def list_coupons(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/coupons", headers=headers, params=params)

    def get_coupon(self, coupon_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/coupons/{coupon_id}", headers=headers)

    def verify_coupon(
        self, coupon_id: str, payload: Dict[str, Any], headers: Dict[str, str]
    ):
        return self._request("POST", f"/coupons/{coupon_id}/verify", payload, headers)

    # ──────────────── Referrals & wallet ────────────────

    def list_referrals(
        self, member_id: str, headers: Dict[str, str], params: Optional[Dict] = None
    ):
        return self._request(
            "GET", f"/members/{member_id}/referrals", headers=headers, params=params
        )

    def get_wallet(self, member_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/members/{member_id}/wallet", headers=headers)

    # ──────────────── Test-driving capabilities (BillingAdmin only) ────────────────

    def advance_clock(self, to_timestamp: str, headers: Dict[str, str]):
        return self._request(
            "POST", "/_clock/advance", {"to_timestamp": to_timestamp}, headers
        )

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", headers=headers)

    def emit_event(
        self,
        event_kind: str,
        event_payload: Dict[str, Any],
        headers: Dict[str, str],
    ):
        return self._request(
            "POST",
            "/_events/emit",
            {"event_kind": event_kind, "event_payload": event_payload},
            headers,
        )


api_client = ApiClient()
