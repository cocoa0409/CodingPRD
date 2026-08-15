"""API client: one method per endpoint defined in the PRD endpoint catalogue."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ---- ContestEvent ----
    def create_contest_event(self, payload, headers):
        return self._request("POST", "/contest-events", payload, headers)

    def get_contest_event(self, contest_id, headers):
        return self._request("GET", f"/contest-events/{contest_id}", headers=headers)

    def transition_contest_event(self, contest_id, payload, headers):
        return self._request("POST", f"/contest-events/{contest_id}/transition", payload, headers)

    def get_tax_summary(self, contest_id, headers):
        return self._request("GET", f"/contest-events/{contest_id}/tax-summary", headers=headers)

    def list_contest_categories(self, contest_id, headers):
        return self._request("GET", f"/contest-events/{contest_id}/categories", headers=headers)

    def list_contest_judges(self, contest_id, headers):
        return self._request("GET", f"/contest-events/{contest_id}/judges", headers=headers)

    # ---- Category ----
    def create_category(self, payload, headers):
        return self._request("POST", "/categories", payload, headers)

    def get_category(self, category_id, headers):
        return self._request("GET", f"/categories/{category_id}", headers=headers)

    def update_category(self, category_id, payload, headers):
        return self._request("PATCH", f"/categories/{category_id}", payload, headers)

    def tabulate_category(self, category_id, headers):
        return self._request("POST", f"/categories/{category_id}/tabulate", {}, headers)

    def lock_scoresheets(self, category_id, headers):
        return self._request("POST", f"/categories/{category_id}/lock-scoresheets", {}, headers)

    # ---- Contestant ----
    def create_contestant(self, payload, headers):
        return self._request("POST", "/contestants", payload, headers)

    def get_contestant(self, contestant_id, headers):
        return self._request("GET", f"/contestants/{contestant_id}", headers=headers)

    def set_consent(self, contestant_id, payload, headers):
        return self._request("POST", f"/contestants/{contestant_id}/consents", payload, headers)

    def list_contestant_judges(self, contestant_id, headers):
        return self._request("GET", f"/contestants/{contestant_id}/judges", headers=headers)

    # ---- Judge ----
    def create_judge(self, payload, headers):
        return self._request("POST", "/judges", payload, headers)

    # ---- Entry ----
    def create_entry(self, payload, headers):
        return self._request("POST", "/entries", payload, headers)

    def list_entries(self, headers, params=None):
        return self._request("GET", "/entries", headers=headers, params=params)

    def get_entry(self, entry_id, headers):
        return self._request("GET", f"/entries/{entry_id}", headers=headers)

    def update_entry(self, entry_id, payload, headers):
        return self._request("PATCH", f"/entries/{entry_id}", payload, headers)

    def withdraw_entry(self, entry_id, headers):
        return self._request("POST", f"/entries/{entry_id}/withdraw", {}, headers)

    def disqualify_entry(self, entry_id, headers, payload=None):
        return self._request("POST", f"/entries/{entry_id}/disqualify", payload or {}, headers)

    def safety_check_entry(self, entry_id, payload, headers):
        return self._request("POST", f"/entries/{entry_id}/safety-check", payload, headers)

    # ---- PreJudgingSlot ----
    def create_prejudging_slot(self, payload, headers):
        return self._request("POST", "/prejudging-slots", payload, headers)

    def list_prejudging_slots(self, headers, params=None):
        return self._request("GET", "/prejudging-slots", headers=headers, params=params)

    def get_prejudging_slot(self, slot_id, headers):
        return self._request("GET", f"/prejudging-slots/{slot_id}", headers=headers)

    def book_prejudging_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/prejudging-slots/{slot_id}/book", payload, headers)

    def release_prejudging_slot(self, slot_id, headers):
        return self._request("POST", f"/prejudging-slots/{slot_id}/release", {}, headers)

    def complete_prejudging_slot(self, slot_id, headers):
        return self._request("POST", f"/prejudging-slots/{slot_id}/complete", {}, headers)

    # ---- ScoreSheet ----
    def create_scoresheet(self, payload, headers):
        return self._request("POST", "/scoresheets", payload, headers)

    def list_scoresheets(self, headers, params=None):
        return self._request("GET", "/scoresheets", headers=headers, params=params)

    def get_scoresheet(self, sheet_id, headers):
        return self._request("GET", f"/scoresheets/{sheet_id}", headers=headers)

    def submit_scoresheet(self, sheet_id, headers):
        return self._request("POST", f"/scoresheets/{sheet_id}/submit", {}, headers)

    def reopen_scoresheet(self, sheet_id, headers):
        return self._request("POST", f"/scoresheets/{sheet_id}/reopen", {}, headers)

    # ---- PerformanceSlot ----
    def create_performance_slot(self, payload, headers):
        return self._request("POST", "/performance-slots", payload, headers)

    def list_performance_slots(self, headers, params=None):
        return self._request("GET", "/performance-slots", headers=headers, params=params)

    def get_performance_slot(self, slot_id, headers):
        return self._request("GET", f"/performance-slots/{slot_id}", headers=headers)

    def update_performance_slot(self, slot_id, payload, headers):
        return self._request("PATCH", f"/performance-slots/{slot_id}", payload, headers)

    def advance_performance_slot(self, slot_id, payload, headers):
        return self._request("POST", f"/performance-slots/{slot_id}/advance", payload, headers)

    # ---- PrizeAward ----
    def create_prize_award(self, payload, headers):
        return self._request("POST", "/prize-awards", payload, headers)

    def list_prize_awards(self, headers, params=None):
        return self._request("GET", "/prize-awards", headers=headers, params=params)

    def get_prize_award(self, award_id, headers):
        return self._request("GET", f"/prize-awards/{award_id}", headers=headers)

    def approve_prize_award(self, award_id, headers):
        return self._request("POST", f"/prize-awards/{award_id}/approve", {}, headers)

    def disburse_prize_award(self, award_id, payload, headers):
        return self._request("POST", f"/prize-awards/{award_id}/disburse", payload, headers)

    def mark_tax_reported(self, award_id, headers):
        return self._request("POST", f"/prize-awards/{award_id}/mark-tax-reported", {}, headers)

    def revoke_prize_award(self, award_id, headers):
        return self._request("POST", f"/prize-awards/{award_id}/revoke", {}, headers)

    # ---- GreenRoomBooking ----
    def create_green_room_booking(self, payload, headers):
        return self._request("POST", "/green-room-bookings", payload, headers)

    def list_green_room_bookings(self, headers, params=None):
        return self._request("GET", "/green-room-bookings", headers=headers, params=params)

    def get_green_room_booking(self, booking_id, headers):
        return self._request("GET", f"/green-room-bookings/{booking_id}", headers=headers)

    def cancel_green_room_booking(self, booking_id, headers):
        return self._request("POST", f"/green-room-bookings/{booking_id}/cancel", {}, headers)

    # ---- Logical clock (test-driving) ----
    def set_current_utc(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)


api_client = ApiClient()
