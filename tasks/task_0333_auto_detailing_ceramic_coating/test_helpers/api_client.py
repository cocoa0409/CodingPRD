"""API client: one method per endpoint defined in the PRD.

Subclasses GenericApiClient; the base _request() handles the HTTP envelope.
All paths are rooted at the /detailing API prefix.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Customers ───────────────────────────────────────────────
    def create_customer(self, payload, headers):
        return self._request("POST", "/detailing/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/detailing/customers/{customer_id}", headers=headers)

    def list_customers(self, headers, params=None):
        return self._request("GET", "/detailing/customers", headers=headers, params=params)

    def list_customer_appointments(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/detailing/customers/{customer_id}/appointments",
            headers=headers, params=params,
        )

    def list_customer_memberships(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/detailing/customers/{customer_id}/memberships",
            headers=headers, params=params,
        )

    # ─── Catalog / config ────────────────────────────────────────
    def create_package(self, payload, headers):
        return self._request("POST", "/detailing/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/detailing/packages", headers=headers, params=params)

    def create_vehicle_size_rate(self, payload, headers):
        return self._request("POST", "/detailing/vehicle-size-rates", payload, headers)

    def list_vehicle_size_rates(self, headers, params=None):
        return self._request("GET", "/detailing/vehicle-size-rates", headers=headers, params=params)

    def create_addon(self, payload, headers):
        return self._request("POST", "/detailing/addons", payload, headers)

    def list_addons(self, headers, params=None):
        return self._request("GET", "/detailing/addons", headers=headers, params=params)

    # ─── Resources ────────────────────────────────────────────────
    def create_service_bay(self, payload, headers):
        return self._request("POST", "/detailing/service-bays", payload, headers)

    def get_service_bay(self, bay_id, headers):
        return self._request("GET", f"/detailing/service-bays/{bay_id}", headers=headers)

    def list_service_bays(self, headers, params=None):
        return self._request("GET", "/detailing/service-bays", headers=headers, params=params)

    def set_bay_status(self, bay_id, payload, headers):
        return self._request(
            "POST", f"/detailing/service-bays/{bay_id}/set-status", payload, headers,
        )

    def create_mobile_unit(self, payload, headers):
        return self._request("POST", "/detailing/mobile-units", payload, headers)

    def get_mobile_unit(self, unit_id, headers):
        return self._request("GET", f"/detailing/mobile-units/{unit_id}", headers=headers)

    def list_mobile_units(self, headers, params=None):
        return self._request("GET", "/detailing/mobile-units", headers=headers, params=params)

    # ─── Memberships ──────────────────────────────────────────────
    def create_membership(self, payload, headers):
        return self._request("POST", "/detailing/memberships", payload, headers)

    def get_membership(self, membership_id, headers):
        return self._request("GET", f"/detailing/memberships/{membership_id}", headers=headers)

    def activate_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/detailing/memberships/{membership_id}/activate", {}, headers,
        )

    def renew_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/detailing/memberships/{membership_id}/renew", {}, headers,
        )

    def mark_membership_past_due(self, membership_id, headers):
        return self._request(
            "POST", f"/detailing/memberships/{membership_id}/mark-past-due", {}, headers,
        )

    def lapse_membership(self, membership_id, headers):
        return self._request(
            "POST", f"/detailing/memberships/{membership_id}/lapse", {}, headers,
        )

    def cancel_membership(self, membership_id, payload, headers):
        return self._request(
            "POST", f"/detailing/memberships/{membership_id}/cancel", payload, headers,
        )

    # ─── Appointments ─────────────────────────────────────────────
    def create_appointment(self, payload, headers):
        return self._request("POST", "/detailing/appointments", payload, headers)

    def get_appointment(self, appointment_id, headers):
        return self._request("GET", f"/detailing/appointments/{appointment_id}", headers=headers)

    def list_appointments(self, headers, params=None):
        return self._request("GET", "/detailing/appointments", headers=headers, params=params)

    def add_appointment_addon(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/addons", payload, headers,
        )

    def list_appointment_addons(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/detailing/appointments/{appointment_id}/addons",
            headers=headers, params=params,
        )

    def set_addon_line_status(self, appointment_id, addon_code, payload, headers):
        return self._request(
            "POST",
            f"/detailing/appointments/{appointment_id}/addons/{addon_code}/set-line-status",
            payload, headers,
        )

    def add_photo(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/photos", payload, headers,
        )

    def list_photos(self, appointment_id, headers, params=None):
        return self._request(
            "GET", f"/detailing/appointments/{appointment_id}/photos",
            headers=headers, params=params,
        )

    def check_in(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/check-in", {}, headers,
        )

    def start_prep(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/start-prep", {}, headers,
        )

    def start_service(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/start-service", {}, headers,
        )

    def finish_service(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/finish-service", {}, headers,
        )

    def finish_cure(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/finish-cure", {}, headers,
        )

    def release(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/release", {}, headers,
        )

    def cancel_appointment(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/cancel", {}, headers,
        )

    def mark_no_show(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/mark-no-show", {}, headers,
        )

    def capture_deposit(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/capture-deposit", payload, headers,
        )

    def pay(self, appointment_id, payload, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/pay", payload, headers,
        )

    def refund(self, appointment_id, headers):
        return self._request(
            "POST", f"/detailing/appointments/{appointment_id}/refund", {}, headers,
        )

    # ─── Rework guarantee ─────────────────────────────────────────
    def create_rework_claim(self, payload, headers):
        return self._request("POST", "/detailing/rework-claims", payload, headers)

    def get_rework_claim(self, claim_id, headers):
        return self._request("GET", f"/detailing/rework-claims/{claim_id}", headers=headers)

    def list_rework_claims(self, headers, params=None):
        return self._request("GET", "/detailing/rework-claims", headers=headers, params=params)

    def approve_rework_claim(self, claim_id, payload, headers):
        return self._request(
            "POST", f"/detailing/rework-claims/{claim_id}/approve", payload, headers,
        )

    def reject_rework_claim(self, claim_id, headers):
        return self._request(
            "POST", f"/detailing/rework-claims/{claim_id}/reject", {}, headers,
        )

    # ─── Test-driving clock ───────────────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/detailing/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers,
        )


api_client = ApiClient()
