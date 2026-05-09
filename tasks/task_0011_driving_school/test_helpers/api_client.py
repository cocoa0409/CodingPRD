"""API client: one method per endpoint defined in the PRD."""
from typing import Any, Dict, Optional

from prd_bench_local_runner.testing import GenericApiClient


class ApiClient(GenericApiClient):
    # --- Students ---
    def create_student(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/students", payload, headers)

    def get_student(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/students/{student_id}", headers=headers)

    def verify_identity(self, student_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/students/{student_id}/verify-identity", payload or {}, headers)

    def submit_medical_cert(self, student_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/students/{student_id}/submit-medical-cert", payload, headers)

    def select_package(self, student_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/students/{student_id}/select-package", payload, headers)

    def sign_contract(self, student_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/students/{student_id}/sign-contract", payload or {}, headers)

    def suspend_student(self, student_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/students/{student_id}/suspend", payload or {}, headers)

    def reinstate_student(self, student_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/students/{student_id}/reinstate", payload or {}, headers)

    def get_training_hours(self, student_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/students/{student_id}/training-hours", headers=headers)

    def submit_hours_to_authority(self, student_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/students/{student_id}/submit-hours-to-authority", payload or {}, headers)

    # --- Instructors ---
    def create_instructor(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/instructors", payload, headers)

    def get_instructor(self, instructor_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/instructors/{instructor_id}", headers=headers)

    def suspend_instructor(self, instructor_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/instructors/{instructor_id}/suspend", payload or {}, headers)

    def reinstate_instructor(self, instructor_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/instructors/{instructor_id}/reinstate", payload or {}, headers)

    # --- Vehicles ---
    def create_vehicle(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/vehicles", payload, headers)

    def get_vehicle(self, vehicle_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/vehicles/{vehicle_id}", headers=headers)

    def set_vehicle_maintenance(self, vehicle_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/vehicles/{vehicle_id}/set-maintenance", payload or {}, headers)

    def restore_vehicle_active(self, vehicle_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/vehicles/{vehicle_id}/restore-active", payload or {}, headers)

    # --- Course packages ---
    def create_course_package(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/course-packages", payload, headers)

    def get_course_package(self, package_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/course-packages/{package_id}", headers=headers)

    # --- Practice appointments ---
    def book_practice(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/practice-appointments", payload, headers)

    def get_practice(self, practice_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/practice-appointments/{practice_id}", headers=headers)

    def cancel_practice(self, practice_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/practice-appointments/{practice_id}/cancel", payload or {}, headers)

    def check_in_practice(self, practice_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/practice-appointments/{practice_id}/check-in", payload or {}, headers)

    def check_out_practice(self, practice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/practice-appointments/{practice_id}/check-out", payload, headers)

    def reschedule_practice(self, practice_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/practice-appointments/{practice_id}/reschedule", payload, headers)

    # --- Exam appointments ---
    def book_exam(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/exam-appointments", payload, headers)

    def get_exam(self, exam_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/exam-appointments/{exam_id}", headers=headers)

    def record_exam_result(self, exam_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/exam-appointments/{exam_id}/record-result", payload, headers)

    def cancel_exam(self, exam_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/exam-appointments/{exam_id}/cancel", payload or {}, headers)

    # --- Simulator sessions ---
    def book_simulator(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/simulator-sessions", payload, headers)

    def cancel_simulator(self, session_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/simulator-sessions/{session_id}/cancel", payload or {}, headers)

    def complete_simulator(self, session_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/simulator-sessions/{session_id}/complete", payload or {}, headers)

    # --- Complaints ---
    def file_complaint(self, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", "/complaints", payload, headers)

    def get_complaint(self, complaint_id: str, headers: Dict[str, str]):
        return self._request("GET", f"/complaints/{complaint_id}", headers=headers)

    def assign_handler(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/assign-handler", payload, headers)

    def escalate_complaint(self, complaint_id: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None):
        return self._request("POST", f"/complaints/{complaint_id}/escalate", payload or {}, headers)

    def resolve_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/resolve", payload, headers)

    def reject_complaint(self, complaint_id: str, payload: Dict[str, Any], headers: Dict[str, str]):
        return self._request("POST", f"/complaints/{complaint_id}/reject", payload, headers)

    # --- Audit ---
    def list_audit_logs(self, headers: Dict[str, str], params: Optional[Dict] = None):
        return self._request("GET", "/audit-logs", headers=headers, params=params)

    # --- Test-driving control endpoints ---
    def advance_clock(self, minutes: int, headers: Dict[str, str]):
        return self._request("POST", "/_clock/advance", {"minutes": minutes}, headers)

    def run_sweep(self, headers: Dict[str, str]):
        return self._request("POST", "/_sweep/run", {}, headers)


api_client = ApiClient()
