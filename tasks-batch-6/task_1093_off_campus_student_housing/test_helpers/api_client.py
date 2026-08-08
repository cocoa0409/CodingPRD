"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- logical clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)

    # --- universities ---
    def create_university(self, payload, headers):
        return self._request("POST", "/universities", payload, headers)

    def get_university(self, university_id, headers):
        return self._request("GET", f"/universities/{university_id}", headers=headers)

    # --- properties ---
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def list_property(self, property_id, headers):
        return self._request("POST", f"/properties/{property_id}/list", {}, headers)

    def suspend_property(self, property_id, headers, payload=None):
        return self._request("POST", f"/properties/{property_id}/suspend", payload or {}, headers)

    def reinstate_property(self, property_id, headers):
        return self._request("POST", f"/properties/{property_id}/reinstate", {}, headers)

    # --- units ---
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # --- students ---
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def request_verification(self, student_id, headers):
        return self._request("POST", f"/students/{student_id}/verification-requests", {}, headers)

    def decide_verification(self, student_id, payload, headers):
        return self._request("POST", f"/students/{student_id}/verification-decision", payload, headers)

    # --- roommate groups ---
    def create_roommate_group(self, payload, headers):
        return self._request("POST", "/roommate-groups", payload, headers)

    def get_roommate_group(self, group_id, headers):
        return self._request("GET", f"/roommate-groups/{group_id}", headers=headers)

    def list_roommate_groups(self, headers, params=None):
        return self._request("GET", "/roommate-groups", headers=headers, params=params)

    def invite_to_group(self, group_id, payload, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/invitations", payload, headers)

    def lock_group(self, group_id, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/lock", {}, headers)

    def place_group(self, group_id, payload, headers):
        return self._request("POST", f"/roommate-groups/{group_id}/place", payload, headers)

    # --- group memberships ---
    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/group-memberships/{membership_id}", headers=headers)

    def list_memberships(self, headers, params=None):
        return self._request("GET", "/group-memberships", headers=headers, params=params)

    def respond_membership(self, membership_id, payload, headers):
        return self._request("POST", f"/group-memberships/{membership_id}/respond", payload, headers)

    # --- leases ---
    def create_lease(self, payload, headers):
        return self._request("POST", "/leases", payload, headers)

    def get_lease(self, lease_id, headers):
        return self._request("GET", f"/leases/{lease_id}", headers=headers)

    def list_leases(self, headers, params=None):
        return self._request("GET", "/leases", headers=headers, params=params)

    def submit_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/submit", {}, headers)

    def sign_lease(self, lease_id, headers):
        return self._request("POST", f"/leases/{lease_id}/sign", {}, headers)

    def cancel_lease(self, lease_id, headers, payload=None):
        return self._request("POST", f"/leases/{lease_id}/cancel", payload or {}, headers)

    def terminate_lease(self, lease_id, headers, payload=None):
        return self._request("POST", f"/leases/{lease_id}/terminate", payload or {}, headers)

    def renew_lease(self, lease_id, payload, headers):
        return self._request("POST", f"/leases/{lease_id}/renew", payload, headers)

    def list_lease_installments(self, lease_id, headers, params=None):
        return self._request("GET", f"/leases/{lease_id}/installments", headers=headers, params=params)

    # --- installments ---
    def pay_installment(self, installment_id, payload, headers):
        return self._request("POST", f"/installments/{installment_id}/pay", payload, headers)

    # --- guarantor applications ---
    def create_guarantor_application(self, payload, headers):
        return self._request("POST", "/guarantor-applications", payload, headers)

    def get_guarantor_application(self, app_id, headers):
        return self._request("GET", f"/guarantor-applications/{app_id}", headers=headers)

    def list_guarantor_applications(self, headers, params=None):
        return self._request("GET", "/guarantor-applications", headers=headers, params=params)

    def review_guarantor_application(self, app_id, payload, headers):
        return self._request("POST", f"/guarantor-applications/{app_id}/review", payload, headers)

    def resubmit_guarantor_application(self, app_id, payload, headers):
        return self._request("POST", f"/guarantor-applications/{app_id}/resubmit", payload, headers)

    # --- sublets ---
    def create_sublet(self, payload, headers):
        return self._request("POST", "/sublets", payload, headers)

    def get_sublet(self, sublet_id, headers):
        return self._request("GET", f"/sublets/{sublet_id}", headers=headers)

    def list_sublets(self, headers, params=None):
        return self._request("GET", "/sublets", headers=headers, params=params)

    def decide_sublet(self, sublet_id, payload, headers):
        return self._request("POST", f"/sublets/{sublet_id}/decision", payload, headers)

    # --- amenities ---
    def create_amenity(self, payload, headers):
        return self._request("POST", "/amenities", payload, headers)

    def get_amenity(self, amenity_id, headers):
        return self._request("GET", f"/amenities/{amenity_id}", headers=headers)

    def list_amenities(self, headers, params=None):
        return self._request("GET", "/amenities", headers=headers, params=params)

    # --- amenity assignments ---
    def create_amenity_assignment(self, payload, headers):
        return self._request("POST", "/amenity-assignments", payload, headers)

    def get_amenity_assignment(self, assignment_id, headers):
        return self._request("GET", f"/amenity-assignments/{assignment_id}", headers=headers)

    def list_amenity_assignments(self, headers, params=None):
        return self._request("GET", "/amenity-assignments", headers=headers, params=params)

    def release_amenity_assignment(self, assignment_id, headers):
        return self._request("POST", f"/amenity-assignments/{assignment_id}/release", {}, headers)

    # --- payouts ---
    def create_payout(self, payload, headers):
        return self._request("POST", "/payouts", payload, headers)

    def get_payout(self, payout_id, headers):
        return self._request("GET", f"/payouts/{payout_id}", headers=headers)

    def list_payouts(self, headers, params=None):
        return self._request("GET", "/payouts", headers=headers, params=params)

    def decide_payout(self, payout_id, payload, headers):
        return self._request("POST", f"/payouts/{payout_id}/decision", payload, headers)

    def pay_payout(self, payout_id, headers):
        return self._request("POST", f"/payouts/{payout_id}/pay", {}, headers)

    def reverse_payout(self, payout_id, headers, payload=None):
        return self._request("POST", f"/payouts/{payout_id}/reverse", payload or {}, headers)

    # --- generic raw request (for unauth / negative header tests) ---
    def raw(self, method, path, payload=None, headers=None, params=None):
        return self._request(method, path, payload, headers, params)


api_client = ApiClient()
