"""API client: one method per endpoint defined in the PRD (Section 4).

Subclasses the framework GenericApiClient; the base _request() handles the HTTP
call, envelope, and base URL. Signature:
    _request(method, path, payload=None, headers=None, params=None) -> Response
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- Officiant ----
    def create_officiant(self, payload, headers):
        return self._request("POST", "/officiants", payload, headers)

    def get_officiant(self, officiant_id, headers):
        return self._request("GET", f"/officiants/{officiant_id}", headers=headers)

    def list_officiants(self, headers, params=None):
        return self._request("GET", "/officiants", headers=headers, params=params)

    def transition_officiant(self, officiant_id, payload, headers):
        return self._request("POST", f"/officiants/{officiant_id}/transition", payload, headers)

    # ---- Couple ----
    def create_couple(self, payload, headers):
        return self._request("POST", "/couples", payload, headers)

    def get_couple(self, couple_id, headers):
        return self._request("GET", f"/couples/{couple_id}", headers=headers)

    # ---- Package ----
    def create_package(self, payload, headers):
        return self._request("POST", "/packages", payload, headers)

    # ---- Venue ----
    def create_venue(self, payload, headers):
        return self._request("POST", "/venues", payload, headers)

    # ---- Booking ----
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/confirm", payload, headers)

    def cancel_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", payload, headers)

    def assign_backup(self, booking_id, headers, payload=None):
        return self._request("POST", f"/bookings/{booking_id}/assign-backup", payload or {}, headers)

    def complete_booking(self, booking_id, headers, payload=None):
        return self._request("POST", f"/bookings/{booking_id}/complete", payload or {}, headers)

    # ---- DateHold ----
    def create_date_hold(self, payload, headers):
        return self._request("POST", "/date-holds", payload, headers)

    def get_date_hold(self, hold_id, headers):
        return self._request("GET", f"/date-holds/{hold_id}", headers=headers)

    def list_date_holds(self, headers, params=None):
        return self._request("GET", "/date-holds", headers=headers, params=params)

    # ---- CeremonyScript ----
    def create_ceremony_script(self, payload, headers):
        return self._request("POST", "/ceremony-scripts", payload, headers)

    def get_ceremony_script(self, script_id, headers):
        return self._request("GET", f"/ceremony-scripts/{script_id}", headers=headers)

    def list_ceremony_scripts(self, headers, params=None):
        return self._request("GET", "/ceremony-scripts", headers=headers, params=params)

    def patch_ceremony_script(self, script_id, payload, headers):
        return self._request("PATCH", f"/ceremony-scripts/{script_id}", payload, headers)

    def submit_ceremony_script(self, script_id, headers, payload=None):
        return self._request("POST", f"/ceremony-scripts/{script_id}/submit", payload or {}, headers)

    def decide_ceremony_script(self, script_id, payload, headers):
        return self._request("POST", f"/ceremony-scripts/{script_id}/decision", payload, headers)

    # ---- Rehearsal ----
    def create_rehearsal(self, payload, headers):
        return self._request("POST", "/rehearsals", payload, headers)

    def get_rehearsal(self, rehearsal_id, headers):
        return self._request("GET", f"/rehearsals/{rehearsal_id}", headers=headers)

    def list_rehearsals(self, headers, params=None):
        return self._request("GET", "/rehearsals", headers=headers, params=params)

    def transition_rehearsal(self, rehearsal_id, payload, headers):
        return self._request("POST", f"/rehearsals/{rehearsal_id}/transition", payload, headers)

    # ---- MarriageLicense ----
    def create_marriage_license(self, payload, headers):
        return self._request("POST", "/marriage-licenses", payload, headers)

    def get_marriage_license(self, license_id, headers):
        return self._request("GET", f"/marriage-licenses/{license_id}", headers=headers)

    def list_marriage_licenses(self, headers, params=None):
        return self._request("GET", "/marriage-licenses", headers=headers, params=params)

    def transition_marriage_license(self, license_id, payload, headers):
        return self._request("POST", f"/marriage-licenses/{license_id}/transition", payload, headers)

    # ---- Review ----
    def create_review(self, payload, headers):
        return self._request("POST", "/reviews", payload, headers)

    def get_review(self, review_id, headers):
        return self._request("GET", f"/reviews/{review_id}", headers=headers)

    def list_reviews(self, headers, params=None):
        return self._request("GET", "/reviews", headers=headers, params=params)

    def moderate_review(self, review_id, payload, headers):
        return self._request("POST", f"/reviews/{review_id}/moderate", payload, headers)

    # ---- System / test-driving ----
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    def run_expiry(self, headers, payload=None):
        return self._request("POST", "/_expiry/run", payload or {}, headers)


api_client = ApiClient()
