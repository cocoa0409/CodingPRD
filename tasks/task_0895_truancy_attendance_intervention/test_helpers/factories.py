"""Payload factories — one per entity, input fields only."""


def create_school_payload(name="Test School", **overrides) -> dict:
    """Only `name` is required; the four thresholds, required_instructional_days,
    and chronic_absence_pct_threshold default server-side when omitted."""
    payload = {"name": name}
    payload.update(overrides)
    return payload


def create_staff_payload(school_id, full_name="Test Staff", role_type="CASE_MANAGER", **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "full_name": full_name,
        "role_type": role_type,
    }
    payload.update(overrides)
    return payload


def create_student_payload(school_id, full_name="Test Student", grade_level=9, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "full_name": full_name,
        "grade_level": grade_level,
    }
    payload.update(overrides)
    return payload


def create_attendance_record_payload(attendance_date, status, **overrides) -> dict:
    payload = {"attendance_date": attendance_date, "status": status}
    payload.update(overrides)
    return payload


def create_case_payload(student_id, **overrides) -> dict:
    payload = {"student_id": student_id}
    payload.update(overrides)
    return payload


def make_goal(description="Goal", weight=1, target_value=1, met_value=0) -> dict:
    return {
        "description": description,
        "weight": weight,
        "target_value": target_value,
        "met_value": met_value,
    }


def create_contract_payload(start_date, end_date, goals, expected_case_version, **overrides) -> dict:
    payload = {
        "start_date": start_date,
        "end_date": end_date,
        "goals": goals,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def create_conference_payload(scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {"scheduled_start": scheduled_start, "scheduled_end": scheduled_end}
    payload.update(overrides)
    return payload


def create_service_referral_payload(service_type="MENTOR", **overrides) -> dict:
    payload = {"service_type": service_type}
    payload.update(overrides)
    return payload


def create_court_citation_payload(courtroom_id, hearing_start, hearing_end, **overrides) -> dict:
    payload = {
        "courtroom_id": courtroom_id,
        "hearing_start": hearing_start,
        "hearing_end": hearing_end,
    }
    payload.update(overrides)
    return payload


def create_compliance_check_payload(check_date, result, **overrides) -> dict:
    payload = {"check_date": check_date, "result": result}
    payload.update(overrides)
    return payload
