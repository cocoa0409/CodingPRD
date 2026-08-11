"""Payload factories — one per write endpoint, input fields only (PRD §3, §4)."""
import itertools

from .constants import (
    CLOCK_START_ISO,
    DEFAULT_PERIOD,
    TEST_DEFAULTS,
    WAVE_END_ISO,
    WAVE_START_ISO,
)

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter):04d}"


def clock_payload(to_iso8601: str = CLOCK_START_ISO) -> dict:
    return {"to_iso8601": to_iso8601}


def create_client_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Client"),
        "billing_email": f"{_uniq('billing')}@acme.test",
    }
    defaults.update(overrides)
    return defaults


def credit_adjustment_payload(amount_cents: int, reason: str = "seed") -> dict:
    return {"amount_cents": amount_cents, "reason": reason}


def create_box_plan_payload(client_id: str, **overrides) -> dict:
    defaults = {
        "client_id": client_id,
        "name": _uniq("Box"),
        "sku": _uniq("PL"),
        "price_per_box_cents": TEST_DEFAULTS["PRICE_PER_BOX_CENTS"],
        "shipping_weight_grams": TEST_DEFAULTS["SHIPPING_WEIGHT_GRAMS"],
    }
    defaults.update(overrides)
    return defaults


def create_kit_revision_payload(expected_box_plan_version: int) -> dict:
    return {"expected_box_plan_version": expected_box_plan_version}


def bom_lines_payload(lines: list) -> dict:
    """lines: [{"component_id": ..., "qty_per_box": ...}, ...]"""
    return {"lines": lines}


def bom_line(component_id: str, qty_per_box: int) -> dict:
    return {"component_id": component_id, "qty_per_box": qty_per_box}


def create_component_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("CMP"),
        "name": _uniq("Widget"),
        "unit_cost_cents": TEST_DEFAULTS["UNIT_COST_CENTS"],
        "reorder_point_units": 0,
    }
    defaults.update(overrides)
    return defaults


def receipt_payload(quantity: int, expected_component_version: int, note: str = None) -> dict:
    payload = {"quantity": quantity, "expected_component_version": expected_component_version}
    if note is not None:
        payload["note"] = note
    return payload


def subscriber_row(email: str, zone: int, full_name: str = None) -> dict:
    row = {"email": email, "zone": zone}
    if full_name is not None:
        row["full_name"] = full_name
    return row


def import_batch_payload(rows: list) -> dict:
    return {"rows": rows}


def churn_payload(reason: str = "OTHER") -> dict:
    return {"reason": reason}


def create_assembly_run_payload(plan_id: str, period: str = DEFAULT_PERIOD) -> dict:
    return {"plan_id": plan_id, "period": period}


def complete_kitting_payload(actual_kitted_count: int) -> dict:
    return {"actual_kitted_count": actual_kitted_count}


def rework_payload(note: str = "rework") -> dict:
    return {"note": note}


def create_shipping_wave_payload(**overrides) -> dict:
    defaults = {
        "carrier": "USPS",
        "service_level": "GROUND",
        "pickup_start": WAVE_START_ISO,
        "pickup_end": WAVE_END_ISO,
    }
    defaults.update(overrides)
    return defaults


def assign_shipments_payload(shipment_ids: list) -> dict:
    return {"shipment_ids": shipment_ids}


def scan_payload(scan_type: str = "DELIVERED") -> dict:
    return {"scan_type": scan_type}


def create_return_case_payload(shipment_id: str, reason: str = "DAMAGED",
                               requested_resolution: str = "REFUND") -> dict:
    return {
        "shipment_id": shipment_id,
        "reason": reason,
        "requested_resolution": requested_resolution,
    }


def reject_return_case_payload(note: str = None) -> dict:
    payload = {}
    if note is not None:
        payload["note"] = note
    return payload


def resolve_dispute_payload(adjustment_credit_cents: int) -> dict:
    return {"adjustment_credit_cents": adjustment_credit_cents}
