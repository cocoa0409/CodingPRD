"""API client: one method per endpoint defined in the PRD (§4).

Subclasses GenericApiClient; the base _request() is inherited. For GET endpoints
query parameters (including the gallery access_code) are passed via `params`.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ----------------------------------------------------------------- #
    # PictureDaySession
    # ----------------------------------------------------------------- #
    def create_session(self, payload, headers):
        return self._request("POST", "/api/picture-day-sessions", payload, headers)

    def list_sessions(self, headers, params=None):
        return self._request("GET", "/api/picture-day-sessions", headers=headers, params=params)

    def get_session(self, session_id, headers):
        return self._request("GET", f"/api/picture-day-sessions/{session_id}", headers=headers)

    def lock_roster(self, session_id, headers):
        return self._request("POST", f"/api/picture-day-sessions/{session_id}/lock-roster", {}, headers)

    def open_capture(self, session_id, headers):
        return self._request("POST", f"/api/picture-day-sessions/{session_id}/open-capture", {}, headers)

    def open_gallery(self, session_id, headers):
        return self._request("POST", f"/api/picture-day-sessions/{session_id}/open-gallery", {}, headers)

    def close_ordering(self, session_id, headers):
        return self._request("POST", f"/api/picture-day-sessions/{session_id}/close-ordering", {}, headers)

    def settle_session(self, session_id, payload, headers):
        return self._request("POST", f"/api/picture-day-sessions/{session_id}/settle", payload, headers)

    def cancel_session(self, session_id, headers):
        return self._request("POST", f"/api/picture-day-sessions/{session_id}/cancel", {}, headers)

    def get_gallery(self, session_id, headers, params=None):
        return self._request("GET", f"/api/picture-day-sessions/{session_id}/gallery", headers=headers, params=params)

    def yearbook_export(self, session_id, headers, params=None):
        return self._request("GET", f"/api/picture-day-sessions/{session_id}/yearbook-export", headers=headers, params=params)

    # ----------------------------------------------------------------- #
    # Student / roster
    # ----------------------------------------------------------------- #
    def create_student(self, payload, headers):
        return self._request("POST", "/api/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/api/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/api/students/{student_id}", headers=headers)

    def mark_absent(self, student_id, headers):
        return self._request("POST", f"/api/students/{student_id}/mark-absent", {}, headers)

    # ----------------------------------------------------------------- #
    # PackageItem / catalog
    # ----------------------------------------------------------------- #
    def create_package(self, payload, headers):
        return self._request("POST", "/api/packages", payload, headers)

    def list_packages(self, headers, params=None):
        return self._request("GET", "/api/packages", headers=headers, params=params)

    def get_package(self, package_id, headers):
        return self._request("GET", f"/api/packages/{package_id}", headers=headers)

    # ----------------------------------------------------------------- #
    # Backdrop / Photographer / CaptureSlot
    # ----------------------------------------------------------------- #
    def create_backdrop(self, payload, headers):
        return self._request("POST", "/api/backdrops", payload, headers)

    def list_backdrops(self, headers, params=None):
        return self._request("GET", "/api/backdrops", headers=headers, params=params)

    def get_backdrop(self, backdrop_id, headers):
        return self._request("GET", f"/api/backdrops/{backdrop_id}", headers=headers)

    def create_photographer(self, payload, headers):
        return self._request("POST", "/api/photographers", payload, headers)

    def list_photographers(self, headers, params=None):
        return self._request("GET", "/api/photographers", headers=headers, params=params)

    def get_photographer(self, photographer_id, headers):
        return self._request("GET", f"/api/photographers/{photographer_id}", headers=headers)

    def create_capture_slot(self, payload, headers):
        return self._request("POST", "/api/capture-slots", payload, headers)

    def list_capture_slots(self, headers, params=None):
        return self._request("GET", "/api/capture-slots", headers=headers, params=params)

    def get_capture_slot(self, slot_id, headers):
        return self._request("GET", f"/api/capture-slots/{slot_id}", headers=headers)

    def complete_capture_slot(self, slot_id, headers):
        return self._request("POST", f"/api/capture-slots/{slot_id}/complete", {}, headers)

    def cancel_capture_slot(self, slot_id, headers):
        return self._request("POST", f"/api/capture-slots/{slot_id}/cancel", {}, headers)

    # ----------------------------------------------------------------- #
    # Photo / capture & match
    # ----------------------------------------------------------------- #
    def create_photo(self, payload, headers):
        return self._request("POST", "/api/photos", payload, headers)

    def list_photos(self, headers, params=None):
        return self._request("GET", "/api/photos", headers=headers, params=params)

    def get_photo(self, photo_id, headers):
        return self._request("GET", f"/api/photos/{photo_id}", headers=headers)

    def match_photo(self, photo_id, headers):
        return self._request("POST", f"/api/photos/{photo_id}/match", {}, headers)

    def approve_photo(self, photo_id, headers):
        return self._request("POST", f"/api/photos/{photo_id}/approve", {}, headers)

    # ----------------------------------------------------------------- #
    # PhotoOrder / ordering
    # ----------------------------------------------------------------- #
    def create_order(self, payload, headers):
        return self._request("POST", "/api/photo-orders", payload, headers)

    def list_orders(self, headers, params=None):
        return self._request("GET", "/api/photo-orders", headers=headers, params=params)

    def get_order(self, order_id, headers):
        return self._request("GET", f"/api/photo-orders/{order_id}", headers=headers)

    def create_order_line(self, payload, headers):
        return self._request("POST", "/api/order-lines", payload, headers)

    def list_order_lines(self, headers, params=None):
        return self._request("GET", "/api/order-lines", headers=headers, params=params)

    def get_order_line(self, line_id, headers):
        return self._request("GET", f"/api/order-lines/{line_id}", headers=headers)

    def submit_order(self, order_id, headers):
        return self._request("POST", f"/api/photo-orders/{order_id}/submit", {}, headers)

    def pay_order(self, order_id, headers):
        return self._request("POST", f"/api/photo-orders/{order_id}/pay", {}, headers)

    def reject_order(self, order_id, headers):
        return self._request("POST", f"/api/photo-orders/{order_id}/reject", {}, headers)

    def cancel_order(self, order_id, headers):
        return self._request("POST", f"/api/photo-orders/{order_id}/cancel", {}, headers)

    # ----------------------------------------------------------------- #
    # RetouchOrder / retouch & retake
    # ----------------------------------------------------------------- #
    def create_retouch_order(self, payload, headers):
        return self._request("POST", "/api/retouch-orders", payload, headers)

    def list_retouch_orders(self, headers, params=None):
        return self._request("GET", "/api/retouch-orders", headers=headers, params=params)

    def get_retouch_order(self, retouch_id, headers):
        return self._request("GET", f"/api/retouch-orders/{retouch_id}", headers=headers)

    def approve_retouch_order(self, retouch_id, headers):
        return self._request("POST", f"/api/retouch-orders/{retouch_id}/approve", {}, headers)

    def complete_retouch_order(self, retouch_id, headers):
        return self._request("POST", f"/api/retouch-orders/{retouch_id}/complete", {}, headers)

    def reject_retouch_order(self, retouch_id, headers):
        return self._request("POST", f"/api/retouch-orders/{retouch_id}/reject", {}, headers)

    def cancel_retouch_order(self, retouch_id, headers):
        return self._request("POST", f"/api/retouch-orders/{retouch_id}/cancel", {}, headers)

    # ----------------------------------------------------------------- #
    # Shipment / distribution
    # ----------------------------------------------------------------- #
    def create_shipment(self, payload, headers):
        return self._request("POST", "/api/shipments", payload, headers)

    def list_shipments(self, headers, params=None):
        return self._request("GET", "/api/shipments", headers=headers, params=params)

    def get_shipment(self, shipment_id, headers):
        return self._request("GET", f"/api/shipments/{shipment_id}", headers=headers)

    def update_shipment(self, shipment_id, payload, headers):
        return self._request("PUT", f"/api/shipments/{shipment_id}", payload, headers)

    def dispatch_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/dispatch", {}, headers)

    def deliver_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/deliver", {}, headers)

    def void_shipment(self, shipment_id, headers):
        return self._request("POST", f"/api/shipments/{shipment_id}/void", {}, headers)

    # ----------------------------------------------------------------- #
    # Logical clock (test-driving)
    # ----------------------------------------------------------------- #
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/api/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
