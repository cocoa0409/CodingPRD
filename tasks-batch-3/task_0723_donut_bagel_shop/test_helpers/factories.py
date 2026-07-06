"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _unique_suffix() -> int:
    return next(_counter)


# Canonical product definitions used across the design indices. Prices match the
# pre-computed literals in the difficulty/corner test recipes.
PRODUCT_SPECS = {
    "GLAZED": dict(sku="GLAZED", name="Glazed Donut", category="DONUT",
                   unit_price_cents=150, dozen_price_cents=1500, bulk_threshold=24,
                   bulk_unit_price_cents=110, unit_cost_cents=45),
    "EVERYTHING": dict(sku="EVERYTHING", name="Everything Bagel", category="BAGEL",
                       unit_price_cents=135, dozen_price_cents=1350, bulk_threshold=24,
                       bulk_unit_price_cents=100, unit_cost_cents=42),
    "SESAME": dict(sku="SESAME", name="Sesame Bagel", category="BAGEL",
                   unit_price_cents=120, dozen_price_cents=1200, bulk_threshold=24,
                   bulk_unit_price_cents=95, unit_cost_cents=40),
}


def create_product_payload(spec="GLAZED", **overrides) -> dict:
    """Build a product payload. `spec` selects a canonical product; overrides win."""
    base = dict(PRODUCT_SPECS.get(spec, PRODUCT_SPECS["GLAZED"]))
    base.update(overrides)
    return base


def create_production_day_payload(business_date=None, delivery_cutoff_utc=None, **overrides) -> dict:
    n = _unique_suffix()
    payload = {
        "business_date": business_date or f"2027-01-{(n % 28) + 1:02d}",
        "delivery_cutoff_utc": delivery_cutoff_utc or "2027-12-31T20:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_bake_batch_payload(product_id, par_qty=30, **overrides) -> dict:
    payload = {"product_id": product_id, "par_qty": par_qty}
    payload.update(overrides)
    return payload


def bake_payload(baked_qty=30, **overrides) -> dict:
    payload = {"baked_qty": baked_qty}
    payload.update(overrides)
    return payload


def line_item(product_id, qty, marked_down=False) -> dict:
    return {"product_id": product_id, "qty": qty, "marked_down": marked_down}


def wholesale_line(product_id, qty) -> dict:
    return {"product_id": product_id, "qty": qty}


def create_retail_order_payload(line_items, loyalty_account_id=None, redeem_reward=False) -> dict:
    payload = {"line_items": line_items}
    if loyalty_account_id is not None:
        payload["loyalty_account_id"] = loyalty_account_id
    if redeem_reward:
        payload["redeem_reward"] = True
    return payload


def create_loyalty_account_payload(phone=None, name="Reg Ular") -> dict:
    n = _unique_suffix()
    return {"phone": phone or f"555-{n:04d}", "name": name}


def create_wholesale_account_payload(name="Cafe Bleu", discount_pct=0.15,
                                     credit_limit_cents=100000, **overrides) -> dict:
    payload = {"name": name, "discount_pct": discount_pct,
               "credit_limit_cents": credit_limit_cents}
    payload.update(overrides)
    return payload


def create_standing_order_payload(wholesale_account_id, line_items, delivery_dow=0) -> dict:
    return {"wholesale_account_id": wholesale_account_id,
            "delivery_dow": delivery_dow, "line_items": line_items}


def create_wholesale_delivery_payload(standing_order_id, route_window_start,
                                      route_window_end) -> dict:
    return {"standing_order_id": standing_order_id,
            "route_window_start": route_window_start,
            "route_window_end": route_window_end}


def create_pre_order_payload(wholesale_account_id, pickup_production_day_id,
                             pickup_window_start, pickup_window_end, line_items) -> dict:
    return {
        "wholesale_account_id": wholesale_account_id,
        "pickup_production_day_id": pickup_production_day_id,
        "pickup_window_start": pickup_window_start,
        "pickup_window_end": pickup_window_end,
        "line_items": line_items,
    }
