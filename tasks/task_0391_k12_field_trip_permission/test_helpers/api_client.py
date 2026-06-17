"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient from the framework; the base _request() method is
inherited and handles the HTTP call + envelope plumbing.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Student ────────────────────────────────────────────────────────────
    def create_student(self, payload, headers):
        return self._request("POST", "/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    # ─── Guardian ───────────────────────────────────────────────────────────
    def create_guardian(self, payload, headers):
        return self._request("POST", "/guardians", payload, headers)

    def list_guardians(self, headers, params=None):
        return self._request("GET", "/guardians", headers=headers, params=params)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/guardians/{guardian_id}", headers=headers)

    # ─── Vehicle ────────────────────────────────────────────────────────────
    def create_vehicle(self, payload, headers):
        return self._request("POST", "/vehicles", payload, headers)

    def list_vehicles(self, headers, params=None):
        return self._request("GET", "/vehicles", headers=headers, params=params)

    def get_vehicle(self, vehicle_id, headers):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def retire_vehicle(self, vehicle_id, headers):
        return self._request("POST", f"/vehicles/{vehicle_id}/retire", headers=headers)

    # ─── ScholarshipPool ────────────────────────────────────────────────────
    def create_scholarship_pool(self, payload, headers):
        return self._request("POST", "/scholarship-pools", payload, headers)

    def list_scholarship_pools(self, headers, params=None):
        return self._request("GET", "/scholarship-pools", headers=headers, params=params)

    def get_scholarship_pool(self, pool_id, headers):
        return self._request("GET", f"/scholarship-pools/{pool_id}", headers=headers)

    # ─── ScholarshipGrant (read surface) ────────────────────────────────────
    def list_scholarship_grants(self, headers, params=None):
        return self._request("GET", "/scholarship-grants", headers=headers, params=params)

    def get_scholarship_grant(self, grant_id, headers):
        return self._request("GET", f"/scholarship-grants/{grant_id}", headers=headers)

    # ─── FieldTrip ──────────────────────────────────────────────────────────
    def create_field_trip(self, payload, headers):
        return self._request("POST", "/field-trips", payload, headers)

    def list_field_trips(self, headers, params=None):
        return self._request("GET", "/field-trips", headers=headers, params=params)

    def get_field_trip(self, trip_id, headers):
        return self._request("GET", f"/field-trips/{trip_id}", headers=headers)

    def submit_trip(self, trip_id, headers):
        return self._request("POST", f"/field-trips/{trip_id}/submit", headers=headers)

    def create_approval(self, trip_id, payload, headers):
        return self._request("POST", f"/field-trips/{trip_id}/approvals", payload, headers)

    def lock_roster(self, trip_id, payload, headers):
        return self._request("POST", f"/field-trips/{trip_id}/lock-roster", payload, headers)

    def start_trip(self, trip_id, headers):
        return self._request("POST", f"/field-trips/{trip_id}/start", headers=headers)

    def complete_trip(self, trip_id, headers):
        return self._request("POST", f"/field-trips/{trip_id}/complete", headers=headers)

    def cancel_trip(self, trip_id, headers):
        return self._request("POST", f"/field-trips/{trip_id}/cancel", headers=headers)

    # ─── TripApproval (read surface) ────────────────────────────────────────
    def list_trip_approvals(self, headers, params=None):
        return self._request("GET", "/trip-approvals", headers=headers, params=params)

    def get_trip_approval(self, approval_id, headers):
        return self._request("GET", f"/trip-approvals/{approval_id}", headers=headers)

    # ─── PermissionSlip ─────────────────────────────────────────────────────
    def create_permission_slip(self, trip_id, payload, headers):
        return self._request("POST", f"/field-trips/{trip_id}/permission-slips", payload, headers)

    def list_permission_slips(self, headers, params=None):
        return self._request("GET", "/permission-slips", headers=headers, params=params)

    def get_permission_slip(self, slip_id, headers):
        return self._request("GET", f"/permission-slips/{slip_id}", headers=headers)

    def sign_slip(self, trip_id, slip_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/permission-slips/{slip_id}/sign", headers=headers
        )

    def revoke_slip(self, trip_id, slip_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/permission-slips/{slip_id}/revoke", headers=headers
        )

    def pay_slip(self, trip_id, slip_id, payload, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/permission-slips/{slip_id}/pay", payload, headers
        )

    def withdraw_slip(self, trip_id, slip_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/permission-slips/{slip_id}/withdraw", headers=headers
        )

    # ─── EmergencyContact ───────────────────────────────────────────────────
    def create_emergency_contact(self, trip_id, slip_id, payload, headers):
        return self._request(
            "POST",
            f"/field-trips/{trip_id}/permission-slips/{slip_id}/emergency-contacts",
            payload,
            headers,
        )

    def list_emergency_contacts(self, headers, params=None):
        return self._request("GET", "/emergency-contacts", headers=headers, params=params)

    def get_emergency_contact(self, contact_id, headers):
        return self._request("GET", f"/emergency-contacts/{contact_id}", headers=headers)

    # ─── ScholarshipGrant (write) ───────────────────────────────────────────
    def create_scholarship_grant(self, trip_id, slip_id, payload, headers):
        return self._request(
            "POST",
            f"/field-trips/{trip_id}/permission-slips/{slip_id}/scholarship-grants",
            payload,
            headers,
        )

    def revoke_scholarship_grant(self, trip_id, slip_id, grant_id, headers):
        return self._request(
            "POST",
            f"/field-trips/{trip_id}/permission-slips/{slip_id}/scholarship-grants/{grant_id}/revoke",
            headers=headers,
        )

    # ─── Chaperone ──────────────────────────────────────────────────────────
    def create_chaperone(self, trip_id, payload, headers):
        return self._request("POST", f"/field-trips/{trip_id}/chaperones", payload, headers)

    def list_chaperones(self, headers, params=None):
        return self._request("GET", "/chaperones", headers=headers, params=params)

    def get_chaperone(self, chaperone_id, headers):
        return self._request("GET", f"/chaperones/{chaperone_id}", headers=headers)

    def confirm_chaperone(self, trip_id, chaperone_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/chaperones/{chaperone_id}/confirm", headers=headers
        )

    def clear_chaperone(self, trip_id, chaperone_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/chaperones/{chaperone_id}/clear", headers=headers
        )

    def withdraw_chaperone(self, trip_id, chaperone_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/chaperones/{chaperone_id}/withdraw", headers=headers
        )

    # ─── TransportBooking ───────────────────────────────────────────────────
    def create_transport_booking(self, trip_id, payload, headers):
        return self._request("POST", f"/field-trips/{trip_id}/transport-bookings", payload, headers)

    def list_transport_bookings(self, headers, params=None):
        return self._request("GET", "/transport-bookings", headers=headers, params=params)

    def get_transport_booking(self, booking_id, headers):
        return self._request("GET", f"/transport-bookings/{booking_id}", headers=headers)

    def confirm_booking(self, trip_id, booking_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/transport-bookings/{booking_id}/confirm", headers=headers
        )

    def cancel_booking(self, trip_id, booking_id, headers):
        return self._request(
            "POST", f"/field-trips/{trip_id}/transport-bookings/{booking_id}/cancel", headers=headers
        )

    # ─── FeeTransaction (read surface) ──────────────────────────────────────
    def list_fee_transactions(self, headers, params=None):
        return self._request("GET", "/fee-transactions", headers=headers, params=params)

    def get_fee_transaction(self, txn_id, headers):
        return self._request("GET", f"/fee-transactions/{txn_id}", headers=headers)

    # ─── Attendance ─────────────────────────────────────────────────────────
    def create_attendance(self, trip_id, payload, headers):
        return self._request("POST", f"/field-trips/{trip_id}/attendance", payload, headers)

    def list_attendance_records(self, headers, params=None):
        return self._request("GET", "/attendance-records", headers=headers, params=params)

    def get_attendance_record(self, record_id, headers):
        return self._request("GET", f"/attendance-records/{record_id}", headers=headers)


api_client = ApiClient()
