"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Actor registration ───────────────────────────
    def create_requester(self, payload, headers):
        return self._request("POST", "/requesters", payload, headers)

    def get_requester(self, requester_id, headers):
        return self._request("GET", f"/requesters/{requester_id}", headers=headers)

    def create_officer(self, payload, headers):
        return self._request("POST", "/officers", payload, headers)

    def create_appeal_authority(self, payload, headers):
        return self._request("POST", "/appeal-authorities", payload, headers)

    def create_submitter(self, payload, headers):
        return self._request("POST", "/submitters", payload, headers)

    # ─── Request intake & lifecycle ────────────────────
    def create_request(self, payload, headers):
        return self._request("POST", "/requests", payload, headers)

    def get_request(self, request_id, headers):
        return self._request("GET", f"/requests/{request_id}", headers=headers)

    def list_requests(self, headers, params=None):
        return self._request("GET", "/requests", headers=headers, params=params)

    def perfect_request(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/perfect", payload, headers)

    def assign_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/requests/{request_id}/assign", payload or {}, headers)

    def extend_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/requests/{request_id}/extend", payload or {}, headers)

    def withdraw_request(self, request_id, headers, payload=None):
        return self._request("POST", f"/requests/{request_id}/withdraw", payload or {}, headers)

    # ─── Records & exemptions ──────────────────────────
    def create_record(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/records", payload, headers)

    def list_request_records(self, request_id, headers, params=None):
        return self._request("GET", f"/requests/{request_id}/records", headers=headers, params=params)

    def get_record(self, record_id, headers):
        return self._request("GET", f"/records/{record_id}", headers=headers)

    def list_records(self, headers, params=None):
        return self._request("GET", "/records", headers=headers, params=params)

    def review_record(self, record_id, payload, headers):
        return self._request("POST", f"/records/{record_id}/review", payload, headers)

    def create_exemption(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/exemptions", payload, headers)

    def list_request_exemptions(self, request_id, headers, params=None):
        return self._request("GET", f"/requests/{request_id}/exemptions", headers=headers, params=params)

    def get_exemption(self, exemption_id, headers):
        return self._request("GET", f"/exemptions/{exemption_id}", headers=headers)

    def list_exemptions(self, headers, params=None):
        return self._request("GET", "/exemptions", headers=headers, params=params)

    # ─── Fees ──────────────────────────────────────────
    def create_fee_estimate(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/fee-estimate", payload, headers)

    def get_fee_estimate(self, request_id, headers):
        return self._request("GET", f"/requests/{request_id}/fee-estimate", headers=headers)

    def adjudicate_fee_waiver(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/fee-waiver", payload, headers)

    def pay_request(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/payment", payload, headers)

    def get_deadline(self, request_id, headers):
        return self._request("GET", f"/requests/{request_id}/deadline", headers=headers)

    # ─── Determination & Glomar ────────────────────────
    def issue_determination(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/determination", payload, headers)

    def invoke_glomar(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/glomar", payload, headers)

    # ─── Appeals ───────────────────────────────────────
    def file_appeal(self, request_id, payload, headers):
        return self._request("POST", f"/requests/{request_id}/appeals", payload, headers)

    def get_appeal(self, appeal_id, headers):
        return self._request("GET", f"/appeals/{appeal_id}", headers=headers)

    def list_request_appeals(self, request_id, headers, params=None):
        return self._request("GET", f"/requests/{request_id}/appeals", headers=headers, params=params)

    def list_appeals(self, headers, params=None):
        return self._request("GET", "/appeals", headers=headers, params=params)

    def assign_appeal(self, appeal_id, headers, payload=None):
        return self._request("POST", f"/appeals/{appeal_id}/assign", payload or {}, headers)

    def decide_appeal(self, appeal_id, payload, headers):
        return self._request("POST", f"/appeals/{appeal_id}/decide", payload, headers)

    # ─── Reverse FOIA ──────────────────────────────────
    def create_objection(self, record_id, payload, headers):
        return self._request("POST", f"/records/{record_id}/objection", payload, headers)

    def get_objection(self, objection_id, headers):
        return self._request("GET", f"/objections/{objection_id}", headers=headers)

    def list_objections(self, headers, params=None):
        return self._request("GET", "/objections", headers=headers, params=params)

    def object_to_disclosure(self, objection_id, headers, payload=None):
        return self._request("POST", f"/objections/{objection_id}/object", payload or {}, headers)

    def resolve_objection(self, objection_id, payload, headers):
        return self._request("POST", f"/objections/{objection_id}/resolve", payload, headers)

    def lapse_objection(self, objection_id, headers, payload=None):
        return self._request("POST", f"/objections/{objection_id}/lapse", payload or {}, headers)

    # ─── Inspection facilities & bookings ──────────────
    def create_reading_room(self, payload, headers):
        return self._request("POST", "/reading-rooms", payload, headers)

    def get_reading_room(self, room_id, headers):
        return self._request("GET", f"/reading-rooms/{room_id}", headers=headers)

    def create_review_station(self, payload, headers):
        return self._request("POST", "/review-stations", payload, headers)

    def get_review_station(self, station_id, headers):
        return self._request("GET", f"/review-stations/{station_id}", headers=headers)

    def create_reading_room_booking(self, room_id, payload, headers):
        return self._request("POST", f"/reading-rooms/{room_id}/bookings", payload, headers)

    def list_reading_room_bookings(self, room_id, headers, params=None):
        return self._request("GET", f"/reading-rooms/{room_id}/bookings", headers=headers, params=params)

    def get_reading_room_booking(self, booking_id, headers):
        return self._request("GET", f"/reading-room-bookings/{booking_id}", headers=headers)

    def list_all_reading_room_bookings(self, headers, params=None):
        return self._request("GET", "/reading-room-bookings", headers=headers, params=params)

    def create_review_station_booking(self, station_id, payload, headers):
        return self._request("POST", f"/review-stations/{station_id}/bookings", payload, headers)

    def list_review_station_bookings(self, station_id, headers, params=None):
        return self._request("GET", f"/review-stations/{station_id}/bookings", headers=headers, params=params)

    def get_review_station_booking(self, booking_id, headers):
        return self._request("GET", f"/review-station-bookings/{booking_id}", headers=headers)

    def list_all_review_station_bookings(self, headers, params=None):
        return self._request("GET", "/review-station-bookings", headers=headers, params=params)

    # ─── Audit log ─────────────────────────────────────
    def list_audit_events(self, request_id, headers, params=None):
        return self._request("GET", f"/requests/{request_id}/audit-events", headers=headers, params=params)

    # ─── Test-driving clock ────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
