"""Payload factories — one per entity, input fields only."""

import uuid

from .constants import TEST_DEFAULTS


def _suffix() -> str:
    return uuid.uuid4().hex[:8].upper()


def clock_payload(to_iso8601: str = TEST_DEFAULTS["CLOCK"], **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": f"Test Bakery {_suffix()}",
        "allergen_program": "STANDARD",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
        "min_drop_cents": TEST_DEFAULTS["MIN_DROP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def credit_limit_adjustment_payload(new_credit_limit_cents: int, **overrides) -> dict:
    defaults = {
        "new_credit_limit_cents": new_credit_limit_cents,
        "reason": "terms renegotiated after a late payment",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{_suffix()}",
        "category": "FLOUR",
        "allergen_class": "NONE",
        "bulk_capable": False,
        "shelf_life_days": 180,
        "index_code": "NONE",
        "list_price_cents_per_lb": 42,
        "min_rotation_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": f"Z-{_suffix()[:6]}",
        "allergen_class": "NONE",
    }
    defaults.update(overrides)
    return defaults


def zone_lockout_payload(lockout_start_at=None, lockout_end_at=None, **overrides) -> dict:
    defaults = {}
    if lockout_start_at is not None:
        defaults["lockout_start_at"] = lockout_start_at
    if lockout_end_at is not None:
        defaults["lockout_end_at"] = lockout_end_at
    defaults.update(overrides)
    return defaults


def create_index_quote_payload(**overrides) -> dict:
    defaults = {
        "index_code": "HRW_WHEAT",
        "effective_on": "2026-08-01T00:00:00Z",
        "price_cents_per_lb": 38,
    }
    defaults.update(overrides)
    return defaults


def create_forward_contract_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "term_start_on": TEST_DEFAULTS["TERM_START_ON"],
        "term_end_on": TEST_DEFAULTS["TERM_END_ON"],
        "pricing_mode": "ORDER_DATE_INDEX",
    }
    defaults.update(overrides)
    return defaults


def create_contract_line_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "volume_committed_lb": 20000,
        "basis_cents_per_lb": 6,
    }
    defaults.update(overrides)
    return defaults


def counter_contract_payload(counter_basis_cents_per_lb: int, **overrides) -> dict:
    defaults = {"counter_basis_cents_per_lb": counter_basis_cents_per_lb}
    defaults.update(overrides)
    return defaults


def terminate_contract_payload(**overrides) -> dict:
    defaults = {"reason": "bakery consolidated its supply agreements"}
    defaults.update(overrides)
    return defaults


def create_lot_payload(product_id: str, zone_id: str, **overrides) -> dict:
    defaults = {
        "lot_code": f"LOT-{_suffix()}",
        "product_id": product_id,
        "zone_id": zone_id,
        "manufactured_on": "2026-07-15T00:00:00Z",
        "quantity_received_lb": 50000,
    }
    defaults.update(overrides)
    return defaults


def quarantine_lot_payload(**overrides) -> dict:
    defaults = {"quarantine_reason": "incoming pallet damaged in transit"}
    defaults.update(overrides)
    return defaults


def dispose_lot_payload(**overrides) -> dict:
    defaults = {"disposal_note": "written off after mill contamination notice"}
    defaults.update(overrides)
    return defaults


def create_silo_payload(customer_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "silo_code": f"SIL-{_suffix()[:6]}",
        "customer_id": customer_id,
        "product_id": product_id,
        "capacity_lb": 60000,
        "min_fill_lb": 5000,
    }
    defaults.update(overrides)
    return defaults


def residual_reading_payload(measured_residual_lb, **overrides) -> dict:
    defaults = {"measured_residual_lb": measured_residual_lb}
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "delivery_mode": "BAGGED",
        "requested_delivery_on": TEST_DEFAULTS["REQUESTED_DELIVERY_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id: str, quantity_lb, **overrides) -> dict:
    defaults = {"product_id": product_id, "quantity_lb": quantity_lb}
    defaults.update(overrides)
    return defaults


def cancel_order_payload(**overrides) -> dict:
    defaults = {"cancellation_reason": "bakery pulled the promotion"}
    defaults.update(overrides)
    return defaults


def create_substitution_request_payload(
    order_line_id: str, proposed_product_id: str, expected_order_version: int, **overrides
) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "proposed_product_id": proposed_product_id,
        "rationale": "customer reformulated the crust and needs a replacement SKU",
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def request_revision_payload(**overrides) -> dict:
    defaults = {"revision_note": "propose a SKU with a matching allergen class"}
    defaults.update(overrides)
    return defaults


def resubmit_substitution_payload(proposed_product_id: str, **overrides) -> dict:
    defaults = {
        "proposed_product_id": proposed_product_id,
        "rationale": "revised proposal after quality feedback on the formulation",
    }
    defaults.update(overrides)
    return defaults


def reject_substitution_payload(**overrides) -> dict:
    defaults = {"decision_note": "the proposed SKU is not formulation-equivalent"}
    defaults.update(overrides)
    return defaults


def create_route_payload(**overrides) -> dict:
    defaults = {
        "route_code": f"R-{_suffix()[:6]}",
        "service_on": TEST_DEFAULTS["SERVICE_DATE"],
        "vehicle_capacity_lb": TEST_DEFAULTS["VEHICLE_CAPACITY_LB"],
        "service_buffer_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_route_stop_payload(
    order_id: str, expected_route_version: int, **overrides
) -> dict:
    defaults = {
        "order_id": order_id,
        "window_start_at": TEST_DEFAULTS["WINDOW_START_AT"],
        "window_end_at": TEST_DEFAULTS["WINDOW_END_AT"],
        "expected_route_version": expected_route_version,
    }
    defaults.update(overrides)
    return defaults


def abort_route_payload(**overrides) -> dict:
    defaults = {"abort_reason": "trailer failed its pre-trip inspection"}
    defaults.update(overrides)
    return defaults


def short_drop_payload(delivered_lb_total, **overrides) -> dict:
    defaults = {
        "delivered_lb_total": delivered_lb_total,
        "short_reason": "trailer compartment jammed; the balance returned to the warehouse",
    }
    defaults.update(overrides)
    return defaults


def create_tech_engagement_payload(customer_id: str, product_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "product_id": product_id}
    defaults.update(overrides)
    return defaults


def log_hours_payload(hours, **overrides) -> dict:
    defaults = {"hours": hours, "work_note": "dough rheology bench trial"}
    defaults.update(overrides)
    return defaults


def attach_engagement_payload(order_id: str, **overrides) -> dict:
    defaults = {"order_id": order_id}
    defaults.update(overrides)
    return defaults


def waive_engagement_payload(**overrides) -> dict:
    defaults = {"waiver_reason": "goodwill gesture for a long-standing account"}
    defaults.update(overrides)
    return defaults
