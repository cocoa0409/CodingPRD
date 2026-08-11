"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import DEFAULT_PRICING


def create_pricing_config_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_PRICING)
    defaults.update(overrides)
    return defaults


def create_delivery_zone_payload(**overrides) -> dict:
    defaults = {"code": "NW-1", "name": "Northwest 1"}
    defaults.update(overrides)
    return defaults


def create_customer_payload(zone_id: str, **overrides) -> dict:
    defaults = {
        "account_type": "OFFICE",
        "business_name": "Test Co",
        "billing_email": "billing@test.example",
        "service_address": "100 Main St",
        "delivery_zone_id": zone_id,
        "service_mode": "WILL_CALL",
        "par_level_bottles": 0,
        "pricing_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_route_payload(zone_id: str, service_date: str, **overrides) -> dict:
    defaults = {
        "zone_id": zone_id,
        "service_date": service_date,
        "driver_name": "Dave",
        "truck_capacity_bottles": 50,
    }
    defaults.update(overrides)
    return defaults


def create_stop_payload(customer_id: str, sequence_index: int, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "sequence_index": sequence_index}
    defaults.update(overrides)
    return defaults


def create_work_order_payload(customer_id: str, order_kind: str, requested_date: str,
                              quantity_bottles: int, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "order_kind": order_kind,
        "requested_date": requested_date,
        "quantity_bottles": quantity_bottles,
    }
    defaults.update(overrides)
    return defaults


def create_cooler_rental_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "cooler_model": "FREESTANDING",
        "monthly_rent_cents": 9000,
        "deposit_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "addon_kind": "COFFEE",
        "quantity": 1,
        "unit_price_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(customer_id: str, period_start: str, period_end: str,
                           due_date: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "billing_period_start": period_start,
        "billing_period_end": period_end,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(invoice_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {"invoice_id": invoice_id, "amount_cents": amount_cents, "method": "CARD"}
    defaults.update(overrides)
    return defaults


def create_deliver_payload(expected_route_version: int, actual_bottles_delivered: int,
                           actual_empties_collected: int, **overrides) -> dict:
    defaults = {
        "expected_route_version": expected_route_version,
        "actual_bottles_delivered": actual_bottles_delivered,
        "actual_empties_collected": actual_empties_collected,
    }
    defaults.update(overrides)
    return defaults


def create_skip_payload(skip_reason: str = "customer not available",
                        notified_before_cutoff: bool = True, **overrides) -> dict:
    defaults = {"skip_reason": skip_reason, "notified_before_cutoff": notified_before_cutoff}
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
