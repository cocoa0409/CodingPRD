"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    DEFAULT_ADD_DROP_DEADLINE,
    DEFAULT_CARD_EXPIRY,
    DEFAULT_PLAN_DINING_CENTS,
    DEFAULT_PLAN_PRICE_CENTS,
    DEFAULT_PLAN_SWIPES,
    DEFAULT_TERM_END,
    DEFAULT_TERM_START,
    DEFAULT_TOTAL_WEEKS,
)

_uid_counter = [0]


def _next(prefix: str) -> str:
    _uid_counter[0] += 1
    return f"{prefix}-{_uid_counter[0]:05d}"


def create_card_holder_payload(**overrides) -> dict:
    n = _next("U")
    defaults = {
        "university_id": n,
        "full_name": f"Holder {n}",
        "email": f"{n.lower()}@x.edu",
        "holder_type": "STUDENT_COMMUTER",
        "housing_status": "COMMUTER",
    }
    defaults.update(overrides)
    return defaults


def create_card_payload(**overrides) -> dict:
    defaults = {"expires_at": DEFAULT_CARD_EXPIRY}
    defaults.update(overrides)
    return defaults


def create_photo_payload(**overrides) -> dict:
    defaults = {"image_ref": f"img://{_next('photo')}"}
    defaults.update(overrides)
    return defaults


def create_term_payload(**overrides) -> dict:
    defaults = {
        "term_code": _next("T"),
        "name": "Test Term",
        "start_date": DEFAULT_TERM_START,
        "end_date": DEFAULT_TERM_END,
        "add_drop_deadline": DEFAULT_ADD_DROP_DEADLINE,
        "total_weeks": DEFAULT_TOTAL_WEEKS,
        "proration_mode": "WEEKLY",
    }
    defaults.update(overrides)
    return defaults


def create_meal_plan_payload(**overrides) -> dict:
    defaults = {
        "plan_code": _next("P"),
        "name": "Test Plan",
        "weekly_swipe_allowance": DEFAULT_PLAN_SWIPES,
        "dining_dollar_allocation_cents": DEFAULT_PLAN_DINING_CENTS,
        "price_cents": DEFAULT_PLAN_PRICE_CENTS,
        "eligible_holder_types": ["STUDENT_COMMUTER", "STUDENT_RESIDENT"],
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(plan_id, term_id, **overrides) -> dict:
    defaults = {"plan_id": plan_id, "term_id": term_id}
    defaults.update(overrides)
    return defaults


def create_change_request_payload(new_plan_id, expected_enrollment_version,
                                  **overrides) -> dict:
    defaults = {
        "new_plan_id": new_plan_id,
        "expected_enrollment_version": expected_enrollment_version,
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(**overrides) -> dict:
    defaults = {"account_type": "CAMPUS_CASH"}
    defaults.update(overrides)
    return defaults


def create_funding_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "idempotency_key": _next("fund")}
    defaults.update(overrides)
    return defaults


def create_adjustment_payload(amount_cents, direction, expected_account_version,
                              **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "direction": direction,
        "reason": "manual correction",
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(card_id, tender_type, amount_cents, **overrides) -> dict:
    defaults = {
        "card_id": card_id,
        "tender_type": tender_type,
        "amount_cents": amount_cents,
        "idempotency_key": _next("tx"),
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(reason_code="AMOUNT_MISMATCH", **overrides) -> dict:
    defaults = {"reason_code": reason_code}
    defaults.update(overrides)
    return defaults


def create_door_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": _next("Z"),
        "building": "Test Hall",
        "security_level": "STANDARD",
        # Tuesday 08:00-18:00 (half-open minute range)
        "access_windows": [{"day_of_week": "TUE", "start_minute": 480,
                            "end_minute": 1080}],
    }
    defaults.update(overrides)
    return defaults


def create_access_grant_payload(zone_id, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "clearance": "STANDARD",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_until": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_merchant_payload(**overrides) -> dict:
    n = _next("M")
    defaults = {
        "merchant_code": n,
        "legal_name": f"Merchant {n}",
        "category": "COFFEE",
        "commission_bps": 275,
        "commission_mode": "PER_TRANSACTION",
        "contact_email": f"{n.lower()}@shop.example",
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(term_id, **overrides) -> dict:
    defaults = {
        "term_id": term_id,
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-30T23:59:59Z",
    }
    defaults.update(overrides)
    return defaults


def create_replacement_payload(reason, expected_card_version, **overrides) -> dict:
    defaults = {"reason": reason, "expected_card_version": expected_card_version}
    defaults.update(overrides)
    return defaults
