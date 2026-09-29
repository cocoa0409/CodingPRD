"""Payload factories - one per write endpoint, input fields only."""

DEFAULTS = {
    "SCHOOL_NAME": "North High",
    "REGION_CODE": "R-NORTH",
    "CLASSIFICATION": "C3A",
    "SCHOOL_YEAR": "2026-2027",
    "COACH_NAME": "Teri Vance",
    "STUDENT_NAME": "Ada Reyes",
    "BIRTH_DATE": "2009-05-14",
    "GRADE_LEVEL": 11,
    "SIGNER_NAME": "Dr. Lin",
}


def create_school_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["SCHOOL_NAME"],
        "classification": DEFAULTS["CLASSIFICATION"],
        "region_code": DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def create_student_payload(school_id, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "full_name": DEFAULTS["STUDENT_NAME"],
        "birth_date": DEFAULTS["BIRTH_DATE"],
        "grade_level": DEFAULTS["GRADE_LEVEL"],
    }
    payload.update(overrides)
    return payload


def academic_record_payload(**overrides) -> dict:
    payload = {
        "gpa_prior_period": 3.400,
        "gpa_current_period": 3.400,
        "credits_prior_period": 3,
        "credits_current_period": 3,
    }
    payload.update(overrides)
    return payload


def create_staff_credential_payload(school_id, **overrides) -> dict:
    payload = {
        "school_id": school_id,
        "coach_name": DEFAULTS["COACH_NAME"],
        "sport": "FOOTBALL",
        "role_title": "HEAD_COACH",
        "certification_expires_on": "2027-06-30",
    }
    payload.update(overrides)
    return payload


def create_sport_season_payload(**overrides) -> dict:
    payload = {
        "sport": "FOOTBALL",
        "classification": DEFAULTS["CLASSIFICATION"],
        "school_year": DEFAULTS["SCHOOL_YEAR"],
        "sport_tier": "TIER_A",
        "practice_start_date": "2026-08-05",
        "first_contest_date": "2026-09-01",
        "season_end_date": "2026-11-15",
        "age_cutoff_date": "2026-09-01",
        "residency_deadline": "2026-08-20",
        "grading_lock_date": "2026-10-01",
        "contest_limit": 10,
    }
    payload.update(overrides)
    return payload


def create_eligibility_case_payload(student_id, sport_season_id, **overrides) -> dict:
    payload = {"student_id": student_id, "sport_season_id": sport_season_id}
    payload.update(overrides)
    return payload


def create_clearance_document_payload(doc_type, **overrides) -> dict:
    payload = {
        "doc_type": doc_type,
        "issued_on": "2026-07-15",
        "expires_on": "2027-07-15",
        "signer_name": DEFAULTS["SIGNER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_contest_payload(sport_season_id, home_school_id, away_school_id,
                           starts_at, ends_at, expected_sport_season_version,
                           **overrides) -> dict:
    payload = {
        "sport_season_id": sport_season_id,
        "home_school_id": home_school_id,
        "away_school_id": away_school_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "travel_miles": 40,
        "expected_sport_season_version": expected_sport_season_version,
    }
    payload.update(overrides)
    return payload


def create_official_payload(**overrides) -> dict:
    payload = {
        "full_name": "Ola Nkemdi",
        "certification_level": "LEVEL_2",
        "home_region_code": DEFAULTS["REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def create_transport_request_payload(contest_id, requesting_school_id, **overrides) -> dict:
    payload = {
        "contest_id": contest_id,
        "requesting_school_id": requesting_school_id,
        "travel_minutes": 45,
    }
    payload.update(overrides)
    return payload


def create_injury_report_payload(student_id, **overrides) -> dict:
    payload = {"student_id": student_id, "injury_type": "CONCUSSION"}
    payload.update(overrides)
    return payload
