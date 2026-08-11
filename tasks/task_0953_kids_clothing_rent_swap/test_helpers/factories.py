"""Payload factories — one per entity, input fields only.

Emails and SKUs must be unique, so the factories mint fresh values by default.
"""

import itertools

_seq = itertools.count(1)


def _next() -> int:
    return next(_seq)


def unique_email(prefix: str = "household") -> str:
    return f"{prefix}-{_next()}@kidswear.test"


def unique_sku(prefix: str = "SKU") -> str:
    return f"{prefix}-{_next()}"


def create_plan_payload(**overrides) -> dict:
    """POST /kidswear/plans — tier, slots_per_box, swaps_per_cycle and
    monthly_fee_cents are required; the four switches and discount_pct default."""
    payload = {
        "tier": "CORE",
        "slots_per_box": 1,
        "swaps_per_cycle": 1,
        "monthly_fee_cents": 5000,
    }
    payload.update(overrides)
    return payload


def create_member_payload(plan_id, **overrides) -> dict:
    """POST /kidswear/members — plan_id, email, display_name and
    child_size_code are required."""
    payload = {
        "plan_id": plan_id,
        "email": unique_email(),
        "display_name": "Test Household",
        "child_size_code": "5",
    }
    payload.update(overrides)
    return payload


def create_cycle_payload(member_id, start_at="2026-05-01T00:00:00Z", **overrides) -> dict:
    payload = {"member_id": member_id, "start_at": start_at}
    payload.update(overrides)
    return payload


def create_garment_style_payload(**overrides) -> dict:
    payload = {
        "sku": unique_sku(),
        "name": "Test Garment",
        "brand_tier": "STANDARD",
        "retail_price_cents": 3000,
        "size_code": "5",
        "season": "SS",
        "category": "TOP",
    }
    payload.update(overrides)
    return payload


def create_garment_unit_payload(style_id, acquired_at="2026-02-01T00:00:00Z", **overrides) -> dict:
    payload = {"style_id": style_id, "acquired_at": acquired_at}
    payload.update(overrides)
    return payload


def create_box_payload(cycle_id, **overrides) -> dict:
    payload = {"cycle_id": cycle_id}
    payload.update(overrides)
    return payload


def allocate_payload(unit_id=None, style_id=None, **overrides) -> dict:
    """POST /kidswear/boxes/{box_id}/allocate takes either an explicit unit_id
    or a style_id that hands the choice to the box-fill selector."""
    payload = {}
    if unit_id is not None:
        payload["unit_id"] = unit_id
    if style_id is not None:
        payload["style_id"] = style_id
    payload.update(overrides)
    return payload


def create_shipping_label_payload(member_id, direction="RETURN", **overrides) -> dict:
    payload = {"member_id": member_id, "direction": direction}
    payload.update(overrides)
    return payload


def create_shipment_payload(member_id, label_id, direction="RETURN", item_count=0, **overrides) -> dict:
    payload = {
        "member_id": member_id,
        "label_id": label_id,
        "direction": direction,
        "item_count": item_count,
    }
    payload.update(overrides)
    return payload


def create_swap_request_payload(return_box_item_ids, requested_style_ids,
                                expected_cycle_version, **overrides) -> dict:
    payload = {
        "return_box_item_ids": list(return_box_item_ids),
        "requested_style_ids": list(requested_style_ids),
        "expected_cycle_version": expected_cycle_version,
    }
    payload.update(overrides)
    return payload


def create_condition_assessment_payload(pipeline, unit_id=None, trade_in_item_id=None,
                                        **overrides) -> dict:
    payload = {"pipeline": pipeline}
    if unit_id is not None:
        payload["unit_id"] = unit_id
    if trade_in_item_id is not None:
        payload["trade_in_item_id"] = trade_in_item_id
    payload.update(overrides)
    return payload


def submit_grade_payload(grade, defect_codes=None, **overrides) -> dict:
    payload = {"grade": grade}
    if defect_codes is not None:
        payload["defect_codes"] = list(defect_codes)
    payload.update(overrides)
    return payload


def create_trade_in_submission_payload(member_id, declared_item_count=3, **overrides) -> dict:
    payload = {"member_id": member_id, "declared_item_count": declared_item_count}
    payload.update(overrides)
    return payload


def create_trade_in_item_payload(declared_brand_tier="STANDARD",
                                 declared_size_code="6", **overrides) -> dict:
    payload = {
        "declared_brand_tier": declared_brand_tier,
        "declared_size_code": declared_size_code,
    }
    payload.update(overrides)
    return payload


def create_buy_out_payload(quote_variant, expected_box_item_version, **overrides) -> dict:
    payload = {
        "quote_variant": quote_variant,
        "expected_box_item_version": expected_box_item_version,
    }
    payload.update(overrides)
    return payload


def create_capsule_payload(season="SS", name="Test Wave",
                           release_at="2026-06-01T00:00:00Z",
                           close_at="2026-08-01T00:00:00Z", **overrides) -> dict:
    payload = {
        "season": season,
        "name": name,
        "release_at": release_at,
        "close_at": close_at,
    }
    payload.update(overrides)
    return payload


def create_capsule_allocation_payload(member_id, units_allocated=1, **overrides) -> dict:
    payload = {"member_id": member_id, "units_allocated": units_allocated}
    payload.update(overrides)
    return payload


def create_pause_request_payload(start_at="2026-05-05T00:00:00Z",
                                 days_requested=10, **overrides) -> dict:
    payload = {"start_at": start_at, "days_requested": days_requested}
    payload.update(overrides)
    return payload


def create_charge_adjustment_payload(charge_type, amount_cents, **overrides) -> dict:
    payload = {"charge_type": charge_type, "amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_credit_adjustment_payload(amount_cents, reason="goodwill", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


def create_credit_application_payload(charge_entry_id, expected_member_version, **overrides) -> dict:
    payload = {
        "charge_entry_id": charge_entry_id,
        "expected_member_version": expected_member_version,
    }
    payload.update(overrides)
    return payload
