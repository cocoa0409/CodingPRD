"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def unique_sku() -> str:
    """Globally-unique SKU within a single test run."""
    return f"SKU-{next(_seq)}"


def unique_email() -> str:
    """Globally-unique customer email within a single test run."""
    return f"customer{next(_seq)}@example.com"


def create_store_payload(**overrides) -> dict:
    """Required: name, state_code. Optional: loyalty_point_value_cents."""
    defaults = {"name": "Test Store", "state_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    """Required: sku, name, category, unit_price_cents.
    Optional: is_prescription_diet, loyalty_points_per_unit."""
    defaults = {
        "sku": unique_sku(),
        "name": "Test Product",
        "category": "FOOD",
        "unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(store_id, product_id, **overrides) -> dict:
    """Required: store_id, product_id, lot_code, quantity_on_hand,
    received_at, expiry_date."""
    defaults = {
        "store_id": store_id,
        "product_id": product_id,
        "lot_code": "L1",
        "quantity_on_hand": 50,
        "received_at": "2026-01-02T00:00:00Z",
        "expiry_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def adjust_lot_payload(delta, expected_lot_version, **overrides) -> dict:
    """Required: delta, expected_lot_version."""
    defaults = {"delta": delta, "expected_lot_version": expected_lot_version}
    defaults.update(overrides)
    return defaults


def create_livestock_batch_payload(store_id, **overrides) -> dict:
    """Required: store_id, species, animal_class, head_count, unit_price_cents,
    intake_at, quarantine_days."""
    defaults = {
        "store_id": store_id,
        "species": "betta",
        "animal_class": "FISH",
        "head_count": 10,
        "unit_price_cents": 500,
        "intake_at": "2026-01-01T00:00:00Z",
        "quarantine_days": 5,
    }
    defaults.update(overrides)
    return defaults


def record_mortality_payload(deaths, **overrides) -> dict:
    """Required: deaths."""
    defaults = {"deaths": deaths}
    defaults.update(overrides)
    return defaults


def create_livestock_sale_payload(batch_id, customer_id, **overrides) -> dict:
    """Required: batch_id, customer_id."""
    defaults = {"batch_id": batch_id, "customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_customer_payload(home_store_id, **overrides) -> dict:
    """Required: email, full_name, home_store_id."""
    defaults = {
        "email": unique_email(),
        "full_name": "Test Customer",
        "home_store_id": home_store_id,
    }
    defaults.update(overrides)
    return defaults


def create_prescription_payload(customer_id, product_id, issued_by_appointment_id,
                                **overrides) -> dict:
    """Required: customer_id, product_id, issued_by_appointment_id,
    max_units_per_order, expires_at."""
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "issued_by_appointment_id": issued_by_appointment_id,
        "max_units_per_order": 2,
        "expires_at": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_clinic_appointment_payload(store_id, customer_id, **overrides) -> dict:
    """Required: store_id, customer_id, service_type, room, start_at,
    end_at, fee_cents."""
    defaults = {
        "store_id": store_id,
        "customer_id": customer_id,
        "service_type": "VET_EXAM",
        "room": "R1",
        "start_at": "2026-01-05T09:00:00Z",
        "end_at": "2026-01-05T10:00:00Z",
        "fee_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id, product_id, store_id, **overrides) -> dict:
    """Required: customer_id, product_id, store_id, quantity_per_cycle,
    cycle_days, next_ship_at. Optional: discount_pct."""
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "store_id": store_id,
        "quantity_per_cycle": 1,
        "cycle_days": 30,
        "next_ship_at": "2026-02-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def run_shipment_payload(expected_subscription_version, **overrides) -> dict:
    """Required: expected_subscription_version."""
    defaults = {"expected_subscription_version": expected_subscription_version}
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id, product_id, store_id, **overrides) -> dict:
    """Required: customer_id, product_id, store_id, quantity. Optional: deposit_pct."""
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "store_id": store_id,
        "quantity": 3,
    }
    defaults.update(overrides)
    return defaults


def create_product_sale_payload(store_id, product_id, customer_id, **overrides) -> dict:
    """Required: store_id, product_id, customer_id, quantity. Optional: redeem_points."""
    defaults = {
        "store_id": store_id,
        "product_id": product_id,
        "customer_id": customer_id,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_recall_payload(product_id, **overrides) -> dict:
    """Required: product_id, severity. Optional: lot_code, scope_state_code."""
    defaults = {"product_id": product_id, "severity": "MANDATORY"}
    defaults.update(overrides)
    return defaults


def create_adoption_event_payload(store_id, **overrides) -> dict:
    """Required: store_id, partner_name, event_date, capacity."""
    defaults = {
        "store_id": store_id,
        "partner_name": "Rescue",
        "event_date": "2026-01-15T00:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_adoption_placement_payload(event_id, batch_id, head, **overrides) -> dict:
    """Required: event_id, batch_id, head."""
    defaults = {"event_id": event_id, "batch_id": batch_id, "head": head}
    defaults.update(overrides)
    return defaults
