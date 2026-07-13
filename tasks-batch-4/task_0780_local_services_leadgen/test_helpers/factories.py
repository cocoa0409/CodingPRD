"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq() -> int:
    return next(_counter)


def create_customer_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {"email": f"customer{n}@x.com", "full_name": f"Customer {n}"}
    defaults.update(overrides)
    return defaults


def create_pro_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "email": f"pro{n}@x.com",
        "business_name": f"Pro {n}",
        "service_zip_codes": ["94016"],
        "covered_category_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_service_category_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "name": f"Category {n}",
        "base_lead_price_cents": 5000,
        "max_leads_per_request": 2,
        "demand_high_threshold": 5,
        "demand_multiplier_high": 1.5,
        "refund_window_hours": 24,
        "min_rating_to_receive_leads": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_plan_payload(**overrides) -> dict:
    n = _uniq()
    defaults = {
        "tier": f"TIER{n}",
        "monthly_fee_cents": 9900,
        "included_lead_credits": 8,
        "overage_price_cents": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(customer_id, category_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "category_id": category_id,
        "zip_code": "94016",
        "description": "job details",
        "budget_cents": 15000,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(lead_id, amount_cents=10000, message="quote", **overrides) -> dict:
    defaults = {"lead_id": lead_id, "amount_cents": amount_cents, "message": message}
    defaults.update(overrides)
    return defaults


def create_booking_payload(quote_id, availability_slot_id, scheduled_start,
                           scheduled_end, **overrides) -> dict:
    defaults = {
        "quote_id": quote_id,
        "availability_slot_id": availability_slot_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(booking_id, rating=5, **overrides) -> dict:
    defaults = {"booking_id": booking_id, "rating": rating}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(lead_id, reason="DUPLICATE", **overrides) -> dict:
    defaults = {"lead_id": lead_id, "reason": reason}
    defaults.update(overrides)
    return defaults


def create_slot_payload(pro_id, start_utc, end_utc, **overrides) -> dict:
    defaults = {"pro_id": pro_id, "start_utc": start_utc, "end_utc": end_utc}
    defaults.update(overrides)
    return defaults
