"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "YEAR_LABEL": "2026-2027",
    "YEAR_START": "2026-08-01",
    "YEAR_END": "2027-05-31",
    "NOTICE_DEADLINE": "2026-09-15T00:00:00Z",
    "PORTFOLIO_DUE": "2027-04-30T00:00:00Z",
    "REPORT_DUE": "2027-06-15T00:00:00Z",
    "MID_YEAR": "2027-01-15",
    "FAMILY_NAME": "Test Family",
    "DISTRICT": "D-01",
    "STUDENT_NAME": "Test Student",
    "STUDENT_DOB": "2016-01-01",
    "NOTICE_DISTRICT": "D-01",
    "TEST_NAME": "IOWA",
    "SESSION_DATE": "2026-09-15",
    "SESSION_START": 540,
    "SESSION_END": 660,
    "SESSION_CAPACITY": 10,
    "REGISTRATION_DEADLINE": "2026-09-01T00:00:00Z",
    "CLASS_TITLE": "Co-op Class",
    "CLASS_SUBJECT": "Art",
    "MEETING_DAY": "MON",
    "MEETING_START": 540,
    "MEETING_END": 630,
    "CLASS_START": "2026-08-25",
    "CLASS_END": "2026-12-15",
    "CLASS_CAPACITY": 5,
    "FEE_BASE_CENTS": 10000,
    "MATERIALS_FEE_CENTS": 1000,
    "COURSE_TITLE": "Course",
    "PLANNED_HOURS": 120,
    "COMPLETED_HOURS": 120,
    "LETTER_GRADE": "A",
    "PAYMENT_CENTS": 11000,
}


def create_academic_year_payload(**overrides) -> dict:
    defaults = {
        "label": DEFAULTS["YEAR_LABEL"],
        "start_date": DEFAULTS["YEAR_START"],
        "end_date": DEFAULTS["YEAR_END"],
        "notice_filing_deadline": DEFAULTS["NOTICE_DEADLINE"],
        "portfolio_due_date": DEFAULTS["PORTFOLIO_DUE"],
        "state_report_due_date": DEFAULTS["REPORT_DUE"],
        "mid_year_date": DEFAULTS["MID_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["FAMILY_NAME"],
        "district_code": DEFAULTS["DISTRICT"],
    }
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STUDENT_NAME"],
        "date_of_birth": DEFAULTS["STUDENT_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(academic_year_id, grade_level, **overrides) -> dict:
    defaults = {"academic_year_id": academic_year_id, "grade_level": grade_level}
    defaults.update(overrides)
    return defaults


def create_notice_payload(**overrides) -> dict:
    defaults = {"district_code": DEFAULTS["NOTICE_DISTRICT"]}
    defaults.update(overrides)
    return defaults


def create_curriculum_plan_payload(subjects=None, **overrides) -> dict:
    defaults = {
        "subjects": subjects
        or ["READING", "WRITING", "MATH", "SCIENCE", "SOCIAL_STUDIES"]
    }
    defaults.update(overrides)
    return defaults


def create_attendance_entry_payload(**overrides) -> dict:
    defaults = {"entry_date": "2026-09-01", "minutes": 300}
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(overall_outcome="ACCEPTED", subject_scores=None, **overrides) -> dict:
    defaults = {
        "overall_outcome": overall_outcome,
        "subject_scores": subject_scores
        or [
            {"subject": "READING", "score": 3},
            {"subject": "WRITING", "score": 3},
            {"subject": "MATH", "score": 3},
            {"subject": "SCIENCE", "score": 3},
            {"subject": "SOCIAL_STUDIES", "score": 3},
        ],
    }
    defaults.update(overrides)
    return defaults


def create_exam_session_payload(**overrides) -> dict:
    defaults = {
        "test_name": DEFAULTS["TEST_NAME"],
        "session_date": DEFAULTS["SESSION_DATE"],
        "start_minutes": DEFAULTS["SESSION_START"],
        "end_minutes": DEFAULTS["SESSION_END"],
        "capacity": DEFAULTS["SESSION_CAPACITY"],
        "registration_deadline": DEFAULTS["REGISTRATION_DEADLINE"],
        "target_grades": [5],
    }
    defaults.update(overrides)
    return defaults


def create_course_credit_payload(**overrides) -> dict:
    defaults = {
        "subject": "ELECTIVE",
        "course_title": DEFAULTS["COURSE_TITLE"],
        "planned_hours": DEFAULTS["PLANNED_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_coop_class_payload(**overrides) -> dict:
    defaults = {
        "title": DEFAULTS["CLASS_TITLE"],
        "subject": DEFAULTS["CLASS_SUBJECT"],
        "grade_min": 0,
        "grade_max": 12,
        "meeting_day": DEFAULTS["MEETING_DAY"],
        "meeting_start_minutes": DEFAULTS["MEETING_START"],
        "meeting_end_minutes": DEFAULTS["MEETING_END"],
        "start_date": DEFAULTS["CLASS_START"],
        "end_date": DEFAULTS["CLASS_END"],
        "capacity": DEFAULTS["CLASS_CAPACITY"],
        "fee_base_cents": DEFAULTS["FEE_BASE_CENTS"],
        "materials_fee_cents": DEFAULTS["MATERIALS_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_graduation_application_payload(academic_year_id, **overrides) -> dict:
    defaults = {"academic_year_id": academic_year_id}
    defaults.update(overrides)
    return defaults


def create_ledger_payment_payload(**overrides) -> dict:
    defaults = {"amount_cents": DEFAULTS["PAYMENT_CENTS"]}
    defaults.update(overrides)
    return defaults
