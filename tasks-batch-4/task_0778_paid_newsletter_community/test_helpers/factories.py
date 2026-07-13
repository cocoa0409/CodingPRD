"""Payload factories — one per entity, input fields only."""


def create_publication_payload(**overrides) -> dict:
    payload = {"name": "Test Publication"}
    payload.update(overrides)
    return payload


def create_tier_payload(**overrides) -> dict:
    payload = {
        "name": "Test Tier",
        "tier_rank": 1,
        "monthly_price_cents": 1000,
        "trial_days": 0,
    }
    payload.update(overrides)
    return payload


def create_member_payload(**overrides) -> dict:
    payload = {"email": "member@example.com", "display_name": "Test Member"}
    payload.update(overrides)
    return payload


def create_subscription_payload(tier_id, **overrides) -> dict:
    payload = {"tier_id": tier_id}
    payload.update(overrides)
    return payload


def change_tier_payload(new_tier_id, expected_subscription_version, **overrides) -> dict:
    payload = {
        "new_tier_id": new_tier_id,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def create_post_payload(**overrides) -> dict:
    payload = {
        "title": "Test Post",
        "body": "Gated body content.",
        "content_type": "POST",
        "min_tier_rank": 0,
    }
    payload.update(overrides)
    return payload


def create_event_payload(**overrides) -> dict:
    payload = {
        "title": "Test Event",
        "starts_at": "2026-04-01T10:00:00Z",
        "ends_at": "2026-04-01T11:00:00Z",
        "registration_closes_at": "2026-03-31T00:00:00Z",
        "capacity": 1,
        "min_tier_rank": 0,
        "allow_waitlist": True,
    }
    payload.update(overrides)
    return payload


def create_comment_payload(**overrides) -> dict:
    payload = {"body": "Nice post."}
    payload.update(overrides)
    return payload


def create_payout_payload(amount_cents, expected_publication_version, **overrides) -> dict:
    payload = {
        "amount_cents": amount_cents,
        "expected_publication_version": expected_publication_version,
    }
    payload.update(overrides)
    return payload
