"""API client: one method per endpoint defined in the Yoga & Pilates Studio PRD §4."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Members ----
    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def list_member_reservations(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/reservations", headers=headers, params=params)

    def list_member_entitlements(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/entitlements", headers=headers, params=params)

    def list_member_fee_charges(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/fee-charges", headers=headers, params=params)

    def list_member_enrollments(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/enrollments", headers=headers, params=params)

    # ---- Rooms ----
    def create_room(self, payload, headers):
        return self._request("POST", "/rooms", payload, headers)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/rooms/{room_id}", headers=headers)

    def update_room(self, room_id, payload, headers):
        return self._request("PATCH", f"/rooms/{room_id}", payload, headers)

    def list_room_class_sessions(self, room_id, headers, params=None):
        return self._request("GET", f"/rooms/{room_id}/class-sessions", headers=headers, params=params)

    def list_room_workshops(self, room_id, headers, params=None):
        return self._request("GET", f"/rooms/{room_id}/workshops", headers=headers, params=params)

    # ---- Teachers ----
    def create_teacher(self, payload, headers):
        return self._request("POST", "/teachers", payload, headers)

    def get_teacher(self, teacher_id, headers):
        return self._request("GET", f"/teachers/{teacher_id}", headers=headers)

    def list_teacher_class_sessions(self, teacher_id, headers, params=None):
        return self._request("GET", f"/teachers/{teacher_id}/class-sessions", headers=headers, params=params)

    def list_teacher_workshops(self, teacher_id, headers, params=None):
        return self._request("GET", f"/teachers/{teacher_id}/workshops", headers=headers, params=params)

    # ---- Intro Offers ----
    def create_intro_offer(self, payload, headers):
        return self._request("POST", "/intro-offers", payload, headers)

    def get_intro_offer(self, offer_id, headers):
        return self._request("GET", f"/intro-offers/{offer_id}", headers=headers)

    def list_intro_offers(self, headers, params=None):
        return self._request("GET", "/intro-offers", headers=headers, params=params)

    def list_intro_offer_entitlements(self, offer_id, headers, params=None):
        return self._request("GET", f"/intro-offers/{offer_id}/entitlements", headers=headers, params=params)

    # ---- Class Sessions ----
    def create_class_session(self, payload, headers):
        return self._request("POST", "/class-sessions", payload, headers)

    def get_class_session(self, session_id, headers):
        return self._request("GET", f"/class-sessions/{session_id}", headers=headers)

    def list_class_sessions(self, headers, params=None):
        return self._request("GET", "/class-sessions", headers=headers, params=params)

    def publish_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/publish", {}, headers)

    def start_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/start", {}, headers)

    def complete_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/complete", {}, headers)

    def cancel_class_session(self, session_id, headers):
        return self._request("POST", f"/class-sessions/{session_id}/cancel", {}, headers)

    def list_class_session_reservations(self, session_id, headers, params=None):
        return self._request("GET", f"/class-sessions/{session_id}/reservations", headers=headers, params=params)

    # ---- Entitlements ----
    def create_entitlement(self, payload, headers):
        return self._request("POST", "/entitlements", payload, headers)

    def get_entitlement(self, entitlement_id, headers):
        return self._request("GET", f"/entitlements/{entitlement_id}", headers=headers)

    def activate_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/entitlements/{entitlement_id}/activate", {}, headers)

    def freeze_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/entitlements/{entitlement_id}/freeze", {}, headers)

    def thaw_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/entitlements/{entitlement_id}/thaw", {}, headers)

    def cancel_entitlement(self, entitlement_id, headers):
        return self._request("POST", f"/entitlements/{entitlement_id}/cancel", {}, headers)

    # ---- Reservations ----
    def create_reservation(self, payload, headers):
        return self._request("POST", "/reservations", payload, headers)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check-in", {}, headers)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", {}, headers)

    # ---- Workshops ----
    def create_workshop(self, payload, headers):
        return self._request("POST", "/workshops", payload, headers)

    def get_workshop(self, workshop_id, headers):
        return self._request("GET", f"/workshops/{workshop_id}", headers=headers)

    def list_workshops(self, headers, params=None):
        return self._request("GET", "/workshops", headers=headers, params=params)

    def publish_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/publish", {}, headers)

    def close_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/close", {}, headers)

    def cancel_workshop(self, workshop_id, headers):
        return self._request("POST", f"/workshops/{workshop_id}/cancel", {}, headers)

    def list_workshop_enrollments(self, workshop_id, headers, params=None):
        return self._request("GET", f"/workshops/{workshop_id}/enrollments", headers=headers, params=params)

    # ---- Enrollments ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def confirm_enrollment(self, enrollment_id, payload, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/confirm", payload, headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", {}, headers)

    # ---- Fee Charges ----
    def get_fee_charge(self, fee_charge_id, headers):
        return self._request("GET", f"/fee-charges/{fee_charge_id}", headers=headers)

    def list_fee_charges(self, headers, params=None):
        return self._request("GET", "/fee-charges", headers=headers, params=params)

    def settle_fee_charge(self, fee_charge_id, payload, headers):
        return self._request("POST", f"/fee-charges/{fee_charge_id}/settle", payload, headers)

    # ---- Ops + Clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    def run_ops(self, headers):
        return self._request("POST", "/_ops/run", {}, headers)


api_client = ApiClient()
