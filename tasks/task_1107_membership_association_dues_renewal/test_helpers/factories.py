"""Payload factories — one per entity, input fields only."""


def create_membership_category_payload(**overrides) -> dict:
    defaults = {
        "code": "PROF",
        "name": "Professional",
        "is_voting": True,
        "is_directory_eligible": True,
        "allows_auto_renew": True,
        "lapse_grace_days": 30,
        "reinstatement_window_days": 90,
    }
    defaults.update(overrides)
    return defaults


def create_chapter_payload(**overrides) -> dict:
    defaults = {
        "code": "CH",
        "name": "Chapter",
        "is_affiliate": False,
    }
    defaults.update(overrides)
    return defaults


def create_renewal_cycle_policy_payload(**overrides) -> dict:
    defaults = {
        "code": "POLICY",
        "mode": "ANNIVERSARY",
        "calendar_anchor_month": 1,
        "calendar_anchor_day": 1,
        "proration_method": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_dues_schedule_payload(**overrides) -> dict:
    defaults = {
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": None,
        "annual_amount_cents": 120000,
        "chapter_share_bps": 2000,
        "increase_notice_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": "member@x.com",
        "full_name": "Member",
        "joined_at": "2026-05-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "payment_method_token": "tok_v",
        "simulated_outcome": "SUCCEEDED",
    }
    defaults.update(overrides)
    return defaults


def create_auto_renew_enroll_payload(**overrides) -> dict:
    defaults = {"payment_method_token": "tok_v"}
    defaults.update(overrides)
    return defaults


def create_revenue_attribution_payload(**overrides) -> dict:
    defaults = {
        "revenue_kind": "CONFERENCE_REGISTRATION",
        "amount_cents": 1000,
        "occurred_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
