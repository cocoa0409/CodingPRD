"""API client: one method per endpoint defined in the PRD."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Courses ---
    def create_course(self, payload, headers):
        return self._request("POST", "/golf/courses", payload, headers)

    def get_course(self, course_id, headers):
        return self._request("GET", f"/golf/courses/{course_id}", headers=headers)

    def list_courses(self, headers, params=None):
        return self._request("GET", "/golf/courses", headers=headers, params=params)

    # --- Golfers ---
    def create_golfer(self, payload, headers):
        return self._request("POST", "/golf/golfers", payload, headers)

    def get_golfer(self, golfer_id, headers):
        return self._request("GET", f"/golf/golfers/{golfer_id}", headers=headers)

    def list_golfers(self, headers, params=None):
        return self._request("GET", "/golf/golfers", headers=headers, params=params)

    # --- Scores ---
    def create_score(self, payload, headers):
        return self._request("POST", "/golf/scores", payload, headers)

    def get_score(self, score_id, headers):
        return self._request("GET", f"/golf/scores/{score_id}", headers=headers)

    def list_scores(self, headers, params=None):
        return self._request("GET", "/golf/scores", headers=headers, params=params)

    def void_score(self, score_id, headers):
        return self._request("POST", f"/golf/scores/{score_id}/void", {}, headers)

    # --- Tee Times ---
    def create_tee_time(self, payload, headers):
        return self._request("POST", "/golf/tee-times", payload, headers)

    def get_tee_time(self, tee_time_id, headers):
        return self._request("GET", f"/golf/tee-times/{tee_time_id}", headers=headers)

    def list_tee_times(self, headers, params=None):
        return self._request("GET", "/golf/tee-times", headers=headers, params=params)

    def close_tee_time(self, tee_time_id, headers):
        return self._request("POST", f"/golf/tee-times/{tee_time_id}/close", {}, headers)

    # --- Bookings ---
    def create_booking(self, tee_time_id, payload, headers):
        return self._request("POST", f"/golf/tee-times/{tee_time_id}/bookings", payload, headers)

    def list_slot_bookings(self, tee_time_id, headers, params=None):
        return self._request("GET", f"/golf/tee-times/{tee_time_id}/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/golf/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/golf/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/golf/bookings/{booking_id}/cancel", {}, headers)

    # --- Handicap Revisions ---
    def create_handicap_revision(self, payload, headers):
        return self._request("POST", "/golf/handicap-revisions", payload, headers)

    def list_handicap_revisions(self, headers, params=None):
        return self._request("GET", "/golf/handicap-revisions", headers=headers, params=params)

    # --- Test-driving clock ---
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers)


api_client = ApiClient()
