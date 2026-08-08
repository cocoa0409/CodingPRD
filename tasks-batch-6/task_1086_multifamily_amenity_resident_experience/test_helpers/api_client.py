"""API client: one method per endpoint defined in the PRD.

Subclasses the framework ``GenericApiClient``; the base ``_request`` handles
the HTTP call and envelope transport. List endpoints accept a ``params`` dict
for filters and pagination.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Properties ----
    def create_property(self, payload, headers):
        return self._request("POST", "/properties", payload, headers)

    def get_property(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}", headers=headers)

    def list_properties(self, headers, params=None):
        return self._request("GET", "/properties", headers=headers, params=params)

    def get_property_report(self, property_id, headers):
        return self._request("GET", f"/properties/{property_id}/report", headers=headers)

    # ---- Units ----
    def create_unit(self, payload, headers):
        return self._request("POST", "/units", payload, headers)

    def get_unit(self, unit_id, headers):
        return self._request("GET", f"/units/{unit_id}", headers=headers)

    def list_units(self, headers, params=None):
        return self._request("GET", "/units", headers=headers, params=params)

    # ---- Residents ----
    def create_resident(self, payload, headers):
        return self._request("POST", "/residents", payload, headers)

    def get_resident(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}", headers=headers)

    def list_residents(self, headers, params=None):
        return self._request("GET", "/residents", headers=headers, params=params)

    def get_resident_ledger(self, resident_id, headers, params=None):
        return self._request("GET", f"/residents/{resident_id}/ledger", headers=headers, params=params)

    def get_resident_retention(self, resident_id, headers):
        return self._request("GET", f"/residents/{resident_id}/retention", headers=headers)

    def create_rent_charge(self, resident_id, payload, headers):
        return self._request("POST", f"/residents/{resident_id}/rent-charges", payload, headers)

    # ---- Payments ----
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    # ---- Amenities ----
    def create_amenity(self, payload, headers):
        return self._request("POST", "/amenities", payload, headers)

    def get_amenity(self, amenity_id, headers):
        return self._request("GET", f"/amenities/{amenity_id}", headers=headers)

    def list_amenities(self, headers, params=None):
        return self._request("GET", "/amenities", headers=headers, params=params)

    # ---- Amenity Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/amenity-bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/amenity-bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/amenity-bookings", headers=headers, params=params)

    def check_in_booking(self, booking_id, headers):
        return self._request("POST", f"/amenity-bookings/{booking_id}/check-in", {}, headers)

    def check_out_booking(self, booking_id, headers):
        return self._request("POST", f"/amenity-bookings/{booking_id}/check-out", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/amenity-bookings/{booking_id}/cancel", {}, headers)

    def mark_no_show_booking(self, booking_id, headers):
        return self._request("POST", f"/amenity-bookings/{booking_id}/mark-no-show", {}, headers)

    # ---- Community Events ----
    def create_event(self, payload, headers):
        return self._request("POST", "/events", payload, headers)

    def get_event(self, event_id, headers):
        return self._request("GET", f"/events/{event_id}", headers=headers)

    def list_events(self, headers, params=None):
        return self._request("GET", "/events", headers=headers, params=params)

    def publish_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/publish", {}, headers)

    def cancel_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/cancel", {}, headers)

    def complete_event(self, event_id, headers):
        return self._request("POST", f"/events/{event_id}/complete", {}, headers)

    def register_event(self, event_id, payload, headers):
        return self._request("POST", f"/events/{event_id}/register", payload, headers)

    # ---- Event Registrations ----
    def get_registration(self, registration_id, headers):
        return self._request("GET", f"/event-registrations/{registration_id}", headers=headers)

    def list_registrations(self, headers, params=None):
        return self._request("GET", "/event-registrations", headers=headers, params=params)

    def cancel_registration(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/cancel", {}, headers)

    def check_in_registration(self, registration_id, headers):
        return self._request("POST", f"/event-registrations/{registration_id}/check-in", {}, headers)

    # ---- Vendors ----
    def create_vendor(self, payload, headers):
        return self._request("POST", "/vendors", payload, headers)

    def get_vendor(self, vendor_id, headers):
        return self._request("GET", f"/vendors/{vendor_id}", headers=headers)

    def list_vendors(self, headers, params=None):
        return self._request("GET", "/vendors", headers=headers, params=params)

    def suspend_vendor(self, vendor_id, headers):
        return self._request("POST", f"/vendors/{vendor_id}/suspend", {}, headers)

    # ---- Service Requests ----
    def create_service_request(self, payload, headers):
        return self._request("POST", "/service-requests", payload, headers)

    def get_service_request(self, sr_id, headers):
        return self._request("GET", f"/service-requests/{sr_id}", headers=headers)

    def list_service_requests(self, headers, params=None):
        return self._request("GET", "/service-requests", headers=headers, params=params)

    def triage_service_request(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/triage", payload, headers)

    def assign_service_request(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/assign", payload, headers)

    def unassign_service_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/unassign", {}, headers)

    def start_service_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/start", {}, headers)

    def complete_service_request(self, sr_id, payload, headers):
        return self._request("POST", f"/service-requests/{sr_id}/complete", payload, headers)

    def approve_invoice_service_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/approve-invoice", {}, headers)

    def cancel_service_request(self, sr_id, headers):
        return self._request("POST", f"/service-requests/{sr_id}/cancel", {}, headers)

    # ---- Packages ----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    def notify_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/notify", {}, headers)

    def pickup_package(self, package_id, payload, headers):
        return self._request("POST", f"/packages/{package_id}/pickup", payload, headers)

    def return_package(self, package_id, headers):
        return self._request("POST", f"/packages/{package_id}/return", {}, headers)

    # ---- Guest Passes ----
    def create_guest_pass(self, payload, headers):
        return self._request("POST", "/guest-passes", payload, headers)

    def get_guest_pass(self, guest_pass_id, headers):
        return self._request("GET", f"/guest-passes/{guest_pass_id}", headers=headers)

    def list_guest_passes(self, headers, params=None):
        return self._request("GET", "/guest-passes", headers=headers, params=params)

    def check_in_guest_pass(self, guest_pass_id, headers):
        return self._request("POST", f"/guest-passes/{guest_pass_id}/check-in", {}, headers)

    def check_out_guest_pass(self, guest_pass_id, headers):
        return self._request("POST", f"/guest-passes/{guest_pass_id}/check-out", {}, headers)

    def cancel_guest_pass(self, guest_pass_id, headers):
        return self._request("POST", f"/guest-passes/{guest_pass_id}/cancel", {}, headers)

    # ---- Surveys ----
    def create_survey(self, payload, headers):
        return self._request("POST", "/surveys", payload, headers)

    def get_survey(self, survey_id, headers):
        return self._request("GET", f"/surveys/{survey_id}", headers=headers)

    def list_surveys(self, headers, params=None):
        return self._request("GET", "/surveys", headers=headers, params=params)

    def open_survey(self, survey_id, headers):
        return self._request("POST", f"/surveys/{survey_id}/open", {}, headers)

    def close_survey(self, survey_id, headers):
        return self._request("POST", f"/surveys/{survey_id}/close", {}, headers)

    def create_survey_response(self, survey_id, payload, headers):
        return self._request("POST", f"/surveys/{survey_id}/responses", payload, headers)

    # ---- Survey Responses ----
    def get_survey_response(self, response_id, headers):
        return self._request("GET", f"/survey-responses/{response_id}", headers=headers)

    def list_survey_responses(self, headers, params=None):
        return self._request("GET", "/survey-responses", headers=headers, params=params)

    # ---- Logical clock ----
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
