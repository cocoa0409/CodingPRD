"""API client: one method per endpoint defined in the PRD (Travel Agency Tour Booking API)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Agency ──────────────────────────────────────────────────────────
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    def set_clock(self, agency_id, payload, headers):
        return self._request("POST", f"/agencies/{agency_id}/_clock/set", payload, headers)

    # ─── Customer ────────────────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/agencies/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/agencies/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/agencies/customers", headers=headers, params=params)

    # ─── Supplier ────────────────────────────────────────────────────────
    def create_supplier(self, payload, headers):
        return self._request("POST", "/agencies/suppliers", payload, headers)

    def get_supplier(self, supplier_id, headers):
        return self._request("GET", f"/agencies/suppliers/{supplier_id}", headers=headers)

    def list_suppliers(self, headers, params=None):
        return self._request("GET", "/agencies/suppliers", headers=headers, params=params)

    # ─── Tour Package ────────────────────────────────────────────────────
    def create_tour_package(self, payload, headers):
        return self._request("POST", "/agencies/tour-packages", payload, headers)

    def get_tour_package(self, package_id, headers):
        return self._request("GET", f"/agencies/tour-packages/{package_id}", headers=headers)

    def list_tour_packages(self, headers, params=None):
        return self._request("GET", "/agencies/tour-packages", headers=headers, params=params)

    def publish_tour_package(self, package_id, headers):
        return self._request("POST", f"/agencies/tour-packages/{package_id}/publish", {}, headers)

    def retire_tour_package(self, package_id, headers):
        return self._request("POST", f"/agencies/tour-packages/{package_id}/retire", {}, headers)

    # ─── Booking ─────────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/agencies/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/agencies/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/agencies/bookings", headers=headers, params=params)

    def reserve_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/agencies/bookings/{booking_id}/reserve", payload, headers)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/agencies/bookings/{booking_id}/confirm", payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/agencies/bookings/{booking_id}/cancel", payload, headers)

    # ─── Traveler ────────────────────────────────────────────────────────
    def add_traveler(self, booking_id, payload, headers):
        return self._request("POST", f"/agencies/bookings/{booking_id}/travelers", payload, headers)

    def get_traveler(self, traveler_id, headers):
        return self._request("GET", f"/agencies/travelers/{traveler_id}", headers=headers)

    def list_travelers(self, headers, params=None):
        return self._request("GET", "/agencies/travelers", headers=headers, params=params)

    # ─── Booking Component ───────────────────────────────────────────────
    def create_component(self, payload, headers):
        return self._request("POST", "/agencies/components", payload, headers)

    def get_component(self, component_id, headers):
        return self._request("GET", f"/agencies/components/{component_id}", headers=headers)

    def list_components(self, headers, params=None):
        return self._request("GET", "/agencies/components", headers=headers, params=params)

    def confirm_component(self, component_id, headers):
        return self._request("POST", f"/agencies/components/{component_id}/confirm", {}, headers)

    def reject_component(self, component_id, headers):
        return self._request("POST", f"/agencies/components/{component_id}/reject", {}, headers)

    # ─── Insurance Policy ────────────────────────────────────────────────
    def create_insurance_policy(self, payload, headers):
        return self._request("POST", "/agencies/insurance-policies", payload, headers)

    def get_insurance_policy(self, policy_id, headers):
        return self._request("GET", f"/agencies/insurance-policies/{policy_id}", headers=headers)

    def list_insurance_policies(self, headers, params=None):
        return self._request("GET", "/agencies/insurance-policies", headers=headers, params=params)

    # ─── Payment Milestone ───────────────────────────────────────────────
    def get_milestone(self, milestone_id, headers):
        return self._request("GET", f"/agencies/milestones/{milestone_id}", headers=headers)

    def list_milestones(self, headers, params=None):
        return self._request("GET", "/agencies/milestones", headers=headers, params=params)

    # ─── Payment ─────────────────────────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/agencies/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/agencies/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/agencies/payments", headers=headers, params=params)

    # ─── Cancellation Record ─────────────────────────────────────────────
    def get_cancellation_record(self, record_id, headers):
        return self._request("GET", f"/agencies/cancellation-records/{record_id}", headers=headers)

    def list_cancellation_records(self, headers, params=None):
        return self._request("GET", "/agencies/cancellation-records", headers=headers, params=params)


api_client = ApiClient()
