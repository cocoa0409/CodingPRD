"""Payload factories — one per entity, input fields only.

Field names mirror the PRD exactly. Each factory accepts **overrides so tests can
control any value while sensible defaults cover the rest.
"""
import itertools

_email_seq = itertools.count(1)
_vin_seq = itertools.count(1)


def _unique_email():
    return f"applicant{next(_email_seq)}@example.com"


def _unique_vin():
    return f"VIN-{next(_vin_seq):06d}"


def create_plan_payload(**overrides) -> dict:
    """SubscriptionPlan input fields (free_buffer_miles / included_swaps_per_term optional)."""
    defaults = {
        "tier": "PLUS",
        "monthly_fee_cents": 80000,
        "included_miles_per_cycle": 1000,
        "free_buffer_miles": 50,
        "overage_tier1_rate_cents": 25,
        "overage_tier2_rate_cents": 38,
        "included_swaps_per_term": 1,
        "min_term_months": 6,
        "deposit_base_cents": 80000,
    }
    defaults.update(overrides)
    return defaults


def create_premium_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "PREMIUM",
        "monthly_fee_cents": 95000,
        "included_miles_per_cycle": 1500,
        "free_buffer_miles": 50,
        "overage_tier1_rate_cents": 25,
        "overage_tier2_rate_cents": 38,
        "included_swaps_per_term": 1,
        "min_term_months": 6,
        "deposit_base_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_fleet_payload(**overrides) -> dict:
    defaults = {"name": "Test Fleet", "region_code": "CA"}
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(fleet_id, plan_id, **overrides) -> dict:
    defaults = {
        "fleet_id": fleet_id,
        "plan_id": plan_id,
        "vin": _unique_vin(),
        "model_label": "XC40",
        "odometer_miles": 0,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Applicant",
        "email": _unique_email(),
        "credit_score": 720,
        "monthly_income_cents": 480000,
        "history_flag": "CLEAN",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(applicant_id, plan_id, **overrides) -> dict:
    defaults = {"applicant_id": applicant_id, "plan_id": plan_id}
    defaults.update(overrides)
    return defaults


def create_courier_payload(fleet_id, **overrides) -> dict:
    defaults = {"name": "Test Courier", "fleet_id": fleet_id}
    defaults.update(overrides)
    return defaults


def create_delivery_slot_payload(courier_id, subscription_id, **overrides) -> dict:
    defaults = {
        "courier_id": courier_id,
        "subscription_id": subscription_id,
        "kind": "DELIVERY",
        "window_start_iso": "2026-04-01T09:00:00Z",
        "window_end_iso": "2026-04-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_return_inspection_payload(subscription_id, vehicle_id, **overrides) -> dict:
    defaults = {
        "subscription_id": subscription_id,
        "vehicle_id": vehicle_id,
        "reported_odometer_miles": 0,
    }
    defaults.update(overrides)
    return defaults


def create_damage_line_item_payload(**overrides) -> dict:
    defaults = {"severity": "MINOR", "amount_cents": 1000}
    defaults.update(overrides)
    return defaults
