"""Payload factories — one per entity, input fields only (PRD §3)."""

from .constants import TEST_DEFAULTS


def create_customer_payload(**overrides) -> dict:
    """Customer registration body (PRD §3.1): email, full_name."""
    defaults = {
        "email": "customer@example.com",
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides) -> dict:
    """DeliveryZone body (PRD §3.1): zone_code, base_delivery_fee_cents,
    same_day_cutoff_hour_utc, window_capacity_per_slot, active?."""
    defaults = {
        "zone_code": "Z-TEST",
        "base_delivery_fee_cents": TEST_DEFAULTS["DELIVERY_FEE_CENTS"],
        "same_day_cutoff_hour_utc": TEST_DEFAULTS["SAME_DAY_CUTOFF_HOUR"],
        "window_capacity_per_slot": TEST_DEFAULTS["WINDOW_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_arrangement_payload(**overrides) -> dict:
    """Arrangement body (PRD §3.1): sku, display_name, base_price_cents,
    premium_tier?, substitution_policy?, substitution_cap_pct?, active?."""
    defaults = {
        "sku": "A-TEST",
        "display_name": "Test Arrangement",
        "base_price_cents": TEST_DEFAULTS["BASE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_holiday_window_payload(**overrides) -> dict:
    """HolidayWindow body (PRD §3.1): name, start_date, end_date,
    surge_multiplier, applies_to_standard?, surge_cutoff_hour_utc."""
    defaults = {
        "name": "Test Window",
        "start_date": "2026-02-14",
        "end_date": "2026-02-14",
        "surge_multiplier": 1.5,
        "applies_to_standard": False,
        "surge_cutoff_hour_utc": 20,
    }
    defaults.update(overrides)
    return defaults


def create_florist_payload(covered_zone_id, **overrides) -> dict:
    """Florist body (PRD §3.1): shop_name, covered_zone_id, daily_capacity,
    quality_rating?, wire_surcharge_cents?, accepting?."""
    defaults = {
        "shop_name": "Test Shop",
        "covered_zone_id": covered_zone_id,
        "daily_capacity": TEST_DEFAULTS["DAILY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, arrangement_id, zone_id, **overrides) -> dict:
    """Order draft body (PRD §3.2): customer_id, arrangement_id, zone_id,
    occasion?, card_message?, delivery_date, window_start_minute,
    window_end_minute, apply_wallet_credit?."""
    defaults = {
        "customer_id": customer_id,
        "arrangement_id": arrangement_id,
        "zone_id": zone_id,
        "delivery_date": "2026-02-20",
        "window_start_minute": TEST_DEFAULTS["WINDOW_START_MINUTE"],
        "window_end_minute": TEST_DEFAULTS["WINDOW_END_MINUTE"],
    }
    defaults.update(overrides)
    return defaults


def create_substitution_payload(order_id, florist_id, **overrides) -> dict:
    """Substitution body (PRD §3.5): order_id, florist_id, removed_stem,
    added_stem, price_delta_cents."""
    defaults = {
        "order_id": order_id,
        "florist_id": florist_id,
        "removed_stem": "rose",
        "added_stem": "lily",
        "price_delta_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(order_id, customer_id, reason, requested_remedy, **overrides) -> dict:
    """QualityClaim body (PRD §3.7): order_id, customer_id, reason,
    requested_remedy."""
    defaults = {
        "order_id": order_id,
        "customer_id": customer_id,
        "reason": reason,
        "requested_remedy": requested_remedy,
    }
    defaults.update(overrides)
    return defaults


def create_recurring_schedule_payload(customer_id, arrangement_id, zone_id, **overrides) -> dict:
    """RecurringSchedule body (PRD §3.8): customer_id, arrangement_id, zone_id,
    cadence, next_delivery_date, window_start_minute, window_end_minute,
    occurrences_remaining, recurring_discount_pct?."""
    defaults = {
        "customer_id": customer_id,
        "arrangement_id": arrangement_id,
        "zone_id": zone_id,
        "cadence": "MONTHLY",
        "next_delivery_date": "2026-03-10",
        "window_start_minute": TEST_DEFAULTS["WINDOW_START_MINUTE"],
        "window_end_minute": TEST_DEFAULTS["WINDOW_END_MINUTE"],
        "occurrences_remaining": 3,
    }
    defaults.update(overrides)
    return defaults
