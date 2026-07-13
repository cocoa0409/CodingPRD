"""Payload factories — one per entity, input fields only.

Field names are exact to the PRD. Emails are generated unique per call so that a
single test can create several members without colliding on the unique-email rule.
"""
import itertools
import uuid

_email_counter = itertools.count(1)


def unique_email(prefix: str = "member") -> str:
    return f"{prefix}-{next(_email_counter)}-{uuid.uuid4().hex[:8]}@racquet-test.com"


# ---- MembershipPlan (PRD §3.2) ----
def create_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "Premier",
        "tier": "PREMIER",
        "monthly_fee_cents": 5000,
        "monthly_court_credits": 8,
        "peak_access": True,
        "guest_fee_cents": 1500,
        "freeze_limit": 2,
    }
    defaults.update(overrides)
    return defaults


def create_basic_plan_payload(**overrides) -> dict:
    defaults = {
        "name": "Basic",
        "tier": "BASIC",
        "monthly_fee_cents": 3000,
        "monthly_court_credits": 0,
        "peak_access": True,
        "guest_fee_cents": 2000,
        "freeze_limit": 1,
    }
    defaults.update(overrides)
    return defaults


# ---- Court (PRD §3.1) ----
def create_court_payload(**overrides) -> dict:
    defaults = {
        "name": "Indoor 1",
        "surface": "HARD",
        "location_type": "INDOOR",
        "hourly_rate_cents": 4000,
        "has_ball_machine": False,
        "ball_machine_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


# ---- Member (PRD §3.2) ----
def create_member_payload(**overrides) -> dict:
    defaults = {"full_name": "Test Member", "email": unique_email()}
    defaults.update(overrides)
    return defaults


# ---- Pro (PRD §3.2) ----
def create_pro_payload(**overrides) -> dict:
    defaults = {"full_name": "Coach Test", "hourly_rate_cents": 9000}
    defaults.update(overrides)
    return defaults


# ---- Subscription (PRD §3.2) ----
def create_subscription_payload(member_id: str, plan_id: str, **overrides) -> dict:
    defaults = {"member_id": member_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


# ---- Reservation (PRD §3.3) ----
def create_reservation_payload(court_id: str, member_id: str, start_time: str,
                               end_time: str, **overrides) -> dict:
    defaults = {
        "court_id": court_id,
        "member_id": member_id,
        "start_time": start_time,
        "end_time": end_time,
    }
    defaults.update(overrides)
    return defaults


# ---- Lesson (PRD §3.5) ----
def create_lesson_payload(pro_id: str, court_id: str, kind: str, start_time: str,
                          end_time: str, price_cents: int, **overrides) -> dict:
    defaults = {
        "pro_id": pro_id,
        "court_id": court_id,
        "kind": kind,
        "start_time": start_time,
        "end_time": end_time,
        "price_cents": price_cents,
    }
    defaults.update(overrides)
    return defaults


# ---- Enrollment (PRD §3.5) ----
def create_enrollment_payload(lesson_id: str, member_id: str, **overrides) -> dict:
    defaults = {"lesson_id": lesson_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults


# ---- Competition (PRD §3.6) ----
def create_competition_payload(name: str, fmt: str, draw_size=None,
                               entry_fee_cents: int = 0, **overrides) -> dict:
    defaults = {"name": name, "format": fmt, "entry_fee_cents": entry_fee_cents}
    if draw_size is not None:
        defaults["draw_size"] = draw_size
    defaults.update(overrides)
    return defaults


# ---- Participant (PRD §3.6) ----
def create_participant_payload(competition_id: str, member_id: str, **overrides) -> dict:
    defaults = {"competition_id": competition_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults


# ---- StringingJob (PRD §3.7) ----
def create_stringing_job_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "racquet_label": "Pro Staff",
        "string_type": "Poly",
        "tension": 55,
        "price_cents": 4500,
    }
    defaults.update(overrides)
    return defaults
