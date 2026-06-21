"""Payload factories — one per entity, input fields only.

Email factories use a counter so repeated calls within a single test produce
unique emails (the member email-uniqueness rule is case-insensitive).
"""
import itertools

_email_counter = itertools.count(1)


def unique_email(prefix="member") -> str:
    """Return a unique email for member registration."""
    return f"{prefix}-{next(_email_counter)}@example.com"


# ─── Season ──────────────────────────────────────────────────────────────────
def create_season_payload(**overrides) -> dict:
    defaults = {
        "name": "Summer 2026",
        "week_count": 12,
        "first_delivery_date": "2026-07-01T00:00:00Z",
        "signup_close_date": "2026-12-30T00:00:00Z",
        "total_share_capacity": 100,
    }
    defaults.update(overrides)
    return defaults


# ─── PickupSite ──────────────────────────────────────────────────────────────
def create_pickup_site_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "name": "Downtown",
        "kind": "PICKUP",
        "weekly_capacity": 100,
    }
    defaults.update(overrides)
    return defaults


# ─── ShareType ───────────────────────────────────────────────────────────────
def create_share_type_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "size": "MEDIUM",
        "base_price_cents": 50000,
        "items_per_box": 8,
    }
    defaults.update(overrides)
    return defaults


# ─── AddOn ───────────────────────────────────────────────────────────────────
def create_add_on_payload(season_id, **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "kind": "EGGS",
        "weekly_price_cents": 800,
        "weekly_supply_cap": 50,
    }
    defaults.update(overrides)
    return defaults


# ─── Member ──────────────────────────────────────────────────────────────────
def create_member_payload(**overrides) -> dict:
    # sliding_scale_tier is optional (defaults to BASELINE server-side); omit it
    # unless an override supplies one, so the default-value behavior stays testable.
    defaults = {
        "email": unique_email(),
        "full_name": "Test Member",
    }
    defaults.update(overrides)
    return defaults


# ─── Subscription ────────────────────────────────────────────────────────────
def create_subscription_payload(season_id, member_id, share_type_id, current_site_id,
                                **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "member_id": member_id,
        "share_type_id": share_type_id,
        "current_site_id": current_site_id,
    }
    defaults.update(overrides)
    return defaults


# ─── SubscriptionAddOn ───────────────────────────────────────────────────────
def create_subscription_add_on_payload(subscription_id, add_on_id, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "add_on_id": add_on_id,
    }
    defaults.update(overrides)
    return defaults


# ─── VacationHold ────────────────────────────────────────────────────────────
def create_vacation_hold_payload(subscription_id, held_box_id, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "held_box_id": held_box_id,
    }
    defaults.update(overrides)
    return defaults


# ─── WaitlistEntry ───────────────────────────────────────────────────────────
def create_waitlist_entry_payload(season_id, member_id, share_type_id, requested_site_id,
                                  **overrides) -> dict:
    defaults = {
        "season_id": season_id,
        "member_id": member_id,
        "share_type_id": share_type_id,
        "requested_site_id": requested_site_id,
    }
    defaults.update(overrides)
    return defaults


# ─── WorkShareShift ──────────────────────────────────────────────────────────
def create_work_share_shift_payload(scheduled_date="2026-08-01T09:00:00Z", hours=4,
                                    **overrides) -> dict:
    defaults = {
        "scheduled_date": scheduled_date,
        "hours": hours,
    }
    defaults.update(overrides)
    return defaults


# ─── Payment ─────────────────────────────────────────────────────────────────
def create_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


# ─── Waitlist promotion (season action) ──────────────────────────────────────
def promote_waitlist_payload(share_type_id, requested_site_id, expected_season_version,
                             **overrides) -> dict:
    defaults = {
        "share_type_id": share_type_id,
        "requested_site_id": requested_site_id,
        "expected_season_version": expected_season_version,
    }
    defaults.update(overrides)
    return defaults
