"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "ZONE_CODE": "WEST",
    "PLAN_CODE": "PRO",
    "MEAL_CODE": "M1",
    "MEALS_PER_WEEK": 12,
    "PRICE_PER_MEAL_CENTS": 1099,
    "BASE_SHIPPING_FEE_CENTS": 1000,
    "COLD_PACK_FEE_CENTS": 500,
    "ORDER_LEAD_DAYS": 4,
    "CUTOFF_TIME_UTC": "18:00",
}


def create_shipping_zone_payload(**overrides) -> dict:
    payload = {
        "zone_code": DEFAULTS["ZONE_CODE"],
        "name": "West",
        "requires_cold_pack": True,
        "base_shipping_fee_cents": DEFAULTS["BASE_SHIPPING_FEE_CENTS"],
        "cold_pack_fee_cents": DEFAULTS["COLD_PACK_FEE_CENTS"],
        "order_lead_days": DEFAULTS["ORDER_LEAD_DAYS"],
        "cutoff_time_utc": DEFAULTS["CUTOFF_TIME_UTC"],
    }
    payload.update(overrides)
    return payload


def create_plan_payload(**overrides) -> dict:
    payload = {
        "plan_code": DEFAULTS["PLAN_CODE"],
        "name": "Pro",
        "meals_per_week": DEFAULTS["MEALS_PER_WEEK"],
        "price_per_meal_cents": DEFAULTS["PRICE_PER_MEAL_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_meal_payload(**overrides) -> dict:
    payload = {
        "meal_code": DEFAULTS["MEAL_CODE"],
        "name": "Grilled Chicken",
        "protein_g": 40,
        "carb_g": 30,
        "fat_g": 10,
        "calories": 400,
        "allergens": [],
        "dietary_tags": [],
    }
    payload.update(overrides)
    return payload


def create_production_run_payload(meal_id, **overrides) -> dict:
    payload = {
        "meal_id": meal_id,
        "delivery_date": "2026-03-16",
        "line_code": "L1",
        "window_start": "2026-03-14T06:00:00Z",
        "window_end": "2026-03-14T10:00:00Z",
        "par_total": 100,
    }
    payload.update(overrides)
    return payload


def create_customer_payload(shipping_zone_id, **overrides) -> dict:
    payload = {
        "email": "a@x.com",
        "full_name": "Cust A",
        "shipping_zone_id": shipping_zone_id,
    }
    payload.update(overrides)
    return payload


def create_subscription_payload(customer_id, plan_id, **overrides) -> dict:
    payload = {"customer_id": customer_id, "plan_id": plan_id}
    payload.update(overrides)
    return payload


def create_pause_window_payload(start_date, end_date, **overrides) -> dict:
    payload = {"start_date": start_date, "end_date": end_date}
    payload.update(overrides)
    return payload


def create_plan_change_payload(to_plan_id, effective_date, expected_subscription_version, **overrides) -> dict:
    payload = {
        "to_plan_id": to_plan_id,
        "effective_date": effective_date,
        "expected_subscription_version": expected_subscription_version,
    }
    payload.update(overrides)
    return payload


def create_box_payload(delivery_date="2026-03-16", **overrides) -> dict:
    payload = {"delivery_date": delivery_date}
    payload.update(overrides)
    return payload


def create_box_item_payload(meal_id, quantity=1, **overrides) -> dict:
    payload = {"meal_id": meal_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def swap_box_item_payload(new_meal_id, quantity=1, **overrides) -> dict:
    payload = {"new_meal_id": new_meal_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_credit_payload(amount_cents, reason="SWAP_CREDIT", **overrides) -> dict:
    payload = {"amount_cents": amount_cents, "reason": reason}
    payload.update(overrides)
    return payload


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def simulate_payment_payload(box_id, outcome) -> dict:
    return {"box_id": box_id, "outcome": outcome}
