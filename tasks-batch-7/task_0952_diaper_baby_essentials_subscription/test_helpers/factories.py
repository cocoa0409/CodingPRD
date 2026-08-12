"""Payload factories — one per entity, input fields only."""

import itertools

from .constants import TEST_DEFAULTS

_email_counter = itertools.count(1)
_code_counter = itertools.count(1)


def unique_email(prefix: str = "household") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


def unique_code(prefix: str = "CODE") -> str:
    return f"{prefix}-{next(_code_counter)}"


def create_account_payload(**overrides) -> dict:
    payload = {
        "email": unique_email(),
        "full_name": "Test Household",
    }
    payload.update(overrides)
    return payload


def create_child_payload(account_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "name": "Rin",
        "birth_date": TEST_DEFAULTS["CHILD_BIRTH_DATE"],
        "weight_grams": TEST_DEFAULTS["CHILD_WEIGHT_GRAMS"],
    }
    payload.update(overrides)
    return payload


def create_allergen_flag_payload(**overrides) -> dict:
    payload = {
        "allergen_tag": "FRAGRANCE",
        "severity": "SEVERE",
    }
    payload.update(overrides)
    return payload


def create_plan_payload(**overrides) -> dict:
    payload = {
        "code": unique_code("PLAN"),
        "name": TEST_DEFAULTS["PLAN_NAME"],
        "default_pack_count": TEST_DEFAULTS["PLAN_DEFAULT_PACK_COUNT"],
        "promo_discount_pct": 0,
        "allows_hypoallergenic": True,
    }
    payload.update(overrides)
    return payload


def create_sku_payload(**overrides) -> dict:
    payload = {
        "code": unique_code("SKU"),
        "name": "Stage 2 Standard 60",
        "stage": "S2",
        "line": "STANDARD",
        "pack_price_cents": TEST_DEFAULTS["SKU_PRICE_CENTS"],
        "pack_size_units": TEST_DEFAULTS["SKU_PACK_SIZE_UNITS"],
        "allergen_tags": [],
        "stock_packs": TEST_DEFAULTS["SKU_STOCK_PACKS"],
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(account_id: str, plan_id: str, child_id: str, **overrides) -> dict:
    payload = {
        "account_id": account_id,
        "plan_id": plan_id,
        "child_id": child_id,
        "consumption_rate_per_day": TEST_DEFAULTS["CONSUMPTION_RATE_PER_DAY"],
        "pack_count": TEST_DEFAULTS["PACK_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_pause_payload(start_date: str, end_date: str, **overrides) -> dict:
    payload = {"start_date": start_date, "end_date": end_date}
    payload.update(overrides)
    return payload


def create_registry_payload(owner_account_id: str, child_id: str, **overrides) -> dict:
    payload = {
        "owner_account_id": owner_account_id,
        "child_id": child_id,
        "title": "Test Registry",
    }
    payload.update(overrides)
    return payload


def create_registry_item_payload(sku_id: str, requested_quantity: int = 2, **overrides) -> dict:
    payload = {"sku_id": sku_id, "requested_quantity": requested_quantity}
    payload.update(overrides)
    return payload


def create_gift_order_payload(
    registry_item_id: str,
    purchaser_account_id: str,
    quantity: int,
    expected_registry_item_version: int,
    **overrides,
) -> dict:
    payload = {
        "registry_item_id": registry_item_id,
        "purchaser_account_id": purchaser_account_id,
        "quantity": quantity,
        "expected_registry_item_version": expected_registry_item_version,
    }
    payload.update(overrides)
    return payload


def create_credit_payload(account_id: str, issued_cents: int, **overrides) -> dict:
    payload = {"account_id": account_id, "issued_cents": issued_cents}
    payload.update(overrides)
    return payload


def create_referral_payload(referrer_account_id: str, referee_account_id: str, code: str, **overrides) -> dict:
    payload = {
        "referrer_account_id": referrer_account_id,
        "referee_account_id": referee_account_id,
        "code": code,
    }
    payload.update(overrides)
    return payload


def create_resize_payload(target_stage: str, expected_subscription_version: int, **overrides) -> dict:
    payload = {
        "target_stage": target_stage,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload
