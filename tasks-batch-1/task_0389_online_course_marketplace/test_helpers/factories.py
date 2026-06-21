"""Payload factories — one per endpoint body, input fields only (PRD §3).

Each factory emits only the client-supplied input fields for the relevant POST.
Server-managed fields (id, status, computed money/score, timestamps, version) are
never set by the client.
"""
import itertools

# Monotonic email suffix so factory-built accounts never collide on the unique-email
# constraint within a single test (PRD §3.1).
_email_seq = itertools.count(1)


def _unique_email(prefix: str) -> str:
    return f"{prefix}{next(_email_seq)}@example.com"


# ─── Instructor (PRD §3.1) ─────────────────────────────────────────
def create_instructor_payload(**overrides) -> dict:
    payload = {
        "display_name": "Test Instructor",
        "email": _unique_email("instructor"),
        "revenue_share_pct": 0.50,
    }
    payload.update(overrides)
    return payload


# ─── Learner (PRD §3.1) ────────────────────────────────────────────
def create_learner_payload(**overrides) -> dict:
    payload = {
        "full_name": "Test Learner",
        "email": _unique_email("learner"),
    }
    payload.update(overrides)
    return payload


# ─── Course (PRD §3.2) ─────────────────────────────────────────────
def create_course_payload(instructor_id, **overrides) -> dict:
    payload = {
        "instructor_id": instructor_id,
        "title": "Test Course",
        "list_price_cents": 1000,
    }
    payload.update(overrides)
    return payload


# ─── Lesson (PRD §3.2) ─────────────────────────────────────────────
def create_lesson_payload(course_id, order_index=1, **overrides) -> dict:
    payload = {
        "course_id": course_id,
        "title": "Test Lesson",
        "order_index": order_index,
    }
    payload.update(overrides)
    return payload


# ─── Coupon (PRD §3.5) ─────────────────────────────────────────────
def create_coupon_payload(instructor_id, course_id, code="SAVE", **overrides) -> dict:
    payload = {
        "instructor_id": instructor_id,
        "course_id": course_id,
        "code": code,
        "discount_type": "PERCENT",
        "discount_value": 10,
        "max_redemptions": 5,
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_until": "2027-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


# ─── Bundle (PRD §3.6) ─────────────────────────────────────────────
def create_bundle_payload(instructor_id, course_ids, bundle_price_cents,
                          **overrides) -> dict:
    payload = {
        "instructor_id": instructor_id,
        "title": "Test Bundle",
        "course_ids": course_ids,
        "bundle_price_cents": bundle_price_cents,
        "promo_starts_at": "2026-01-01T00:00:00Z",
        "promo_ends_at": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def enroll_bundle_payload(learner_id, expected_bundle_version, **overrides) -> dict:
    payload = {
        "learner_id": learner_id,
        "expected_bundle_version": expected_bundle_version,
    }
    payload.update(overrides)
    return payload


# ─── Enrollment (PRD §3.4) ─────────────────────────────────────────
def enroll_course_payload(learner_id, **overrides) -> dict:
    payload = {"learner_id": learner_id}
    payload.update(overrides)
    return payload


# ─── LessonCompletion (PRD §3.7) ───────────────────────────────────
def create_lesson_completion_payload(enrollment_id, lesson_id, **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "lesson_id": lesson_id,
    }
    payload.update(overrides)
    return payload


# ─── Review (PRD §3.10) ────────────────────────────────────────────
def create_review_payload(enrollment_id, stars=5, body="Great course", **overrides) -> dict:
    payload = {
        "enrollment_id": enrollment_id,
        "stars": stars,
        "body": body,
    }
    payload.update(overrides)
    return payload


# ─── Payout (PRD §3.11) ────────────────────────────────────────────
def create_payout_payload(instructor_id, requested_amount_cents, **overrides) -> dict:
    payload = {
        "instructor_id": instructor_id,
        "requested_amount_cents": requested_amount_cents,
    }
    payload.update(overrides)
    return payload


def approve_payout_payload(expected_instructor_version, **overrides) -> dict:
    payload = {"expected_instructor_version": expected_instructor_version}
    payload.update(overrides)
    return payload


# ─── Clock (PRD §2.8) ──────────────────────────────────────────────
def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
