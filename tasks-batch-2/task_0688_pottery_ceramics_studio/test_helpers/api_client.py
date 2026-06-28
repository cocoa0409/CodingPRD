"""API client: one method per endpoint defined in the Pottery Ceramics Studio PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):

    # ─── LoyaltyMember ─────────────────────────────────────────────────────
    def create_member(self, payload, headers):
        return self._request("POST", "/loyalty-members", payload, headers)

    def get_member(self, member_id, headers):
        return self._request("GET", f"/loyalty-members/{member_id}", headers=headers)

    def list_members(self, headers, params=None):
        return self._request("GET", "/loyalty-members", headers=headers, params=params)

    def suspend_member(self, member_id, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/suspend", headers=headers)

    def reactivate_member(self, member_id, headers):
        return self._request("POST", f"/loyalty-members/{member_id}/reactivate", headers=headers)

    def get_member_ledger(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/ledger", headers=headers, params=params)

    def get_member_visits(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/visits", headers=headers, params=params)

    def get_member_enrollments(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/enrollments", headers=headers, params=params)

    def get_member_party_bookings(self, member_id, headers, params=None):
        return self._request("GET", f"/loyalty-members/{member_id}/party-bookings", headers=headers, params=params)

    # ─── PaintBarItem ──────────────────────────────────────────────────────
    def create_paint_bar_item(self, payload, headers):
        return self._request("POST", "/paint-bar-items", payload, headers)

    def get_paint_bar_item(self, item_id, headers):
        return self._request("GET", f"/paint-bar-items/{item_id}", headers=headers)

    def list_paint_bar_items(self, headers, params=None):
        return self._request("GET", "/paint-bar-items", headers=headers, params=params)

    def restock_paint_bar_item(self, item_id, payload, headers):
        return self._request("POST", f"/paint-bar-items/{item_id}/restock", payload, headers)

    def discontinue_paint_bar_item(self, item_id, headers):
        return self._request("POST", f"/paint-bar-items/{item_id}/discontinue", headers=headers)

    # ─── StudioVisit ───────────────────────────────────────────────────────
    def create_visit(self, payload, headers):
        return self._request("POST", "/studio-visits", payload, headers)

    def get_visit(self, visit_id, headers):
        return self._request("GET", f"/studio-visits/{visit_id}", headers=headers)

    def list_visits(self, headers, params=None):
        return self._request("GET", "/studio-visits", headers=headers, params=params)

    def get_visit_points_preview(self, visit_id, headers):
        return self._request("GET", f"/studio-visits/{visit_id}/points-preview", headers=headers)

    def add_piece(self, visit_id, payload, headers):
        return self._request("POST", f"/studio-visits/{visit_id}/pieces", payload, headers)

    def consume_supply(self, visit_id, payload, headers):
        return self._request("POST", f"/studio-visits/{visit_id}/consume", payload, headers)

    def checkout_visit(self, visit_id, payload, headers):
        return self._request("POST", f"/studio-visits/{visit_id}/checkout", payload, headers)

    def void_visit(self, visit_id, headers):
        return self._request("POST", f"/studio-visits/{visit_id}/void", headers=headers)

    # ─── BisquePiece ───────────────────────────────────────────────────────
    def get_piece(self, piece_id, headers):
        return self._request("GET", f"/bisque-pieces/{piece_id}", headers=headers)

    def list_pieces(self, headers, params=None):
        return self._request("GET", "/bisque-pieces", headers=headers, params=params)

    def unload_piece(self, piece_id, headers):
        return self._request("POST", f"/bisque-pieces/{piece_id}/unload", headers=headers)

    def pickup_piece(self, piece_id, headers):
        return self._request("POST", f"/bisque-pieces/{piece_id}/pickup", headers=headers)

    def get_piece_notification(self, piece_id, headers):
        return self._request("GET", f"/bisque-pieces/{piece_id}/notification", headers=headers)

    # ─── KilnBatch ─────────────────────────────────────────────────────────
    def create_batch(self, payload, headers):
        return self._request("POST", "/kiln-batches", payload, headers)

    def get_batch(self, batch_id, headers):
        return self._request("GET", f"/kiln-batches/{batch_id}", headers=headers)

    def list_batches(self, headers, params=None):
        return self._request("GET", "/kiln-batches", headers=headers, params=params)

    def get_batch_pieces(self, batch_id, headers, params=None):
        return self._request("GET", f"/kiln-batches/{batch_id}/pieces", headers=headers, params=params)

    def load_piece(self, batch_id, payload, headers):
        return self._request("POST", f"/kiln-batches/{batch_id}/load", payload, headers)

    def start_firing(self, batch_id, headers):
        return self._request("POST", f"/kiln-batches/{batch_id}/start-firing", headers=headers)

    def complete_firing(self, batch_id, headers):
        return self._request("POST", f"/kiln-batches/{batch_id}/complete-firing", headers=headers)

    def cancel_batch(self, batch_id, headers):
        return self._request("POST", f"/kiln-batches/{batch_id}/cancel", headers=headers)

    # ─── PartyBooking ──────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/party-bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/party-bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/party-bookings", headers=headers, params=params)

    def pay_deposit(self, booking_id, payload, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/pay-deposit", payload, headers)

    def expire_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/expire", headers=headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/party-bookings/{booking_id}/cancel", headers=headers)

    # ─── ClassSeries / Enrollment ──────────────────────────────────────────
    def create_series(self, payload, headers):
        return self._request("POST", "/class-series", payload, headers)

    def get_series(self, series_id, headers):
        return self._request("GET", f"/class-series/{series_id}", headers=headers)

    def list_series(self, headers, params=None):
        return self._request("GET", "/class-series", headers=headers, params=params)

    def enroll(self, series_id, payload, headers):
        return self._request("POST", f"/class-series/{series_id}/enroll", payload, headers)

    def start_series(self, series_id, headers):
        return self._request("POST", f"/class-series/{series_id}/start", headers=headers)

    def cancel_series(self, series_id, headers):
        return self._request("POST", f"/class-series/{series_id}/cancel", headers=headers)

    def get_series_enrollments(self, series_id, headers, params=None):
        return self._request("GET", f"/class-series/{series_id}/enrollments", headers=headers, params=params)

    def get_enrollment(self, enrollment_id, headers):
        return self._request("GET", f"/enrollments/{enrollment_id}", headers=headers)

    def mark_attended(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/mark-attended", headers=headers)

    def withdraw_enrollment(self, enrollment_id, headers):
        return self._request("POST", f"/enrollments/{enrollment_id}/withdraw", headers=headers)

    # ─── Logical clock ─────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
