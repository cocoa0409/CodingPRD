"""Payload factories — one per entity, input fields only."""


def create_creator_payload(**overrides) -> dict:
    defaults = {"email": "creator@example.com", "display_name": "Test Creator"}
    defaults.update(overrides)
    return defaults


def create_student_payload(**overrides) -> dict:
    defaults = {"email": "student@example.com", "full_name": "Test Student"}
    defaults.update(overrides)
    return defaults


def create_course_payload(creator_id, **overrides) -> dict:
    defaults = {"creator_id": creator_id, "title": "Test Course"}
    defaults.update(overrides)
    return defaults


def create_lesson_payload(course_id, **overrides) -> dict:
    defaults = {"course_id": course_id, "title": "Lesson 1", "position": 1}
    defaults.update(overrides)
    return defaults


def create_price_plan_payload(course_id, **overrides) -> dict:
    defaults = {"course_id": course_id, "plan_type": "ONE_TIME", "amount_cents": 20000}
    defaults.update(overrides)
    return defaults


def create_coupon_payload(course_id, **overrides) -> dict:
    defaults = {
        "course_id": course_id,
        "code": "SAVE",
        "discount_type": "PERCENT",
        "discount_value": 10,
        "max_redemptions": 5,
        "starts_at": "2026-01-01T00:00:00Z",
        "expires_at": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_affiliate_payload(creator_id, **overrides) -> dict:
    defaults = {"creator_id": creator_id, "code": "AFF", "commission_pct": 10}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(student_id, course_id, price_plan_id, **overrides) -> dict:
    defaults = {
        "student_id": student_id,
        "course_id": course_id,
        "price_plan_id": price_plan_id,
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(amount_cents, expected_creator_version, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "expected_creator_version": expected_creator_version,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
