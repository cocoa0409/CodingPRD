"""Payload factories — one per entity, input fields only.

Field names are exact PRD field names. Each factory supplies sensible
defaults and accepts **overrides for any value a test needs to control.
"""

DEFAULTS = {
    "COVERAGE_START": "2026-04-01T00:00:00Z",
    "COVERAGE_END": "2027-06-01T00:00:00Z",
    "DEADLINE": "2027-01-01T00:00:00Z",
}


def create_counselor_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Counselor",
        "email": "counselor@example.com",
        "hourly_rate_cents": 18000,
        "weekly_review_capacity": 10,
    }
    payload.update(overrides)
    return payload


def create_student_payload(counselor_id, **overrides) -> dict:
    payload = {
        "counselor_id": counselor_id,
        "full_name": "Test Student",
        "email": "student@example.com",
        "grad_year": 2027,
        "gpa": 3.5,
        "sat_total": 1300,
    }
    payload.update(overrides)
    return payload


def create_contract_payload(student_id, billing_model="HOURLY", **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "billing_model": billing_model,
        "coverage_start_utc": DEFAULTS["COVERAGE_START"],
        "coverage_end_utc": DEFAULTS["COVERAGE_END"],
    }
    if billing_model == "HOURLY":
        payload["hourly_rate_cents"] = 20000
    elif billing_model == "PACKAGE":
        payload["package_fee_cents"] = 600000
        payload["package_milestones"] = 3
    payload.update(overrides)
    return payload


def create_billing_entry_payload(contract_id, entry_type, source_kind, amount_cents, **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "entry_type": entry_type,
        "source_kind": source_kind,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_school_list_item_payload(student_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "school_name": "Test University",
        "admit_rate": 0.50,
        "median_sat": 1250,
    }
    payload.update(overrides)
    return payload


def create_application_payload(student_id, school_list_item_id, round="RD", **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "school_list_item_id": school_list_item_id,
        "round": round,
        "deadline_utc": DEFAULTS["DEADLINE"],
    }
    payload.update(overrides)
    return payload


def create_application_task_payload(application_id, task_type="FORM", **overrides) -> dict:
    payload = {
        "application_id": application_id,
        "title": "Test Task",
        "task_type": task_type,
        "due_utc": "2026-12-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_essay_payload(student_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "prompt": "Why us?",
        "word_limit": 650,
    }
    payload.update(overrides)
    return payload


def submit_essay_version_payload(word_count=500, body="Draft text", **overrides) -> dict:
    payload = {"word_count": word_count, "body": body}
    payload.update(overrides)
    return payload


def create_recommendation_payload(student_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "recommender_name": "Mr Recommender",
        "recommender_email": "rec@example.com",
        "rec_type": "TEACHER",
    }
    payload.update(overrides)
    return payload


def create_activity_payload(student_id, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "title": "Test Activity",
        "category": "ARTS",
        "hours_per_week": 2,
        "weeks_per_year": 20,
        "tier": 3,
    }
    payload.update(overrides)
    return payload


def create_scholarship_payload(student_id, award_type="MERIT", gross_amount_cents=1000000, **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "award_name": "Test Award",
        "award_type": award_type,
        "gross_amount_cents": gross_amount_cents,
    }
    payload.update(overrides)
    return payload


def create_appointment_payload(student_id, start_utc, end_utc, meeting_type="STRATEGY", **overrides) -> dict:
    payload = {
        "student_id": student_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "meeting_type": meeting_type,
    }
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
