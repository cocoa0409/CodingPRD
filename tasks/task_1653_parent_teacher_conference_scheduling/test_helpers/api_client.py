"""API client: one method per endpoint declared in PRD 4."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    """Endpoint methods for the Parent-Teacher Conference Scheduling API."""

    # --- Logical clock ---
    def set_clock(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/_clock/set_current_utc", payload, headers)

    # --- Conference windows ---
    def create_window(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/windows", payload, headers)

    def list_windows(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/windows", headers=headers, params=params)

    def get_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/windows/{window_id}", headers=headers)

    def patch_window(self, window_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/conf/windows/{window_id}", payload, headers)

    def publish_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/publish", {}, headers)

    def generate_slots(self, window_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/generate-slots", payload, headers)

    def open_booking(self, window_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/open-booking", {}, headers)

    def lock_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/lock", {}, headers)

    def start_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/start", {}, headers)

    def complete_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/complete", {}, headers)

    def archive_window(self, window_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/archive", {}, headers)

    def run_ops(self, window_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/windows/{window_id}/run-ops", {}, headers)

    def list_window_slots(self, window_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/conf/windows/{window_id}/slots", headers=headers, params=params)

    def get_attendance_report(self, window_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/windows/{window_id}/attendance-report", headers=headers)

    # --- Teachers ---
    def create_teacher(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/teachers", payload, headers)

    def list_teachers(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/teachers", headers=headers, params=params)

    def get_teacher(self, teacher_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/teachers/{teacher_id}", headers=headers)

    def patch_teacher(self, teacher_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/conf/teachers/{teacher_id}", payload, headers)

    def list_teacher_slots(self, teacher_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/conf/teachers/{teacher_id}/slots", headers=headers, params=params)

    def list_teacher_links(self, teacher_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/conf/teachers/{teacher_id}/teacher-links", headers=headers, params=params)

    def get_teacher_summary(self, teacher_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/conf/teachers/{teacher_id}/summary", headers=headers, params=params)

    # --- Families and students ---
    def create_family(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/families", payload, headers)

    def get_family(self, family_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/families/{family_id}", headers=headers)

    def patch_family(self, family_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/conf/families/{family_id}", payload, headers)

    def clear_strikes(self, family_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/families/{family_id}/clear-strikes", {}, headers)

    def list_family_students(self, family_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/conf/families/{family_id}/students", headers=headers, params=params)

    def create_student(self, family_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/conf/families/{family_id}/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/students/{student_id}", headers=headers)

    def withdraw_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/students/{student_id}/withdraw", {}, headers)

    # --- Student-teacher links ---
    def list_student_links(self, student_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/conf/students/{student_id}/teacher-links", headers=headers, params=params)

    def create_teacher_link(self, student_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/conf/students/{student_id}/teacher-links", payload, headers)

    def delete_teacher_link(self, link_id: str, headers: Dict[str, str]):
        return self._request("DELETE", f"/conf/teacher-links/{link_id}", headers=headers)

    # --- Time slots ---
    def get_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/slots/{slot_id}", headers=headers)

    def block_slot(self, slot_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/slots/{slot_id}/block", payload or {}, headers)

    def unblock_slot(self, slot_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/slots/{slot_id}/unblock", {}, headers)

    # --- Bookings ---
    def create_booking(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/bookings", payload, headers)

    def list_bookings(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/bookings", headers=headers, params=params)

    def get_booking(self, booking_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/bookings/{booking_id}", headers=headers)

    def cancel_booking(self, booking_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/bookings/{booking_id}/cancel", payload or {}, headers)

    def reschedule_booking(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/conf/bookings/{booking_id}/reschedule", payload, headers)

    def mark_attendance(self, booking_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/conf/bookings/{booking_id}/attendance", payload, headers)

    # --- Interpreters ---
    def create_interpreter(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/interpreters", payload, headers)

    def list_interpreters(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/interpreters", headers=headers, params=params)

    def get_interpreter(self, interpreter_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/interpreters/{interpreter_id}", headers=headers)

    def patch_interpreter(self, interpreter_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("PATCH", f"/conf/interpreters/{interpreter_id}", payload, headers)

    def get_interpreter_summary(self, interpreter_id: str, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", f"/conf/interpreters/{interpreter_id}/summary", headers=headers, params=params)

    # --- Interpreter requests ---
    def create_interpreter_request(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/interpreter-requests", payload, headers)

    def list_interpreter_requests(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/interpreter-requests", headers=headers, params=params)

    def get_interpreter_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/interpreter-requests/{request_id}", headers=headers)

    def assign_interpreter(self, request_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/interpreter-requests/{request_id}/assign", payload or {}, headers)

    def accept_request(self, request_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/interpreter-requests/{request_id}/accept", {}, headers)

    def decline_request(self, request_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/interpreter-requests/{request_id}/decline", payload or {}, headers)

    def cancel_request(self, request_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/interpreter-requests/{request_id}/cancel", payload or {}, headers)

    # --- Waitlist entries ---
    def create_waitlist_entry(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/waitlist-entries", payload, headers)

    def list_waitlist_entries(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/waitlist-entries", headers=headers, params=params)

    def get_waitlist_entry(self, entry_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/waitlist-entries/{entry_id}", headers=headers)

    def claim_offer(self, entry_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/waitlist-entries/{entry_id}/claim", payload or {}, headers)

    def decline_offer(self, entry_id: str, headers: Dict[str, str]):
        return self._request("POST", f"/conf/waitlist-entries/{entry_id}/decline-offer", {}, headers)

    def withdraw_entry(self, entry_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/waitlist-entries/{entry_id}/withdraw", payload or {}, headers)

    # --- Attendance records ---
    def list_attendance_records(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/attendance-records", headers=headers, params=params)

    def get_attendance_record(self, record_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/attendance-records/{record_id}", headers=headers)

    # --- Outreach tasks ---
    def list_outreach_tasks(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/conf/outreach-tasks", headers=headers, params=params)

    def get_outreach_task(self, task_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/conf/outreach-tasks/{task_id}", headers=headers)

    def create_outreach_task(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/conf/outreach-tasks", payload, headers)

    def contact_task(self, task_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/outreach-tasks/{task_id}/contact", payload or {}, headers)

    def resolve_task(self, task_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/outreach-tasks/{task_id}/resolve", payload or {}, headers)

    def dismiss_task(self, task_id: str, payload: Optional[Dict[str, Any]], headers: Dict[str, str]):
        return self._request("POST", f"/conf/outreach-tasks/{task_id}/dismiss", payload or {}, headers)


api_client = ApiClient()
