"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────
    def set_clock(self, to_iso8601, headers):
        return self._request(
            "POST", "/_clock/set_current_utc", {"to_iso8601": to_iso8601}, headers
        )

    # ─── Agency ──────────────────────────────────────
    def create_agency(self, payload, headers):
        return self._request("POST", "/agencies", payload, headers)

    def get_agency(self, agency_id, headers):
        return self._request("GET", f"/agencies/{agency_id}", headers=headers)

    # ─── CastingDirector ─────────────────────────────
    def create_casting_director(self, payload, headers):
        return self._request("POST", "/casting-directors", payload, headers)

    def get_casting_director(self, cd_id, headers):
        return self._request("GET", f"/casting-directors/{cd_id}", headers=headers)

    # ─── Talent ──────────────────────────────────────
    def create_talent(self, payload, headers):
        return self._request("POST", "/talents", payload, headers)

    def list_talents(self, headers, params=None):
        return self._request("GET", "/talents", headers=headers, params=params)

    def get_talent(self, talent_id, headers):
        return self._request("GET", f"/talents/{talent_id}", headers=headers)

    def get_talent_availability_summary(self, talent_id, headers):
        return self._request(
            "GET", f"/talents/{talent_id}/availability-summary", headers=headers
        )

    def roster_talent(self, talent_id, headers):
        return self._request("POST", f"/talents/{talent_id}/roster", {}, headers)

    def suspend_talent(self, talent_id, headers):
        return self._request("POST", f"/talents/{talent_id}/suspend", {}, headers)

    def archive_talent(self, talent_id, headers):
        return self._request("POST", f"/talents/{talent_id}/archive", {}, headers)

    # ─── CompCard ────────────────────────────────────
    def create_comp_card(self, payload, headers):
        return self._request("POST", "/comp-cards", payload, headers)

    def list_comp_cards(self, headers, params=None):
        return self._request("GET", "/comp-cards", headers=headers, params=params)

    def get_comp_card(self, cc_id, headers):
        return self._request("GET", f"/comp-cards/{cc_id}", headers=headers)

    # ─── CastingCall ─────────────────────────────────
    def create_casting_call(self, payload, headers):
        return self._request("POST", "/casting-calls", payload, headers)

    def list_casting_calls(self, headers, params=None):
        return self._request("GET", "/casting-calls", headers=headers, params=params)

    def get_casting_call(self, call_id, headers):
        return self._request("GET", f"/casting-calls/{call_id}", headers=headers)

    def close_casting_call(self, call_id, headers):
        return self._request("POST", f"/casting-calls/{call_id}/close", {}, headers)

    def reopen_casting_call(self, call_id, headers):
        return self._request("POST", f"/casting-calls/{call_id}/reopen", {}, headers)

    # ─── Submission ──────────────────────────────────
    def create_submission(self, payload, headers):
        return self._request("POST", "/submissions", payload, headers)

    def list_submissions(self, headers, params=None):
        return self._request("GET", "/submissions", headers=headers, params=params)

    def get_submission(self, sub_id, headers):
        return self._request("GET", f"/submissions/{sub_id}", headers=headers)

    def decline_submission(self, sub_id, headers):
        return self._request("POST", f"/submissions/{sub_id}/decline", {}, headers)

    def withdraw_submission(self, sub_id, headers):
        return self._request("POST", f"/submissions/{sub_id}/withdraw", {}, headers)

    # ─── AuditionSlot ────────────────────────────────
    def create_audition_slot(self, payload, headers):
        return self._request("POST", "/audition-slots", payload, headers)

    def list_audition_slots(self, headers, params=None):
        return self._request("GET", "/audition-slots", headers=headers, params=params)

    def get_audition_slot(self, slot_id, headers):
        return self._request("GET", f"/audition-slots/{slot_id}", headers=headers)

    def complete_audition_slot(self, slot_id, headers):
        return self._request("POST", f"/audition-slots/{slot_id}/complete", {}, headers)

    def release_audition_slot(self, slot_id, headers):
        return self._request("POST", f"/audition-slots/{slot_id}/release", {}, headers)

    # ─── AvailabilityHold ────────────────────────────
    def create_availability_hold(self, payload, headers):
        return self._request("POST", "/availability-holds", payload, headers)

    def list_availability_holds(self, headers, params=None):
        return self._request(
            "GET", "/availability-holds", headers=headers, params=params
        )

    def get_availability_hold(self, hold_id, headers):
        return self._request("GET", f"/availability-holds/{hold_id}", headers=headers)

    def release_availability_hold(self, hold_id, headers):
        return self._request(
            "POST", f"/availability-holds/{hold_id}/release", {}, headers
        )

    # ─── DealMemo ────────────────────────────────────
    def create_deal_memo(self, payload, headers):
        return self._request("POST", "/deal-memos", payload, headers)

    def list_deal_memos(self, headers, params=None):
        return self._request("GET", "/deal-memos", headers=headers, params=params)

    def get_deal_memo(self, dm_id, headers):
        return self._request("GET", f"/deal-memos/{dm_id}", headers=headers)

    def offer_deal_memo(self, dm_id, payload, headers):
        return self._request("POST", f"/deal-memos/{dm_id}/offer", payload, headers)

    def counter_deal_memo(self, dm_id, payload, headers):
        return self._request("POST", f"/deal-memos/{dm_id}/counter", payload, headers)

    def accept_deal_memo(self, dm_id, headers):
        return self._request("POST", f"/deal-memos/{dm_id}/accept", {}, headers)

    def reject_deal_memo(self, dm_id, headers):
        return self._request("POST", f"/deal-memos/{dm_id}/reject", {}, headers)

    # ─── Booking ─────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def confirm_booking(self, booking_id, payload, headers):
        return self._request(
            "POST", f"/bookings/{booking_id}/confirm", payload, headers
        )

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    # ─── CommissionEntry ─────────────────────────────
    def list_commission_entries(self, headers, params=None):
        return self._request(
            "GET", "/commission-entries", headers=headers, params=params
        )

    def get_commission_entry(self, entry_id, headers):
        return self._request(
            "GET", f"/commission-entries/{entry_id}", headers=headers
        )

    # ─── Payment ─────────────────────────────────────
    def create_payment(self, payload, headers):
        return self._request("POST", "/payments", payload, headers)

    def list_payments(self, headers, params=None):
        return self._request("GET", "/payments", headers=headers, params=params)

    def get_payment(self, payment_id, headers):
        return self._request("GET", f"/payments/{payment_id}", headers=headers)

    # ─── ResidualSchedule ────────────────────────────
    def create_residual_schedule(self, payload, headers):
        return self._request("POST", "/residual-schedules", payload, headers)

    def list_residual_schedules(self, headers, params=None):
        return self._request(
            "GET", "/residual-schedules", headers=headers, params=params
        )

    def get_residual_schedule(self, res_id, headers):
        return self._request("GET", f"/residual-schedules/{res_id}", headers=headers)

    def pay_residual_schedule(self, res_id, headers):
        return self._request(
            "POST", f"/residual-schedules/{res_id}/pay", {}, headers
        )

    def void_residual_schedule(self, res_id, headers):
        return self._request(
            "POST", f"/residual-schedules/{res_id}/void", {}, headers
        )


api_client = ApiClient()
