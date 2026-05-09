"""Payload factories — input fields only, exact PRD field names."""
from typing import Any, Dict
from .constants import DEFAULT_PACKAGE


def create_student_payload(**overrides) -> Dict[str, Any]:
    p = {
        "full_name": "Test Student",
        "id_number": "ID-1234567",
        "id_card_country": "US",
    }
    p.update(overrides)
    return p


def create_instructor_payload(**overrides) -> Dict[str, Any]:
    p = {
        "full_name": "Test Instructor",
        "license_number": "INS-001",
        "vehicle_qualifications": ["MANUAL_C1"],
    }
    p.update(overrides)
    return p


def create_vehicle_payload(**overrides) -> Dict[str, Any]:
    import uuid
    p = {
        "plate_number": f"PL-{uuid.uuid4().hex[:8].upper()}",
        "vehicle_type": "MANUAL_C1",
    }
    p.update(overrides)
    return p


def create_course_package_payload(**overrides) -> Dict[str, Any]:
    p = dict(DEFAULT_PACKAGE)
    p.update(overrides)
    return p


def create_practice_payload(*, student_id: str, instructor_id: str, vehicle_id: str,
                             training_stage: str, scheduled_start_at: str,
                             scheduled_end_at: str, **overrides) -> Dict[str, Any]:
    p = {
        "student_id": student_id,
        "instructor_id": instructor_id,
        "vehicle_id": vehicle_id,
        "training_stage": training_stage,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    p.update(overrides)
    return p


def create_exam_payload(*, student_id: str, exam_type: str, scheduled_at: str,
                        examiner_id: str, **overrides) -> Dict[str, Any]:
    p = {
        "student_id": student_id,
        "exam_type": exam_type,
        "scheduled_at": scheduled_at,
        "examiner_id": examiner_id,
    }
    p.update(overrides)
    return p


def create_simulator_payload(*, student_id: str, scheduled_start_at: str,
                              scheduled_end_at: str, **overrides) -> Dict[str, Any]:
    p = {
        "student_id": student_id,
        "scheduled_start_at": scheduled_start_at,
        "scheduled_end_at": scheduled_end_at,
    }
    p.update(overrides)
    return p


def create_complaint_payload(*, student_id: str, category: str, description: str,
                              **overrides) -> Dict[str, Any]:
    p = {
        "student_id": student_id,
        "category": category,
        "description": description,
    }
    p.update(overrides)
    return p


def assign_handler_payload(*, handler_id: str, handler_role: str) -> Dict[str, Any]:
    return {"handler_id": handler_id, "handler_role": handler_role}


def reschedule_payload(*, new_scheduled_start_at: str, new_scheduled_end_at: str,
                        new_instructor_id: str = None, new_vehicle_id: str = None) -> Dict[str, Any]:
    p = {
        "new_scheduled_start_at": new_scheduled_start_at,
        "new_scheduled_end_at": new_scheduled_end_at,
    }
    if new_instructor_id is not None:
        p["new_instructor_id"] = new_instructor_id
    if new_vehicle_id is not None:
        p["new_vehicle_id"] = new_vehicle_id
    return p


def medical_cert_payload(expires_on: str) -> Dict[str, Any]:
    return {"medical_cert_expires_on": expires_on}


def select_package_payload(course_package_id: str) -> Dict[str, Any]:
    return {"course_package_id": course_package_id}


def check_out_payload(gps_track_distance_km: float) -> Dict[str, Any]:
    return {"gps_track_distance_km": gps_track_distance_km}


def record_result_payload(score: int) -> Dict[str, Any]:
    return {"score": score}


def resolve_complaint_payload(*, response_text: str, resolution_summary: str) -> Dict[str, Any]:
    return {"response_text": response_text, "resolution_summary": resolution_summary}


def reject_complaint_payload(*, response_text: str) -> Dict[str, Any]:
    return {"response_text": response_text}
