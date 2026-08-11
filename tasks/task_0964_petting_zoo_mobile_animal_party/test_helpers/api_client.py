"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Logical clock (PRD §2.8) ----
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/petting-zoo/_clock/set_current_utc",
            {"to_iso8601": to_iso8601}, headers,
        )

    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/petting-zoo/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/petting-zoo/customers/{customer_id}", headers=headers)

    def list_customer_venues(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/customers/{customer_id}/venues",
            headers=headers, params=params,
        )

    # ---- Insurance certificates ----
    def create_insurance_certificate(self, customer_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/customers/{customer_id}/insurance-certificates",
            payload, headers,
        )

    def list_insurance_certificates(self, customer_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/customers/{customer_id}/insurance-certificates",
            headers=headers, params=params,
        )

    def verify_insurance_certificate(self, certificate_id, decision, headers):
        return self._request(
            "POST", f"/petting-zoo/insurance-certificates/{certificate_id}/verify",
            {"decision": decision}, headers,
        )

    # ---- Venues ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/petting-zoo/venues", payload, headers)

    def get_venue(self, venue_id, headers):
        return self._request("GET", f"/petting-zoo/venues/{venue_id}", headers=headers)

    # ---- Animals ----
    def create_animal(self, payload, headers):
        return self._request("POST", "/petting-zoo/animals", payload, headers)

    def list_animals(self, headers, params=None):
        return self._request("GET", "/petting-zoo/animals", headers=headers, params=params)

    def get_animal(self, animal_id, headers):
        return self._request("GET", f"/petting-zoo/animals/{animal_id}", headers=headers)

    def retire_animal(self, animal_id, headers):
        return self._request("POST", f"/petting-zoo/animals/{animal_id}/retire", {}, headers)

    def create_health_record(self, animal_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/animals/{animal_id}/health-records", payload, headers,
        )

    def list_health_records(self, animal_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/animals/{animal_id}/health-records",
            headers=headers, params=params,
        )

    def list_animal_booking_animals(self, animal_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/animals/{animal_id}/booking-animals",
            headers=headers, params=params,
        )

    # ---- Handlers ----
    def create_handler(self, payload, headers):
        return self._request("POST", "/petting-zoo/handlers", payload, headers)

    def list_handlers(self, headers, params=None):
        return self._request("GET", "/petting-zoo/handlers", headers=headers, params=params)

    def get_handler(self, handler_id, headers):
        return self._request("GET", f"/petting-zoo/handlers/{handler_id}", headers=headers)

    def list_handler_assignments(self, handler_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/handlers/{handler_id}/staff-assignments",
            headers=headers, params=params,
        )

    # ---- Bookings ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/petting-zoo/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/petting-zoo/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/petting-zoo/bookings/{booking_id}", headers=headers)

    def quote_booking(self, booking_id, headers):
        return self._request("POST", f"/petting-zoo/bookings/{booking_id}/quote", {}, headers)

    def create_payment(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/payments", payload, headers,
        )

    def confirm_booking(self, booking_id, headers):
        return self._request("POST", f"/petting-zoo/bookings/{booking_id}/confirm", {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/reschedule", payload, headers,
        )

    def cancel_booking(self, booking_id, reason, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/cancel", {"reason": reason}, headers,
        )

    def weather_hold(self, booking_id, weather_assessment_id, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/weather-hold",
            {"weather_assessment_id": weather_assessment_id}, headers,
        )

    def release_weather_hold(self, booking_id, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/release-weather-hold", {}, headers,
        )

    def dispatch_booking(self, booking_id, headers):
        return self._request("POST", f"/petting-zoo/bookings/{booking_id}/dispatch", {}, headers)

    def arrive_booking(self, booking_id, headers):
        return self._request("POST", f"/petting-zoo/bookings/{booking_id}/arrive", {}, headers)

    def start_event(self, booking_id, actual_handwash_stations, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/start-event",
            {"actual_handwash_stations": actual_handwash_stations}, headers,
        )

    def complete_booking(self, booking_id, actual_attendance_count, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/complete",
            {"actual_attendance_count": actual_attendance_count}, headers,
        )

    def finalize_invoice(self, booking_id, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/finalize-invoice", {}, headers,
        )

    # ---- Booking roster animals ----
    def attach_booking_animal(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/animals", payload, headers,
        )

    def confirm_booking_animal(self, booking_id, booking_animal_id, headers):
        return self._request(
            "POST",
            f"/petting-zoo/bookings/{booking_id}/animals/{booking_animal_id}/confirm",
            {}, headers,
        )

    def remove_booking_animal(self, booking_id, booking_animal_id, headers):
        return self._request(
            "DELETE",
            f"/petting-zoo/bookings/{booking_id}/animals/{booking_animal_id}",
            headers=headers,
        )

    def list_booking_animals(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/bookings/{booking_id}/animals",
            headers=headers, params=params,
        )

    # ---- Staff assignments ----
    def create_staff_assignment(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/staff-assignments",
            payload, headers,
        )

    def release_staff_assignment(self, booking_id, staff_assignment_id, headers):
        return self._request(
            "DELETE",
            f"/petting-zoo/bookings/{booking_id}/staff-assignments/{staff_assignment_id}",
            headers=headers,
        )

    def list_staff_assignments(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/bookings/{booking_id}/staff-assignments",
            headers=headers, params=params,
        )

    # ---- Add-on requests ----
    def create_addon(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/add-ons", payload, headers,
        )

    def decide_addon(self, booking_id, addon_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/add-ons/{addon_id}/decide",
            payload, headers,
        )

    def list_addons(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/bookings/{booking_id}/add-ons",
            headers=headers, params=params,
        )

    # ---- Permits ----
    def create_permit(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/permits", payload, headers,
        )

    def submit_permit(self, permit_id, headers):
        return self._request("POST", f"/petting-zoo/permits/{permit_id}/submit", {}, headers)

    def decide_permit(self, permit_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/permits/{permit_id}/decide", payload, headers,
        )

    def list_permits(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/bookings/{booking_id}/permits",
            headers=headers, params=params,
        )

    # ---- Waivers ----
    def sign_waiver(self, booking_id, count, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/waiver-signatures",
            {"count": count}, headers,
        )

    def list_waivers(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/bookings/{booking_id}/waivers",
            headers=headers, params=params,
        )

    # ---- Weather assessments ----
    def create_weather_assessment(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/petting-zoo/bookings/{booking_id}/weather-assessments",
            payload, headers,
        )

    def list_weather_assessments(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/bookings/{booking_id}/weather-assessments",
            headers=headers, params=params,
        )

    # ---- Ledger ----
    def list_ledger_entries(self, booking_id, headers, params=None):
        return self._request(
            "GET", f"/petting-zoo/bookings/{booking_id}/ledger-entries",
            headers=headers, params=params,
        )


api_client = ApiClient()
