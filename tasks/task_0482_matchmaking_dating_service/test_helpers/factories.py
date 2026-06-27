"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PLAN_MONTHLY_FEE": 12000,
    "PLAN_TERM_MONTHS": 6,
    "PLAN_GUARANTEE": 8,
    "PLAN_COACHING_SESSIONS": 3,
    "PLAN_COACHING_VALUE": 5000,
    "PLAN_BG_ADDON": 2500,
    "BIRTH_DATE": "1990-01-01T00:00:00Z",
    "CITY": "NYC",
}


def create_plan_payload(**overrides) -> dict:
    """MembershipPlan creation payload. priority_match_enabled is optional (defaults false)."""
    defaults = {
        "tier": "PLUS",
        "monthly_fee_cents": DEFAULTS["PLAN_MONTHLY_FEE"],
        "term_months": DEFAULTS["PLAN_TERM_MONTHS"],
        "guaranteed_introductions": DEFAULTS["PLAN_GUARANTEE"],
        "priority_match_enabled": False,
        "included_coaching_sessions": DEFAULTS["PLAN_COACHING_SESSIONS"],
        "coaching_value_cents": DEFAULTS["PLAN_COACHING_VALUE"],
        "background_check_addon_cents": DEFAULTS["PLAN_BG_ADDON"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    """Member registration payload."""
    defaults = {
        "email": "member@example.com",
        "full_name": "Test Member",
        "birth_date": DEFAULTS["BIRTH_DATE"],
        "city": DEFAULTS["CITY"],
        "gender": "MALE",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(**overrides) -> dict:
    """Screening open payload."""
    defaults = {
        "questionnaire_score": 90,
        "identity_verified": True,
    }
    defaults.update(overrides)
    return defaults


def decide_screening_payload(**overrides) -> dict:
    """Screening decide payload. decision_note optional (defaults '')."""
    defaults = {
        "decision": "APPROVED",
    }
    defaults.update(overrides)
    return defaults


def create_preference_payload(**overrides) -> dict:
    """Preference upsert payload. dealbreaker_tags optional (defaults [])."""
    defaults = {
        "seeking_gender": "FEMALE",
        "min_age": 25,
        "max_age": 45,
        "max_distance_band": 0,
        "attribute_weights": {"education": 80, "lifestyle": 80, "values": 80},
    }
    defaults.update(overrides)
    return defaults


def activate_membership_payload(plan_id, **overrides) -> dict:
    """Membership activation payload."""
    defaults = {"plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def create_freeze_payload(start_at, end_at, **overrides) -> dict:
    """Freeze schedule payload."""
    defaults = {"start_at": start_at, "end_at": end_at}
    defaults.update(overrides)
    return defaults


def create_introduction_payload(member_a_id, member_b_id, expected_member_a_version, **overrides) -> dict:
    """Introduction suggestion payload. win_back_promo optional (defaults false)."""
    defaults = {
        "member_a_id": member_a_id,
        "member_b_id": member_b_id,
        "expected_member_a_version": expected_member_a_version,
    }
    defaults.update(overrides)
    return defaults


def respond_introduction_payload(response, expected_introduction_version, **overrides) -> dict:
    """Introduction respond payload."""
    defaults = {
        "response": response,
        "expected_introduction_version": expected_introduction_version,
    }
    defaults.update(overrides)
    return defaults


def create_feedback_payload(author_member_id, **overrides) -> dict:
    """Feedback payload. comments optional (defaults '')."""
    defaults = {
        "author_member_id": author_member_id,
        "rating": 5,
        "continue_interest": True,
    }
    defaults.update(overrides)
    return defaults


def create_date_event_payload(scheduled_by_member_id, start_at, end_at, **overrides) -> dict:
    """DateEvent schedule payload."""
    defaults = {
        "scheduled_by_member_id": scheduled_by_member_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_coaching_session_payload(start_at, end_at, **overrides) -> dict:
    """CoachingSession booking payload."""
    defaults = {
        "coach_user_id": "coach-1",
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def order_background_check_payload(**overrides) -> dict:
    """BackgroundCheck order payload."""
    defaults = {"provider_ref": "PRV-1"}
    defaults.update(overrides)
    return defaults


def complete_background_check_payload(result, **overrides) -> dict:
    """BackgroundCheck completion payload."""
    defaults = {"result": result}
    defaults.update(overrides)
    return defaults
