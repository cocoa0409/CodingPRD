"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Booth models ----
    def create_booth_model(self, payload, headers):
        return self._request("POST", "/booth-models", payload, headers)

    def get_booth_model(self, model_id, headers):
        return self._request("GET", f"/booth-models/{model_id}", headers=headers)

    # ---- Packages ----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/packages/{package_id}", headers=headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/packages", headers=headers, params=params)

    # ---- Booths ----
    def create_booth(self, payload, headers):
        return self._request("POST", "/booths", payload, headers)

    def get_booth(self, booth_id, headers):
        return self._request("GET", f"/booths/{booth_id}", headers=headers)

    def list_booths(self, headers, params=None):
        return self._request("GET", "/booths", headers=headers, params=params)

    def update_booth(self, booth_id, payload, headers):
        return self._request("PATCH", f"/booths/{booth_id}", payload, headers)

    # ---- Attendants ----
    def create_attendant(self, payload, headers):
        return self._request("POST", "/attendants", payload, headers)

    def get_attendant(self, attendant_id, headers):
        return self._request("GET", f"/attendants/{attendant_id}", headers=headers)

    # ---- Add-ons (catalog) ----
    def create_add_on(self, payload, headers):
        return self._request("POST", "/add-ons", payload, headers)

    def get_add_on(self, add_on_id, headers):
        return self._request("GET", f"/add-ons/{add_on_id}", headers=headers)

    # ---- Customers ----
    def create_customer(self, payload, headers):
        return self._request("POST", "/customers", payload, headers)

    def get_customer(self, customer_id, headers):
        return self._request("GET", f"/customers/{customer_id}", headers=headers)

    # ---- Bookings (hub) ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def add_booking_add_on(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/add-ons", payload, headers)

    def list_booking_add_ons(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/add-ons", headers=headers, params=params)

    def get_add_on_line(self, line_id, headers):
        return self._request("GET", f"/add-on-lines/{line_id}", headers=headers)

    def list_add_on_lines(self, headers, params=None):
        return self._request("GET", "/add-on-lines", headers=headers, params=params)

    def create_payment(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/payments", payload, headers)

    def list_booking_payments(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/payments", headers=headers, params=params)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", payload, headers)

    def start_service(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/start-service", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def forfeit_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/forfeit", {}, headers)

    def list_booking_attendant_assignments(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/attendant-assignments", headers=headers, params=params)

    def get_attendant_assignment(self, assignment_id, headers):
        return self._request("GET", f"/attendant-assignments/{assignment_id}", headers=headers)

    def list_attendant_assignments(self, headers, params=None):
        return self._request("GET", "/attendant-assignments", headers=headers, params=params)

    # ---- Event logs ----
    def get_event_log(self, log_id, headers):
        return self._request("GET", f"/event-logs/{log_id}", headers=headers)

    def list_booking_event_logs(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/event-logs", headers=headers, params=params)

    def update_event_log(self, log_id, payload, headers):
        return self._request("PATCH", f"/event-logs/{log_id}", payload, headers)

    def finalize_event_log(self, log_id, payload, headers):
        return self._request("POST", f"/event-logs/{log_id}/finalize", payload, headers)

    # ---- Galleries ----
    def get_gallery(self, gallery_id, headers):
        return self._request("GET", f"/galleries/{gallery_id}", headers=headers)

    def list_booking_galleries(self, booking_id, headers, params=None):
        return self._request("GET", f"/bookings/{booking_id}/galleries", headers=headers, params=params)

    def upload_gallery_photos(self, gallery_id, payload, headers):
        return self._request("POST", f"/galleries/{gallery_id}/photos", payload, headers)

    def publish_gallery(self, gallery_id, headers):
        return self._request("POST", f"/galleries/{gallery_id}/publish", {}, headers)

    def unpublish_gallery(self, gallery_id, headers):
        return self._request("POST", f"/galleries/{gallery_id}/unpublish", {}, headers)

    # ---- Test clock ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def get_clock(self, headers=None):
        return self._request("GET", "/_clock", headers=headers)


api_client = ApiClient()
