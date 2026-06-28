"""Payload factories — one per entity, input fields only."""


def create_tier_payload(**overrides) -> dict:
    """Required: code, level, base_annual_cents, deposit_pct.
    Optional (server-defaulted): installments, extended_day_annual_cents, active."""
    defaults = {
        "code": "STANDARD",
        "level": "PRIMARY",
        "base_annual_cents": 1_000_000,
        "deposit_pct": 0.10,
        "installments": 10,
    }
    defaults.update(overrides)
    return defaults


def create_classroom_payload(**overrides) -> dict:
    """Required: name, level, capacity, min_age_months, max_age_months."""
    defaults = {
        "name": "Primary Room",
        "level": "PRIMARY",
        "capacity": 5,
        "min_age_months": 36,
        "max_age_months": 72,
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(parent_user_id="parent-1", **overrides) -> dict:
    """Required: parent_user_id, full_name, date_of_birth.
    Optional: sibling_of_student_id, staff_child."""
    defaults = {
        "parent_user_id": parent_user_id,
        "full_name": "Test Child",
        "date_of_birth": "2022-09-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(student_id, classroom_id, tier_id, **overrides) -> dict:
    """Required: student_id, classroom_id, tier_id.
    Optional: extended_day_opt_in, financial_aid_pct."""
    defaults = {
        "student_id": student_id,
        "classroom_id": classroom_id,
        "tier_id": tier_id,
    }
    defaults.update(overrides)
    return defaults


def accept_offer_payload(program_start_date="2026-09-01T00:00:00Z", **overrides) -> dict:
    """Required: program_start_date."""
    defaults = {"program_start_date": program_start_date}
    defaults.update(overrides)
    return defaults


def create_payment_payload(enrollment_id, kind, amount_cents, **overrides) -> dict:
    """Required: enrollment_id, kind, amount_cents."""
    defaults = {
        "enrollment_id": enrollment_id,
        "kind": kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_refund_request_payload(enrollment_id, effective_date, method, **overrides) -> dict:
    """Required: enrollment_id, effective_date, method."""
    defaults = {
        "enrollment_id": enrollment_id,
        "effective_date": effective_date,
        "method": method,
    }
    defaults.update(overrides)
    return defaults


def create_staff_assignment_payload(classroom_id, expected_classroom_version,
                                     staff_name="Maria", **overrides) -> dict:
    """Required: classroom_id, staff_name, expected_classroom_version."""
    defaults = {
        "classroom_id": classroom_id,
        "staff_name": staff_name,
        "expected_classroom_version": expected_classroom_version,
    }
    defaults.update(overrides)
    return defaults


def end_staff_assignment_payload(expected_classroom_version, **overrides) -> dict:
    """Required: expected_classroom_version."""
    defaults = {"expected_classroom_version": expected_classroom_version}
    defaults.update(overrides)
    return defaults


def create_assessment_record_payload(student_id, enrollment_id, work_area,
                                      mastery_level, work_cycle_date, **overrides) -> dict:
    """Required: student_id, enrollment_id, work_area, mastery_level, work_cycle_date.
    Optional: portfolio_included."""
    defaults = {
        "student_id": student_id,
        "enrollment_id": enrollment_id,
        "work_area": work_area,
        "mastery_level": mastery_level,
        "work_cycle_date": work_cycle_date,
    }
    defaults.update(overrides)
    return defaults


def create_conference_slot_payload(guide_user_id, classroom_id, start_at, end_at,
                                    **overrides) -> dict:
    """Required: guide_user_id, classroom_id, start_at, end_at."""
    defaults = {
        "guide_user_id": guide_user_id,
        "classroom_id": classroom_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def book_slot_payload(booked_student_id, **overrides) -> dict:
    """Required: booked_student_id."""
    defaults = {"booked_student_id": booked_student_id}
    defaults.update(overrides)
    return defaults


def create_observation_payload(classroom_id, observer_name, window_start_at,
                               window_end_at, **overrides) -> dict:
    """Required: classroom_id, observer_name, window_start_at, window_end_at."""
    defaults = {
        "classroom_id": classroom_id,
        "observer_name": observer_name,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    defaults.update(overrides)
    return defaults
