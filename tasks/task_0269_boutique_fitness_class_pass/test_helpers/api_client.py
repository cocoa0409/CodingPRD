"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Studios & rooms ---------------------------------------------------
    def create_studio(self, payload, headers):
        return self._request("POST", "/studios", payload, headers)

    def get_studio(self, studio_id, headers):
        return self._request("GET", f"/studios/{studio_id}", headers=headers)

    def close_studio(self, studio_id, headers):
        return self._request("POST", f"/studios/{studio_id}/close", headers=headers)

    def create_room(self, studio_id, payload, headers):
        return self._request("POST", f"/studios/{studio_id}/rooms", payload, headers)

    def list_rooms(self, studio_id, headers, params=None):
        return self._request("GET", f"/studios/{studio_id}/rooms", headers=headers, params=params)

    def retire_room(self, room_id, headers):
        return self._request("POST", f"/rooms/{room_id}/retire", headers=headers)

    # --- Instructors -------------------------------------------------------
    def create_instructor(self, payload, headers):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id, headers):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def list_instructors(self, headers, params=None):
        return self._request("GET", "/instructors", headers=headers, params=params)

    def deactivate_instructor(self, instructor_id, headers):
        return self._request("POST", f"/instructors/{instructor_id}/deactivate", headers=headers)

    # --- Class templates ---------------------------------------------------
    def create_class_template(self, payload, headers):
        return self._request("POST", "/class-templates", payload, headers)

    def get_class_template(self, template_id, headers):
        return self._request("GET", f"/class-templates/{template_id}", headers=headers)

    # --- Package plans & memberships --------------------------------------
    def create_package_plan(self, payload, headers):
        return self._request("POST", "/package-plans", payload, headers)

    def get_package_plan(self, plan_id, headers):
        return self._request("GET", f"/package-plans/{plan_id}", headers=headers)

    def create_member(self, payload, headers):
        return self._request("POST", "/members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/members", headers=headers, params=params)

    def create_membership(self, member_id, payload, headers):
        return self._request("POST", f"/members/{member_id}/memberships", payload, headers)

    def list_member_memberships(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/memberships", headers=headers, params=params)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/memberships", headers=headers, params=params)

    def list_membership_wallet_entries(self, membership_id, headers, params=None):
        return self._request("GET", f"/memberships/{membership_id}/wallet-entries", headers=headers, params=params)

    def freeze_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/memberships/{membership_id}/freeze", payload, headers)

    def unfreeze_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/unfreeze", headers=headers)

    def renew_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/renew", headers=headers)

    def cancel_membership(self, membership_id, headers):
        return self._request("POST", f"/memberships/{membership_id}/cancel", headers=headers)

    # --- Fees --------------------------------------------------------------
    def list_member_fees(self, member_id, headers, params=None):
        return self._request("GET", f"/members/{member_id}/fees", headers=headers, params=params)

    def waive_fee(self, fee_id, headers):
        return self._request("POST", f"/fees/{fee_id}/waive", headers=headers)

    def get_fee(self, fee_id, headers):
        return self._request("GET", f"/fees/{fee_id}", headers=headers)

    def list_fees(self, headers, params=None):
        return self._request("GET", "/fees", headers=headers, params=params)

    # --- Sessions & reservations ------------------------------------------
    def create_session(self, payload, headers):
        return self._request("POST", "/sessions", payload, headers)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/sessions/{session_id}", headers=headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/sessions", headers=headers, params=params)

    def update_session(self, session_id, payload, headers):
        return self._request("PATCH", f"/sessions/{session_id}", payload, headers)

    def publish_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/publish", headers=headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/sessions/{session_id}/cancel", headers=headers)

    def create_reservation(self, session_id, payload, headers):
        return self._request("POST", f"/sessions/{session_id}/reservations", payload, headers)

    def list_session_reservations(self, session_id, headers, params=None):
        return self._request("GET", f"/sessions/{session_id}/reservations", headers=headers, params=params)

    def get_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reservations/{reservation_id}", headers=headers)

    def list_reservation_wallet_entries(self, reservation_id, headers, params=None):
        return self._request("GET", f"/reservations/{reservation_id}/wallet-entries", headers=headers, params=params)

    def list_reservations(self, headers, params=None):
        return self._request("GET", "/reservations", headers=headers, params=params)

    def cancel_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/cancel", headers=headers)

    def check_in_reservation(self, reservation_id, headers):
        return self._request("POST", f"/reservations/{reservation_id}/check_in", headers=headers)

    # --- Test-driving / ops endpoints -------------------------------------
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def capture_payment(self, payload, headers):
        return self._request("POST", "/_payments/capture", payload, headers)

    def run_completion(self, headers):
        return self._request("POST", "/_ops/run_completion", headers=headers)

    def run_expiry(self, headers):
        return self._request("POST", "/_ops/run_expiry", headers=headers)


api_client = ApiClient()
