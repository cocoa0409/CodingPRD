"""API client: one method per endpoint defined in the PRD (§4)."""
from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # ------------------------------------------------------------------
    # Logical clock (test-driving endpoint, PRD §2.4)
    # ------------------------------------------------------------------
    def set_clock(self, to_iso8601, headers):
        return self._request("POST", "/reslife/_clock/set_current_utc",
                             {"to_iso8601": to_iso8601}, headers)

    # ------------------------------------------------------------------
    # Terms
    # ------------------------------------------------------------------
    def create_term(self, payload, headers):
        return self._request("POST", "/reslife/terms", payload, headers)

    def list_terms(self, headers, params=None):
        return self._request("GET", "/reslife/terms", headers=headers, params=params)

    def get_term(self, term_id, headers):
        return self._request("GET", f"/reslife/terms/{term_id}", headers=headers)

    def activate_term(self, term_id, headers):
        return self._request("POST", f"/reslife/terms/{term_id}/activate", {}, headers)

    def close_term(self, term_id, headers):
        return self._request("POST", f"/reslife/terms/{term_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Dorms
    # ------------------------------------------------------------------
    def create_dorm(self, payload, headers):
        return self._request("POST", "/reslife/dorms", payload, headers)

    def list_dorms(self, headers, params=None):
        return self._request("GET", "/reslife/dorms", headers=headers, params=params)

    def get_dorm(self, dorm_id, headers):
        return self._request("GET", f"/reslife/dorms/{dorm_id}", headers=headers)

    def close_dorm_for_break(self, dorm_id, headers):
        return self._request("POST", f"/reslife/dorms/{dorm_id}/close-for-break", {}, headers)

    def reopen_dorm(self, dorm_id, headers):
        return self._request("POST", f"/reslife/dorms/{dorm_id}/reopen", {}, headers)

    # ------------------------------------------------------------------
    # Rooms
    # ------------------------------------------------------------------
    def create_room(self, payload, headers):
        return self._request("POST", "/reslife/rooms", payload, headers)

    def list_rooms(self, headers, params=None):
        return self._request("GET", "/reslife/rooms", headers=headers, params=params)

    def get_room(self, room_id, headers):
        return self._request("GET", f"/reslife/rooms/{room_id}", headers=headers)

    def block_room(self, room_id, headers):
        return self._request("POST", f"/reslife/rooms/{room_id}/block", {}, headers)

    def unblock_room(self, room_id, headers):
        return self._request("POST", f"/reslife/rooms/{room_id}/unblock", {}, headers)

    # ------------------------------------------------------------------
    # Parents / Guardians / Staff
    # ------------------------------------------------------------------
    def create_parent(self, payload, headers):
        return self._request("POST", "/reslife/parents", payload, headers)

    def get_parent(self, parent_id, headers):
        return self._request("GET", f"/reslife/parents/{parent_id}", headers=headers)

    def create_guardian(self, payload, headers):
        return self._request("POST", "/reslife/guardians", payload, headers)

    def list_guardians(self, headers, params=None):
        return self._request("GET", "/reslife/guardians", headers=headers, params=params)

    def get_guardian(self, guardian_id, headers):
        return self._request("GET", f"/reslife/guardians/{guardian_id}", headers=headers)

    def approve_guardian(self, guardian_id, headers):
        return self._request("POST", f"/reslife/guardians/{guardian_id}/approve", {}, headers)

    def suspend_guardian(self, guardian_id, headers):
        return self._request("POST", f"/reslife/guardians/{guardian_id}/suspend", {}, headers)

    def create_staff(self, payload, headers):
        return self._request("POST", "/reslife/staff", payload, headers)

    def list_staff(self, headers, params=None):
        return self._request("GET", "/reslife/staff", headers=headers, params=params)

    def get_staff(self, staff_id, headers):
        return self._request("GET", f"/reslife/staff/{staff_id}", headers=headers)

    # ------------------------------------------------------------------
    # Students
    # ------------------------------------------------------------------
    def create_student(self, payload, headers):
        return self._request("POST", "/reslife/students", payload, headers)

    def list_students(self, headers, params=None):
        return self._request("GET", "/reslife/students", headers=headers, params=params)

    def get_student(self, student_id, headers):
        return self._request("GET", f"/reslife/students/{student_id}", headers=headers)

    def patch_student(self, student_id, payload, headers):
        return self._request("PATCH", f"/reslife/students/{student_id}", payload, headers)

    def set_student_enrollment(self, student_id, to_status, headers):
        return self._request("POST", f"/reslife/students/{student_id}/enrollment",
                             {"to_status": to_status}, headers)

    # ------------------------------------------------------------------
    # Dorm assignments
    # ------------------------------------------------------------------
    def create_dorm_assignment(self, payload, headers):
        return self._request("POST", "/reslife/dorm-assignments", payload, headers)

    def list_dorm_assignments(self, headers, params=None):
        return self._request("GET", "/reslife/dorm-assignments", headers=headers, params=params)

    def get_dorm_assignment(self, assignment_id, headers):
        return self._request("GET", f"/reslife/dorm-assignments/{assignment_id}", headers=headers)

    def confirm_dorm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/reslife/dorm-assignments/{assignment_id}/confirm", {}, headers)

    def end_dorm_assignment(self, assignment_id, headers):
        return self._request("POST", f"/reslife/dorm-assignments/{assignment_id}/end", {}, headers)

    def link_roommate(self, assignment_id, roommate_assignment_id, headers):
        return self._request("POST", f"/reslife/dorm-assignments/{assignment_id}/link-roommate",
                             {"roommate_assignment_id": roommate_assignment_id}, headers)

    # ------------------------------------------------------------------
    # Leave requests
    # ------------------------------------------------------------------
    def create_leave_request(self, payload, headers):
        return self._request("POST", "/reslife/leave-requests", payload, headers)

    def list_leave_requests(self, headers, params=None):
        return self._request("GET", "/reslife/leave-requests", headers=headers, params=params)

    def get_leave_request(self, leave_id, headers):
        return self._request("GET", f"/reslife/leave-requests/{leave_id}", headers=headers)

    def parent_decision(self, leave_id, decision, headers, denial_reason=None):
        payload = {"decision": decision}
        if denial_reason is not None:
            payload["denial_reason"] = denial_reason
        return self._request("POST", f"/reslife/leave-requests/{leave_id}/parent-decision",
                             payload, headers)

    def dorm_decision(self, leave_id, decision, headers, denial_reason=None):
        payload = {"decision": decision}
        if denial_reason is not None:
            payload["denial_reason"] = denial_reason
        return self._request("POST", f"/reslife/leave-requests/{leave_id}/dorm-decision",
                             payload, headers)

    def cancel_leave(self, leave_id, headers):
        return self._request("POST", f"/reslife/leave-requests/{leave_id}/cancel", {}, headers)

    def sign_out_leave(self, leave_id, headers):
        return self._request("POST", f"/reslife/leave-requests/{leave_id}/sign-out", {}, headers)

    def return_leave(self, leave_id, headers):
        return self._request("POST", f"/reslife/leave-requests/{leave_id}/return", {}, headers)

    # ------------------------------------------------------------------
    # Sign events
    # ------------------------------------------------------------------
    def create_sign_event(self, payload, headers):
        return self._request("POST", "/reslife/sign-events", payload, headers)

    def list_sign_events(self, headers, params=None):
        return self._request("GET", "/reslife/sign-events", headers=headers, params=params)

    def get_sign_event(self, event_id, headers):
        return self._request("GET", f"/reslife/sign-events/{event_id}", headers=headers)

    # ------------------------------------------------------------------
    # Duty shifts & night checks
    # ------------------------------------------------------------------
    def create_duty_shift(self, payload, headers):
        return self._request("POST", "/reslife/duty-shifts", payload, headers)

    def list_duty_shifts(self, headers, params=None):
        return self._request("GET", "/reslife/duty-shifts", headers=headers, params=params)

    def get_duty_shift(self, shift_id, headers):
        return self._request("GET", f"/reslife/duty-shifts/{shift_id}", headers=headers)

    def request_swap(self, shift_id, target_staff_id, headers):
        return self._request("POST", f"/reslife/duty-shifts/{shift_id}/request-swap",
                             {"target_staff_id": target_staff_id}, headers)

    def swap_respond(self, shift_id, accept, headers):
        return self._request("POST", f"/reslife/duty-shifts/{shift_id}/swap-respond",
                             {"accept": accept}, headers)

    def complete_shift(self, shift_id, headers):
        return self._request("POST", f"/reslife/duty-shifts/{shift_id}/complete", {}, headers)

    def create_night_check(self, shift_id, payload, headers):
        return self._request("POST", f"/reslife/duty-shifts/{shift_id}/night-checks",
                             payload, headers)

    def list_night_checks(self, headers, params=None):
        return self._request("GET", "/reslife/night-checks", headers=headers, params=params)

    def get_night_check(self, check_id, headers):
        return self._request("GET", f"/reslife/night-checks/{check_id}", headers=headers)

    # ------------------------------------------------------------------
    # Health center
    # ------------------------------------------------------------------
    def create_medication_order(self, payload, headers):
        return self._request("POST", "/reslife/medication-orders", payload, headers)

    def list_medication_orders(self, headers, params=None):
        return self._request("GET", "/reslife/medication-orders", headers=headers, params=params)

    def get_medication_order(self, order_id, headers):
        return self._request("GET", f"/reslife/medication-orders/{order_id}", headers=headers)

    def hold_medication_order(self, order_id, reason, headers):
        return self._request("POST", f"/reslife/medication-orders/{order_id}/hold",
                             {"reason": reason}, headers)

    def resume_medication_order(self, order_id, headers):
        return self._request("POST", f"/reslife/medication-orders/{order_id}/resume", {}, headers)

    def discontinue_medication_order(self, order_id, headers):
        return self._request("POST", f"/reslife/medication-orders/{order_id}/discontinue", {}, headers)

    def create_administration(self, order_id, payload, headers):
        return self._request("POST", f"/reslife/medication-orders/{order_id}/administrations",
                             payload, headers)

    def list_administrations(self, headers, params=None):
        return self._request("GET", "/reslife/medication-administrations",
                             headers=headers, params=params)

    def get_administration(self, administration_id, headers):
        return self._request("GET", f"/reslife/medication-administrations/{administration_id}",
                             headers=headers)

    def list_order_administrations(self, order_id, headers):
        return self._request("GET", f"/reslife/medication-orders/{order_id}/administrations",
                             headers=headers)

    # ------------------------------------------------------------------
    # Discipline
    # ------------------------------------------------------------------
    def create_discipline_case(self, payload, headers):
        return self._request("POST", "/reslife/discipline-cases", payload, headers)

    def list_discipline_cases(self, headers, params=None):
        return self._request("GET", "/reslife/discipline-cases", headers=headers, params=params)

    def get_discipline_case(self, case_id, headers):
        return self._request("GET", f"/reslife/discipline-cases/{case_id}", headers=headers)

    def begin_review(self, case_id, headers):
        return self._request("POST", f"/reslife/discipline-cases/{case_id}/begin-review", {}, headers)

    def schedule_hearing(self, case_id, hearing_at, hearing_officer_id, headers):
        return self._request("POST", f"/reslife/discipline-cases/{case_id}/schedule-hearing",
                             {"hearing_at": hearing_at,
                              "hearing_officer_id": hearing_officer_id}, headers)

    def record_outcome(self, case_id, payload, headers):
        return self._request("POST", f"/reslife/discipline-cases/{case_id}/record-outcome",
                             payload, headers)

    def appeal_case(self, case_id, headers):
        return self._request("POST", f"/reslife/discipline-cases/{case_id}/appeal", {}, headers)

    def appeal_decision(self, case_id, decision, headers, adjusted_points=None):
        payload = {"decision": decision}
        if adjusted_points is not None:
            payload["adjusted_points"] = adjusted_points
        return self._request("POST", f"/reslife/discipline-cases/{case_id}/appeal-decision",
                             payload, headers)

    def close_case(self, case_id, headers):
        return self._request("POST", f"/reslife/discipline-cases/{case_id}/close", {}, headers)

    # ------------------------------------------------------------------
    # Breaks & break housing
    # ------------------------------------------------------------------
    def create_break_period(self, payload, headers):
        return self._request("POST", "/reslife/break-periods", payload, headers)

    def list_break_periods(self, headers, params=None):
        return self._request("GET", "/reslife/break-periods", headers=headers, params=params)

    def get_break_period(self, break_id, headers):
        return self._request("GET", f"/reslife/break-periods/{break_id}", headers=headers)

    def create_break_housing_request(self, payload, headers):
        return self._request("POST", "/reslife/break-housing-requests", payload, headers)

    def list_break_housing_requests(self, headers, params=None):
        return self._request("GET", "/reslife/break-housing-requests",
                             headers=headers, params=params)

    def get_break_housing_request(self, request_id, headers):
        return self._request("GET", f"/reslife/break-housing-requests/{request_id}",
                             headers=headers)

    def decide_break_housing(self, request_id, decision, headers):
        return self._request("POST", f"/reslife/break-housing-requests/{request_id}/decide",
                             {"decision": decision}, headers)

    def break_housing_check_in(self, request_id, headers):
        return self._request("POST", f"/reslife/break-housing-requests/{request_id}/check-in",
                             {}, headers)

    def break_housing_check_out(self, request_id, headers):
        return self._request("POST", f"/reslife/break-housing-requests/{request_id}/check-out",
                             {}, headers)

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    def create_storage_unit(self, payload, headers):
        return self._request("POST", "/reslife/storage-units", payload, headers)

    def list_storage_units(self, headers, params=None):
        return self._request("GET", "/reslife/storage-units", headers=headers, params=params)

    def get_storage_unit(self, unit_id, headers):
        return self._request("GET", f"/reslife/storage-units/{unit_id}", headers=headers)

    def create_storage_reservation(self, payload, headers):
        return self._request("POST", "/reslife/storage-reservations", payload, headers)

    def list_storage_reservations(self, headers, params=None):
        return self._request("GET", "/reslife/storage-reservations",
                             headers=headers, params=params)

    def get_storage_reservation(self, reservation_id, headers):
        return self._request("GET", f"/reslife/storage-reservations/{reservation_id}",
                             headers=headers)

    def storage_check_in(self, reservation_id, headers):
        return self._request("POST", f"/reslife/storage-reservations/{reservation_id}/check-in",
                             {}, headers)

    def storage_retrieve(self, reservation_id, headers):
        return self._request("POST", f"/reslife/storage-reservations/{reservation_id}/retrieve",
                             {}, headers)

    def storage_cancel(self, reservation_id, headers):
        return self._request("POST", f"/reslife/storage-reservations/{reservation_id}/cancel",
                             {}, headers)


api_client = ApiClient()
