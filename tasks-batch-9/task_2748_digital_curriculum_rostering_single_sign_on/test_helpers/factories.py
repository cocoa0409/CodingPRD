"""
Payload factories for the Digital Curriculum Rostering & Single Sign-On API.

Each builder returns a valid request body for one endpoint with sensible,
contract-legal defaults, and lets a test override any field with a keyword
argument (pass None to drop an optional field). Identifiers that the contract
declares unique are made unique per process so that a test can create many rows
of the same kind without tripping the duplicate-identifier rungs.

Money is always an integer number of cents and seats are always integers — no
monetary or seat value is ever emitted as a string.
"""

import itertools

from .constants import (
    STANDARD_PRICE_PER_SEAT_CENTS,
    TERM_ADD_DROP_CUTOFF_DATE,
    TERM_ARCHIVE_RETENTION_DAYS,
    TERM_END_DATE,
    TERM_INSTRUCTIONAL_DAYS,
    TERM_NAME,
    TERM_SCHOOL_YEAR,
    TERM_START_DATE,
)
from .types import (
    AllocationPolicy,
    GradeBand,
    IdentifierStrategy,
    MeetingDay,
    RosteringStandard,
    RunType,
    SeatModel,
    Subject,
    SubjectType,
)

_counter = itertools.count(1)


def next_sequence() -> int:
    """A monotonically increasing integer for building unique identifiers."""
    return next(_counter)


def _merge(payload: dict, overrides: dict) -> dict:
    """Apply overrides; a None override removes the key entirely."""
    result = dict(payload)
    for key, value in overrides.items():
        if value is None:
            result.pop(key, None)
        else:
            result[key] = value
    return result


# ── School ───────────────────────────────────────────────────────────────────

def school_payload(grade_band=GradeBand.ELEMENTARY, **overrides) -> dict:
    """POST /rostering/schools — policy fields omitted so district defaults apply."""
    n = next_sequence()
    payload = {
        "name": f"Building {n}",
        "sis_school_id": f"SCH-{n:04d}",
        "building_code": f"B{n:03d}",
        "grade_band": grade_band,
    }
    return _merge(payload, overrides)


def school_policy_patch(**overrides) -> dict:
    """PATCH /rostering/schools/{school_id}"""
    return dict(overrides)


# ── Term ─────────────────────────────────────────────────────────────────────

def term_payload(**overrides) -> dict:
    """POST /rostering/terms — the standard Fall 2026 term."""
    payload = {
        "name": TERM_NAME,
        "school_year": TERM_SCHOOL_YEAR,
        "start_date": TERM_START_DATE,
        "end_date": TERM_END_DATE,
        "add_drop_cutoff_date": TERM_ADD_DROP_CUTOFF_DATE,
        "instructional_days": TERM_INSTRUCTIONAL_DAYS,
        "archive_retention_days": TERM_ARCHIVE_RETENTION_DAYS,
    }
    return _merge(payload, overrides)


# ── Teacher ──────────────────────────────────────────────────────────────────

def teacher_payload(school_id, **overrides) -> dict:
    """POST /rostering/teachers"""
    n = next_sequence()
    payload = {
        "school_id": school_id,
        "sis_staff_id": f"STF-{n:04d}",
        "full_name": f"Teacher {n}",
        "email": f"teacher{n}@district.k12",
    }
    return _merge(payload, overrides)


def separation_payload(separation_effective_date, **overrides) -> dict:
    """POST /rostering/teachers/{teacher_id}/separate"""
    return _merge({"separation_effective_date": separation_effective_date}, overrides)


# ── Student ──────────────────────────────────────────────────────────────────

def student_payload(school_id, grade_level=3, **overrides) -> dict:
    """POST /rostering/students"""
    n = next_sequence()
    payload = {
        "school_id": school_id,
        "sis_student_id": f"STU-{n:04d}",
        "first_name": f"First{n}",
        "last_name": f"Last{n}",
        "grade_level": grade_level,
        "date_of_birth": "2016-05-04",
    }
    return _merge(payload, overrides)


def withdrawal_payload(withdrawal_effective_date, **overrides) -> dict:
    """POST /rostering/students/{student_id}/withdraw"""
    return _merge({"withdrawal_effective_date": withdrawal_effective_date}, overrides)


# ── Section ──────────────────────────────────────────────────────────────────

def section_payload(school_id, term_id, primary_teacher_id=None, period_index=1,
                    meeting_days=None, max_seats=30, **overrides) -> dict:
    """POST /rostering/sections"""
    n = next_sequence()
    payload = {
        "school_id": school_id,
        "term_id": term_id,
        "sis_section_id": f"SEC-{n:04d}",
        "course_code": f"CRS-{n:03d}",
        "subject": Subject.MATH,
        "period_index": period_index,
        "meeting_days": list(meeting_days) if meeting_days else list(MeetingDay.MWF),
        "max_seats": max_seats,
    }
    if primary_teacher_id is not None:
        payload["primary_teacher_id"] = primary_teacher_id
    return _merge(payload, overrides)


