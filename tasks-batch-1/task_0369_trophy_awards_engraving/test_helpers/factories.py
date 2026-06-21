"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": _uniq("cust") + "@x.com",
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_catalog_product_payload(**overrides) -> dict:
    component_id = overrides.pop("_component_id", None)
    bom = overrides.pop("bom", None)
    if bom is None:
        bom = [{"component_id": component_id, "qty_per_unit": 1}] if component_id else []
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "product_type": "PLAQUE",
        "base_price_cents": 4000,
        "engraving_price_per_char_cents": 0,
        "logo_setup_fee_cents": 0,
        "standard_lead_days": 5,
        "bom": bom,
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("COMP"),
        "name": "Test Component",
        "on_hand_qty": 100,
    }
    defaults.update(overrides)
    return defaults


def create_rush_policy_payload(**overrides) -> dict:
    defaults = {
        "name": "std",
        "expedited_surcharge_pct": 0.25,
        "rush_surcharge_pct": 0.50,
        "rush_min_business_days": 1,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_promo_code_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("PROMO").upper(),
        "kind": "PERCENT",
        "percent_off": 0.10,
        "min_subtotal_cents": 0,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "service_level": "STANDARD",
        "due_date": "2026-07-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(catalog_product_id, **overrides) -> dict:
    defaults = {
        "catalog_product_id": catalog_product_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_proof_payload(**overrides) -> dict:
    defaults = {
        "proof_kind": "TEXT",
        "content_ref": "X",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, kind, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "kind": kind,
    }
    defaults.update(overrides)
    return defaults


def create_fulfillment_payload(method, **overrides) -> dict:
    defaults = {
        "method": method,
    }
    defaults.update(overrides)
    return defaults
