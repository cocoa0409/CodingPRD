"""API client: one method per endpoint defined in the Photography & Videography
Booking PRD (PRD §4).

Subclasses the framework's GenericApiClient; the base _request() is inherited.
All paths are rooted at the /studio prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Clients ----
    def create_client(self, payload, headers):
        return self._request("POST", "/studio/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/studio/clients/{client_id}", headers=headers)

    # ---- Photographers ----
    def create_photographer(self, payload, headers):
        return self._request("POST", "/studio/photographers", payload, headers)

    def get_photographer(self, photographer_id, headers):
        return self._request("GET", f"/studio/photographers/{photographer_id}", headers=headers)

    # ---- Session Packages ----
    def create_session_package(self, payload, headers):
        return self._request("POST", "/studio/session-packages", payload, headers)

    def get_session_package(self, package_id, headers):
        return self._request("GET", f"/studio/session-packages/{package_id}", headers=headers)

    def list_session_packages(self, headers, params=None):
        return self._request("GET", "/studio/session-packages", headers=headers, params=params)

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/studio/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/studio/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/studio/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/confirm", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/cancel", {}, headers)

    def close_booking(self, booking_id, headers):
        return self._request("POST", f"/studio/bookings/{booking_id}/close", {}, headers)

    # ---- Payments ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/studio/payments", payload, headers)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/studio/payments/{payment_id}", headers=headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/studio/payments", headers=headers, params=params)

    def settle_payment(self, payment_id, headers):
        return self._request("POST", f"/studio/payments/{payment_id}/settle", {}, headers)

    # ---- Contracts ----
    def create_contract(self, payload, headers):
        return self._request("POST", "/studio/contracts", payload, headers)

    def get_contract(self, contract_id, headers):
        return self._request("GET", f"/studio/contracts/{contract_id}", headers=headers)

    def list_contracts(self, headers, params=None):
        return self._request("GET", "/studio/contracts", headers=headers, params=params)

    def send_contract(self, contract_id, headers):
        return self._request("POST", f"/studio/contracts/{contract_id}/send", {}, headers)

    def sign_contract(self, contract_id, headers):
        return self._request("POST", f"/studio/contracts/{contract_id}/sign", {}, headers)

    # ---- Shoot Schedules ----
    def create_shoot_schedule(self, payload, headers):
        return self._request("POST", "/studio/shoot-schedules", payload, headers)

    def get_shoot_schedule(self, schedule_id, headers):
        return self._request("GET", f"/studio/shoot-schedules/{schedule_id}", headers=headers)

    def list_shoot_schedules(self, headers, params=None):
        return self._request("GET", "/studio/shoot-schedules", headers=headers, params=params)

    def reschedule_shoot_schedule(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/studio/shoot-schedules/{schedule_id}/reschedule", payload, headers
        )

    def complete_shoot_schedule(self, schedule_id, headers):
        return self._request("POST", f"/studio/shoot-schedules/{schedule_id}/complete", {}, headers)

    # ---- Second Shooter Assignments ----
    def create_second_shooter_assignment(self, schedule_id, payload, headers):
        return self._request(
            "POST", f"/studio/shoot-schedules/{schedule_id}/second-shooter-assignments",
            payload, headers,
        )

    def list_assignments_for_schedule(self, schedule_id, headers, params=None):
        return self._request(
            "GET", f"/studio/shoot-schedules/{schedule_id}/second-shooter-assignments",
            headers=headers, params=params,
        )

    def get_second_shooter_assignment(self, assignment_id, headers):
        return self._request(
            "GET", f"/studio/second-shooter-assignments/{assignment_id}", headers=headers
        )

    def list_second_shooter_assignments(self, headers, params=None):
        return self._request(
            "GET", "/studio/second-shooter-assignments", headers=headers, params=params
        )

    def release_second_shooter_assignment(self, assignment_id, headers):
        return self._request(
            "POST", f"/studio/second-shooter-assignments/{assignment_id}/release", {}, headers
        )

    # ---- Galleries ----
    def create_gallery(self, payload, headers):
        return self._request("POST", "/studio/galleries", payload, headers)

    def get_gallery(self, gallery_id, headers):
        return self._request("GET", f"/studio/galleries/{gallery_id}", headers=headers)

    def list_galleries(self, headers, params=None):
        return self._request("GET", "/studio/galleries", headers=headers, params=params)

    def upload_gallery(self, gallery_id, payload, headers):
        return self._request("POST", f"/studio/galleries/{gallery_id}/upload", payload, headers)

    def request_gallery_revision(self, gallery_id, headers):
        return self._request(
            "POST", f"/studio/galleries/{gallery_id}/request-revision", {}, headers
        )

    def finalize_gallery(self, gallery_id, headers):
        return self._request("POST", f"/studio/galleries/{gallery_id}/finalize", {}, headers)

    # ---- Proof Selections ----
    def create_proof_selection(self, gallery_id, payload, headers):
        return self._request(
            "POST", f"/studio/galleries/{gallery_id}/proof-selections", payload, headers
        )

    def list_proof_selections(self, gallery_id, headers, params=None):
        return self._request(
            "GET", f"/studio/galleries/{gallery_id}/proof-selections", headers=headers, params=params
        )

    # ---- Add-On Orders ----
    def create_add_on_order(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/studio/bookings/{booking_id}/add-on-orders", payload, headers
        )

    def list_add_on_orders(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/studio/bookings/{booking_id}/add-on-orders", headers=headers, params=params
        )

    def cancel_add_on_order(self, order_id, payload, headers):
        return self._request("POST", f"/studio/add-on-orders/{order_id}/cancel", payload, headers)

    # ---- License Grants ----
    def create_license_grant(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/studio/bookings/{booking_id}/license-grants", payload, headers
        )

    def list_license_grants(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/studio/bookings/{booking_id}/license-grants", headers=headers, params=params
        )

    def revoke_license_grant(self, grant_id, headers):
        return self._request("POST", f"/studio/license-grants/{grant_id}/revoke", {}, headers)

    # ---- Test-driving clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/studio/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )


api_client = ApiClient()