def section_patch(**overrides) -> dict:
    """PATCH /rostering/sections/{section_id}"""
    return dict(overrides)


# ── Enrollment ───────────────────────────────────────────────────────────────

def enrollment_payload(section_id, student_id, requested_effective_date,
                       **overrides) -> dict:
    """POST /rostering/enrollments"""
    payload = {
        "section_id": section_id,
        "student_id": student_id,
        "requested_effective_date": requested_effective_date,
    }
    return _merge(payload, overrides)


def drop_payload(drop_effective_date, **overrides) -> dict:
    """POST /rostering/enrollments/{enrollment_id}/drop"""
    return _merge({"drop_effective_date": drop_effective_date}, overrides)


# ── VendorApp (licence) ──────────────────────────────────────────────────────

def vendor_app_payload(term_id, total_seats=10,
                       price_per_seat_cents=STANDARD_PRICE_PER_SEAT_CENTS,
                       grade_band_scope=None, **overrides) -> dict:
    """POST /rostering/vendor-apps — a DRAFT licence with defaults applied."""
    n = next_sequence()
    payload = {
        "name": f"Vendor App {n}",
        "vendor_code": f"VND-{n:04d}",
        "term_id": term_id,
        "rostering_standard": RosteringStandard.ONEROSTER_REST_1P2,
        "identifier_strategy": IdentifierStrategy.SIS_ID,
        "username_domain": "apps.district.k12",
        "grade_band_scope": list(grade_band_scope) if grade_band_scope
        else [GradeBand.ELEMENTARY],
        "seat_model": SeatModel.PER_STUDENT,
        "allocation_policy": AllocationPolicy.PROPORTIONAL_HEADCOUNT,
        "total_seats": total_seats,
        "price_per_seat_cents": price_per_seat_cents,
    }
    return _merge(payload, overrides)


def vendor_app_patch(**overrides) -> dict:
    """PATCH /rostering/vendor-apps/{vendor_app_id}"""
    return dict(overrides)


# ── BuildingAllocation ───────────────────────────────────────────────────────

def allocation_patch(allocated_seats, expected_vendor_app_version, **overrides) -> dict:
    """PATCH /rostering/building-allocations/{building_allocation_id}"""
    payload = {
        "allocated_seats": allocated_seats,
        "expected_vendor_app_version": expected_vendor_app_version,
    }
    return _merge(payload, overrides)


# ── AppAccount ───────────────────────────────────────────────────────────────

def app_account_payload(building_allocation_id, expected_vendor_app_version,
                        student_id=None, teacher_id=None, **overrides) -> dict:
    """
    POST /rostering/app-accounts — carries exactly one of student_id or
    teacher_id, and the subject_type that agrees with it.
    """
    payload = {
        "building_allocation_id": building_allocation_id,
        "expected_vendor_app_version": expected_vendor_app_version,
    }
    if student_id is not None:
        payload["subject_type"] = SubjectType.STUDENT
        payload["student_id"] = student_id
    elif teacher_id is not None:
        payload["subject_type"] = SubjectType.TEACHER
        payload["teacher_id"] = teacher_id
    return _merge(payload, overrides)


def password_set_payload(new_password, **overrides) -> dict:
    """POST /rostering/app-accounts/{app_account_id}/password-set"""
    return _merge({"new_password": new_password}, overrides)


def usage_payload(activity_date, active_minutes, **overrides) -> dict:
    """POST /rostering/app-accounts/{app_account_id}/record-usage"""
    payload = {"activity_date": activity_date, "active_minutes": active_minutes}
    return _merge(payload, overrides)


def deprovision_payload(effective_date, **overrides) -> dict:
    """POST /rostering/app-accounts/{app_account_id}/deprovision"""
    return _merge({"effective_date": effective_date}, overrides)


# ── SyncRun ──────────────────────────────────────────────────────────────────

def sync_run_payload(vendor_app_id, run_type=RunType.FULL, **overrides) -> dict:
    """POST /rostering/sync-runs"""
    return _merge({"vendor_app_id": vendor_app_id, "run_type": run_type}, overrides)


# ── ErrorQueueItem triage ────────────────────────────────────────────────────

def resolve_match_payload(replacement_teacher_id, **overrides) -> dict:
    """POST /rostering/error-queue-items/{id}/resolve-match"""
    return _merge({"replacement_teacher_id": replacement_teacher_id}, overrides)


def merge_duplicate_payload(surviving_student_id, **overrides) -> dict:
    """POST /rostering/error-queue-items/{id}/merge-duplicate"""
    return _merge({"surviving_student_id": surviving_student_id}, overrides)
