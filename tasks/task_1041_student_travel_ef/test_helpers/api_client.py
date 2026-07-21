"""API client: one method per endpoint defined in the PRD.

Subclasses the framework's GenericApiClient; the base _request() handles
envelope parsing, base URL, and header injection.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ---- Tour ----
    def create_tour(self, payload, headers):
        return self._request("POST", "/tours", payload, headers)

    def get_tour(self, tour_id, headers):
        return self._request("GET", f"/tours/{tour_id}", headers=headers)

    # ---- GroupLeader ----
    def create_group_leader(self, payload, headers):
        return self._request("POST", "/group-leaders", payload, headers)

    def get_group_leader(self, gl_id, headers):
        return self._request("GET", f"/group-leaders/{gl_id}", headers=headers)

    # ---- Departure ----
    def create_departure(self, payload, headers):
        return self._request("POST", "/departures", payload, headers)

    def get_departure(self, dep_id, headers):
        return self._request("GET", f"/departures/{dep_id}", headers=headers)

    def list_departures(self, headers, params=None):
        return self._request("GET", "/departures", headers=headers, params=params)

    def get_departure_summary(self, dep_id, headers):
        return self._request("GET", f"/departures/{dep_id}/summary", headers=headers)

    def open_departure(self, dep_id, headers):
        return self._request("POST", f"/departures/{dep_id}/open", {}, headers)

    def guarantee_departure(self, dep_id, headers):
        return self._request("POST", f"/departures/{dep_id}/guarantee", {}, headers)

    def depart_departure(self, dep_id, headers):
        return self._request("POST", f"/departures/{dep_id}/depart", {}, headers)

    def cancel_departure(self, dep_id, headers, payload=None):
        return self._request("POST", f"/departures/{dep_id}/cancel", payload or {}, headers)

    def list_departure_enrollments(self, dep_id, headers, params=None):
        return self._request("GET", f"/departures/{dep_id}/enrollments", headers=headers, params=params)

    def list_departure_chaperones(self, dep_id, headers, params=None):
        return self._request("GET", f"/departures/{dep_id}/chaperones", headers=headers, params=params)

    def list_departure_rooming(self, dep_id, headers, params=None):
        return self._request("GET", f"/departures/{dep_id}/rooming", headers=headers, params=params)

    def list_departure_supplier_bookings(self, dep_id, headers, params=None):
        return self._request("GET", f"/departures/{dep_id}/supplier-bookings", headers=headers, params=params)

    # ---- Enrollment ----
    def create_enrollment(self, payload, headers):
        return self._request("POST", "/enrollments", payload, headers)

    def get_enrollment(self, enr_id, headers):
        return self._request("GET", f"/enrollments/{enr_id}", headers=headers)

    def confirm_enrollment(self, enr_id, headers):
        return self._request("POST", f"/enrollments/{enr_id}/confirm", {}, headers)

    def cancel_enrollment(self, enr_id, headers, payload=None):
        return self._request("POST", f"/enrollments/{enr_id}/cancel", payload or {}, headers)

    def rebook_enrollment(self, enr_id, payload, headers):
        return self._request("POST", f"/enrollments/{enr_id}/rebook", payload, headers)

    def get_refund_quote(self, enr_id, headers):
        return self._request("GET", f"/enrollments/{enr_id}/refund-quote", headers=headers)

    def list_enrollment_payment_plans(self, enr_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enr_id}/payment-plan", headers=headers, params=params)

    def list_enrollment_permission_forms(self, enr_id, headers, params=None):
        return self._request("GET", f"/enrollments/{enr_id}/permission-form", headers=headers, params=params)

    # ---- PaymentPlan / Payment ----
    def create_payment_plan(self, payload, headers):
        return self._request("POST", "/payment-plans", payload, headers)

    def get_payment_plan(self, plan_id, headers):
        return self._request("GET", f"/payment-plans/{plan_id}", headers=headers)

    def list_payment_plan_payments(self, plan_id, headers, params=None):
        return self._request("GET", f"/payment-plans/{plan_id}/payments", headers=headers, params=params)

    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    # ---- PermissionForm ----
    def create_permission_form(self, payload, headers):
        return self._request("POST", "/permission-forms", payload, headers)

    def get_permission_form(self, pf_id, headers):
        return self._request("GET", f"/permission-forms/{pf_id}", headers=headers)

    def submit_permission_form(self, pf_id, headers):
        return self._request("POST", f"/permission-forms/{pf_id}/submit", {}, headers)

    def review_permission_form(self, pf_id, payload, headers):
        return self._request("POST", f"/permission-forms/{pf_id}/review", payload, headers)

    # ---- Chaperone ----
    def create_chaperone(self, payload, headers):
        return self._request("POST", "/chaperones", payload, headers)

    def get_chaperone(self, chap_id, headers):
        return self._request("GET", f"/chaperones/{chap_id}", headers=headers)

    # ---- RoomingAssignment ----
    def create_rooming_assignment(self, payload, headers):
        return self._request("POST", "/rooming-assignments", payload, headers)

    def get_rooming_assignment(self, room_id, headers):
        return self._request("GET", f"/rooming-assignments/{room_id}", headers=headers)

    def add_rooming_member(self, room_id, payload, headers):
        return self._request("POST", f"/rooming-assignments/{room_id}/members", payload, headers)

    def finalize_rooming_assignment(self, room_id, headers):
        return self._request("POST", f"/rooming-assignments/{room_id}/finalize", {}, headers)

    # ---- Supplier / SupplierBooking ----
    def create_supplier(self, payload, headers):
        return self._request("POST", "/suppliers", payload, headers)

    def get_supplier(self, sup_id, headers):
        return self._request("GET", f"/suppliers/{sup_id}", headers=headers)

    def list_supplier_bookings(self, sup_id, headers, params=None):
        return self._request("GET", f"/suppliers/{sup_id}/bookings", headers=headers, params=params)

    def create_supplier_booking(self, payload, headers):
        return self._request("POST", "/supplier-bookings", payload, headers)

    def get_supplier_booking(self, booking_id, headers):
        return self._request("GET", f"/supplier-bookings/{booking_id}", headers=headers)

    def confirm_supplier_booking(self, booking_id, headers):
        return self._request("POST", f"/supplier-bookings/{booking_id}/confirm", {}, headers)

    def cancel_supplier_booking(self, booking_id, headers):
        return self._request("POST", f"/supplier-bookings/{booking_id}/cancel", {}, headers)


api_client = ApiClient()
