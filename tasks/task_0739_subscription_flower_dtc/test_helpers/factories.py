"""Payload factories — one per entity, input fields only."""
from typing import Optional

from .constants import TEST_DEFAULTS


def create_plan_payload(**overrides) -> dict:
    """Plan input fields: name, cadence, base_fee_cents, default_style?, is_active?"""
    defaults = {
        "name": TEST_DEFAULTS["PLAN_NAME"],
        "cadence": TEST_DEFAULTS["CADENCE"],
        "base_fee_cents": TEST_DEFAULTS["PLAN_BASE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_carrier_route_payload(**overrides) -> dict:
    """CarrierRoute input fields: zone, service_date."""
    defaults = {
        "zone": "Z1",
        "service_date": "2026-03-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_substitution_rule_payload(**overrides) -> dict:
    """SubstitutionRule input fields: from_variety, to_variety, allowed?, max_substitution_pct?, quality_floor_grade?"""
    defaults = {
        "from_variety": "ROSE",
        "to_variety": "TULIP",
        "allowed": True,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(email: str = "test@x.com", full_name: str = "Test Customer", **overrides) -> dict:
    """Customer input fields: email, full_name, default_zip?"""
    defaults = {
        "email": email,
        "full_name": full_name,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, plan_id: str, **overrides) -> dict:
    """Subscription input fields: customer_id, plan_id, size, style?, vase_addon?, is_gift?, occasion?, gift_message?, start_date?"""
    defaults = {
        "customer_id": customer_id,
        "plan_id": plan_id,
        "size": TEST_DEFAULTS["SIZE"],
        "start_date": TEST_DEFAULTS["START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_stem_lot_payload(**overrides) -> dict:
    """StemLot input fields: variety, grade, quantity_total, unit_cost_cents, sourced_at, shelf_life_hours."""
    defaults = {
        "variety": "ROSE",
        "grade": "A",
        "quantity_total": 100,
        "unit_cost_cents": 40,
        "sourced_at": "2026-03-04T00:00:00Z",
        "shelf_life_hours": 240,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(lot_id: str, quantity_reserved: int, hold_start: str, hold_end: str, **overrides) -> dict:
    """StemAllocation input fields: lot_id, quantity_reserved, hold_start, hold_end."""
    defaults = {
        "lot_id": lot_id,
        "quantity_reserved": quantity_reserved,
        "hold_start": hold_start,
        "hold_end": hold_end,
    }
    defaults.update(overrides)
    return defaults


def confirm_sourced_payload(substitution_applied: bool = False, from_variety: Optional[str] = None, to_variety: Optional[str] = None) -> dict:
    """confirm-sourced input: substitution_applied?, from_variety?, to_variety?"""
    payload: dict = {"substitution_applied": substitution_applied}
    if substitution_applied:
        if from_variety is not None:
            payload["from_variety"] = from_variety
        if to_variety is not None:
            payload["to_variety"] = to_variety
    return payload


def ship_shipment_payload(route_id: str, delivery_window_start: str, delivery_window_end: str) -> dict:
    """ship input: route_id, delivery_window_start, delivery_window_end."""
    return {
        "route_id": route_id,
        "delivery_window_start": delivery_window_start,
        "delivery_window_end": delivery_window_end,
    }


def change_subscription_payload(expected_subscription_version: int, **overrides) -> dict:
    """change input: any subset of size/style/vase_addon/plan_id, and mandatory expected_subscription_version."""
    payload: dict = {"expected_subscription_version": expected_subscription_version}
    payload.update(overrides)
    return payload


def simulate_payment_payload(outcome: str) -> dict:
    """simulate-payment input: outcome (SUCCEEDED | FAILED)."""
    return {"outcome": outcome}


def refund_payload(amount_cents: int) -> dict:
    """refund input: amount_cents."""
    return {"amount_cents": amount_cents}


def redeem_offer_payload(subscription_id: str) -> dict:
    """redeem input: subscription_id."""
    return {"subscription_id": subscription_id}


def set_clock_payload(to_iso8601: str) -> dict:
    """clock input: to_iso8601."""
    return {"to_iso8601": to_iso8601}
