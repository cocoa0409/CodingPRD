"""Payload factories — one per entity, input fields only.

Each factory returns a dict carrying only the server-accepted input fields
for the corresponding create endpoint; system/computed fields are omitted.
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="user"):
    """Generate a globally-unique email for member/instructor creation."""
    return f"{prefix}{next(_email_counter)}@dojo-test.example"


# ----- Program -----
def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Adult Brazilian Jiu-Jitsu",
        "discipline": "BJJ",
        "base_monthly_tuition_cents": 12000,
        "test_fee_cents": 5000,
        "min_attendance_for_test": 0,
        "min_days_in_rank": 0,
    }
    defaults.update(overrides)
    return defaults


# ----- BeltRank -----
def create_belt_rank_payload(code, rank_order, **overrides) -> dict:
    defaults = {
        "code": code,
        "rank_order": rank_order,
    }
    defaults.update(overrides)
    return defaults


# ----- Family -----
def create_family_payload(**overrides) -> dict:
    defaults = {
        "surname": "Sato",
        "billing_email": "sato@dojo-test.example",
    }
    defaults.update(overrides)
    return defaults


# ----- Member -----
def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "email": overrides.pop("email", unique_email("member")),
        "date_of_birth": "1990-01-01",
        "waiver_signed": True,
    }
    defaults.update(overrides)
    return defaults


# ----- Instructor -----
def create_instructor_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Instructor",
        "email": overrides.pop("email", unique_email("instructor")),
    }
    defaults.update(overrides)
    return defaults


# ----- Enrollment -----
def create_enrollment_payload(member_id, program_id, expected_member_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "program_id": program_id,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


# ----- ClassSession -----
def create_class_session_payload(program_id, instructor_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "instructor_id": instructor_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


# ----- Attendance -----
def create_attendance_payload(enrollment_id, class_session_id, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "class_session_id": class_session_id,
    }
    defaults.update(overrides)
    return defaults


# ----- PromotionTest -----
def create_promotion_test_payload(enrollment_id, examiner_instructor_id, scheduled_for, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "examiner_instructor_id": examiner_instructor_id,
        "scheduled_for": scheduled_for,
    }
    defaults.update(overrides)
    return defaults


# ----- Contract -----
def create_contract_payload(member_id, program_id, expected_member_version, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "program_id": program_id,
        "term_months": 12,
        "billing_anchor_day": 1,
        "expected_member_version": expected_member_version,
    }
    defaults.update(overrides)
    return defaults


# ----- PrivateLesson -----
def create_private_lesson_payload(member_id, instructor_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "instructor_id": instructor_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "hourly_rate_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


# ----- TournamentRegistration -----
def create_tournament_registration_payload(member_id, enrollment_id, event_date, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "enrollment_id": enrollment_id,
        "tournament_name": "Test Open",
        "event_date": event_date,
    }
    defaults.update(overrides)
    return defaults


# ----- ProShopOrder -----
def create_pro_shop_order_payload(member_id, line_items, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults
