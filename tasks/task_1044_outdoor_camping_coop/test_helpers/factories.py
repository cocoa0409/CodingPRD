"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq():
    return next(_counter)


def member_payload(**overrides):
    n = _uniq()
    defaults = {
        "email": f"member{n}@coop.test",
        "full_name": f"Member {n}",
    }
    defaults.update(overrides)
    return defaults


def product_payload(**overrides):
    n = _uniq()
    defaults = {
        "sku": f"SKU-{n}",
        "name": f"Product {n}",
        "category": "TENT",
        "retail_price_cents": 100000,
        "tax_rate": 0.05,
        "replacement_value_cents": 150000,
    }
    defaults.update(overrides)
    return defaults


def rentable_product_payload(**overrides):
    defaults = product_payload()
    defaults.update({
        "is_rentable": True,
        "base_daily_rate_cents": 3000,
    })
    defaults.update(overrides)
    return defaults


def rental_unit_payload(product_id, **overrides):
    n = _uniq()
    defaults = {
        "product_id": product_id,
        "asset_tag": f"TAG-{n}",
    }
    defaults.update(overrides)
    return defaults


def reservation_payload(member_id, rental_unit_id, start_date, end_date, **overrides):
    defaults = {
        "member_id": member_id,
        "rental_unit_id": rental_unit_id,
        "start_date": start_date,
        "end_date": end_date,
    }
    defaults.update(overrides)
    return defaults


def guide_payload(**overrides):
    n = _uniq()
    defaults = {
        "full_name": f"Guide {n}",
        "certifications": [],
    }
    defaults.update(overrides)
    return defaults


def trip_payload(**overrides):
    n = _uniq()
    defaults = {
        "title": f"Trip {n}",
        "start_time": "2026-08-01T09:00:00Z",
        "end_time": "2026-08-01T17:00:00Z",
        "capacity": 5,
        "price_cents": 5000,
        "required_certification": "NONE",
    }
    defaults.update(overrides)
    return defaults


def trade_in_payload(member_id, product_id, condition_grade="A", **overrides):
    defaults = {
        "member_id": member_id,
        "product_id": product_id,
        "condition_grade": condition_grade,
    }
    defaults.update(overrides)
    return defaults


def repair_order_payload(member_id, product_id, purchase_date, **overrides):
    defaults = {
        "member_id": member_id,
        "product_id": product_id,
        "purchase_date": purchase_date,
    }
    defaults.update(overrides)
    return defaults


def pass_payload(member_id, **overrides):
    defaults = {
        "member_id": member_id,
        "pass_type": "SEASON",
        "valid_from": "2026-08-01T00:00:00Z",
        "valid_to": "2026-12-01T00:00:00Z",
        "price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def special_order_payload(member_id, product_id, quantity=1, **overrides):
    defaults = {
        "member_id": member_id,
        "product_id": product_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def purchase_payload(member_id, line_items, **overrides):
    defaults = {
        "member_id": member_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def declaration_payload(year=2026, declared_rate=0.08, **overrides):
    defaults = {
        "year": year,
        "declared_rate": declared_rate,
    }
    defaults.update(overrides)
    return defaults
