"""API client: one method per endpoint defined in the PRD (§4).

Subclasses the framework's GenericApiClient; the base `_request()` is inherited.
GET requests pass filters/pagination via `params`; POST requests pass `payload`
as a JSON body.
"""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ─── Logical clock ───────────────────────────────────────────────────────
    def set_clock(self, payload, headers):
        return self._request("POST", "/_clock/set_current_utc", payload, headers)

    # ─── Trainer ─────────────────────────────────────────────────────────────
    def create_trainer(self, payload, headers):
        return self._request("POST", "/trainers", payload, headers)

    def get_trainer(self, trainer_id, headers):
        return self._request("GET", f"/trainers/{trainer_id}", headers=headers)

    # ─── Client ──────────────────────────────────────────────────────────────
    def create_client(self, payload, headers):
        return self._request("POST", "/clients", payload, headers)

    def get_client(self, client_id, headers):
        return self._request("GET", f"/clients/{client_id}", headers=headers)

    def list_clients(self, headers, params=None):
        return self._request("GET", "/clients", headers=headers, params=params)

    def submit_intake(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/submit-intake", {}, headers)

    def assess_client(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/assess", {}, headers)

    def return_intake(self, client_id, headers):
        return self._request("POST", f"/clients/{client_id}/return-intake", {}, headers)

    # ─── Engagement ──────────────────────────────────────────────────────────
    def create_engagement(self, payload, headers):
        return self._request("POST", "/engagements", payload, headers)

    def get_engagement(self, engagement_id, headers):
        return self._request("GET", f"/engagements/{engagement_id}", headers=headers)

    def list_engagements(self, headers, params=None):
        return self._request("GET", "/engagements", headers=headers, params=params)

    def pause_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/pause", {}, headers)

    def resume_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/resume", {}, headers)

    def end_engagement(self, engagement_id, headers):
        return self._request("POST", f"/engagements/{engagement_id}/end", {}, headers)

    # ─── SessionPack ─────────────────────────────────────────────────────────
    def create_session_pack(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/session-packs", payload, headers)

    def list_session_packs(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/session-packs", headers=headers, params=params)

    def get_session_pack(self, pack_id, headers):
        return self._request("GET", f"/session-packs/{pack_id}", headers=headers)

    def session_pack_invoice(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/session-packs/invoice", payload, headers)

    # ─── Booking ─────────────────────────────────────────────────────────────
    def create_booking(self, payload, headers):
        return self._request("POST", "/bookings", payload, headers)

    def get_booking(self, booking_id, headers):
        return self._request("GET", f"/bookings/{booking_id}", headers=headers)

    def list_bookings(self, headers, params=None):
        return self._request("GET", "/bookings", headers=headers, params=params)

    def cancel_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/cancel", {}, headers)

    def complete_booking(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/complete", {}, headers)

    def mark_no_show(self, booking_id, headers):
        return self._request("POST", f"/bookings/{booking_id}/mark-no-show", {}, headers)

    def reschedule_booking(self, booking_id, payload, headers):
        return self._request("POST", f"/bookings/{booking_id}/reschedule", payload, headers)

    # ─── ProgramAssignment ───────────────────────────────────────────────────
    def create_program_assignment(self, payload, headers):
        return self._request("POST", "/program-assignments", payload, headers)

    def get_program_assignment(self, program_id, headers):
        return self._request("GET", f"/program-assignments/{program_id}", headers=headers)

    def list_program_assignments(self, headers, params=None):
        return self._request("GET", "/program-assignments", headers=headers, params=params)

    def publish_program(self, program_id, headers):
        return self._request("POST", f"/program-assignments/{program_id}/publish", {}, headers)

    def archive_program(self, program_id, headers):
        return self._request("POST", f"/program-assignments/{program_id}/archive", {}, headers)

    # ─── MacroPlan ───────────────────────────────────────────────────────────
    def create_macro_plan(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/macro-plans", payload, headers)

    def get_macro_plan(self, macro_plan_id, headers):
        return self._request("GET", f"/macro-plans/{macro_plan_id}", headers=headers)

    def list_macro_plans(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/macro-plans", headers=headers, params=params)

    def lock_macro_plan(self, macro_plan_id, headers):
        return self._request("POST", f"/macro-plans/{macro_plan_id}/lock", {}, headers)

    # ─── CheckIn ─────────────────────────────────────────────────────────────
    def create_check_in(self, engagement_id, payload, headers):
        return self._request("POST", f"/engagements/{engagement_id}/check-ins", payload, headers)

    def get_check_in(self, check_in_id, headers):
        return self._request("GET", f"/check-ins/{check_in_id}", headers=headers)

    def list_check_ins(self, engagement_id, headers, params=None):
        return self._request("GET", f"/engagements/{engagement_id}/check-ins", headers=headers, params=params)

    def request_revision(self, check_in_id, headers):
        return self._request("POST", f"/check-ins/{check_in_id}/request-revision", {}, headers)

    def resubmit_check_in(self, check_in_id, payload, headers):
        return self._request("POST", f"/check-ins/{check_in_id}/resubmit", payload, headers)

    def assess_check_in(self, check_in_id, headers):
        return self._request("POST", f"/check-ins/{check_in_id}/assess", {}, headers)

    # ─── HabitLog (append-only) ──────────────────────────────────────────────
    def create_habit_log(self, payload, headers):
        return self._request("POST", "/habit-logs", payload, headers)

    def get_habit_log(self, habit_log_id, headers):
        return self._request("GET", f"/habit-logs/{habit_log_id}", headers=headers)

    def list_habit_logs(self, headers, params=None):
        return self._request("GET", "/habit-logs", headers=headers, params=params)

    # ─── Message (append-only) ───────────────────────────────────────────────
    def create_message(self, payload, headers):
        return self._request("POST", "/messages", payload, headers)

    def get_message(self, message_id, headers):
        return self._request("GET", f"/messages/{message_id}", headers=headers)

    def list_messages(self, headers, params=None):
        return self._request("GET", "/messages", headers=headers, params=params)


api_client = ApiClient()
