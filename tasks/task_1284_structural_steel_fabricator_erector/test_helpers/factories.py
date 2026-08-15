"""Payload factories — one per entity, input fields only.

Defaults assume the logical clock's initial reading of 2026-08-01T00:00:00Z
(PRD section 2.5): weld windows and weld dates default to that day and welder
qualifications default to an expiry after it.
"""
from .constants import TEST_DEFAULTS


def create_job_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Job",
        "contract_value_cents": TEST_DEFAULTS["CONTRACT_VALUE_CENTS"],
        "billing_basis": "WEIGHT",
    }
    defaults.update(overrides)
    # requires_aisc_hold is optional (defaults to false server-side); omit
    # unless the caller pins it.
    if defaults.get("requires_aisc_hold") is None:
        defaults.pop("requires_aisc_hold", None)
    return defaults


def create_shop_drawing_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id, "drawing_number": "D-1"}
    defaults.update(overrides)
    return defaults


def submit_drawing_payload(**overrides) -> dict:
    defaults: dict = {}
    defaults.update(overrides)
    return defaults


def decide_drawing_payload(decision="APPROVE", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def revise_drawing_payload(expected_drawing_version, **overrides) -> dict:
    defaults = {"expected_drawing_version": expected_drawing_version}
    defaults.update(overrides)
    return defaults


def create_mill_order_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "material_grade": "A992",
        "ordered_weight_lbs": TEST_DEFAULTS["ORDERED_WEIGHT_LBS"],
        "unit_price_per_cwt_cents": TEST_DEFAULTS["UNIT_PRICE_PER_CWT_CENTS"],
        "billing_mode": "NOMINAL",
    }
    defaults.update(overrides)
    return defaults


def receive_mill_order_payload(received_weight_lbs=None, **overrides) -> dict:
    defaults = {
        "received_weight_lbs": (
            TEST_DEFAULTS["ORDERED_WEIGHT_LBS"]
            if received_weight_lbs is None else received_weight_lbs
        )
    }
    defaults.update(overrides)
    return defaults


def create_erection_sequence_payload(job_id, **overrides) -> dict:
    defaults = {"job_id": job_id, "seq_number": 1}
    defaults.update(overrides)
    return defaults


def create_piece_payload(job_id, drawing_id, sequence_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "piece_mark": "P1",
        "weight_lbs": 800,
        "drawing_id": drawing_id,
        "sequence_id": sequence_id,
    }
    defaults.update(overrides)
    return defaults


def create_welder_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Welder One",
        "qual_process": "FCAW",
        "qual_expires_on": TEST_DEFAULTS["QUAL_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_weld_payload(piece_id, welder_id, **overrides) -> dict:
    defaults = {
        "piece_id": piece_id,
        "welder_id": welder_id,
        "process": "FCAW",
        "weld_date": TEST_DEFAULTS["WELD_DATE"],
        "window_start": "2026-08-01T09:00:00Z",
        "window_end": "2026-08-01T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(job_id, kind, piece_id=None, weld_id=None,
                              **overrides) -> dict:
    defaults = {"job_id": job_id, "kind": kind}
    if piece_id is not None:
        defaults["piece_id"] = piece_id
    if weld_id is not None:
        defaults["weld_id"] = weld_id
    defaults.update(overrides)
    return defaults


def submit_inspection_payload(outcome="PASSED", **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_shipping_load_payload(job_id, **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "load_number": "L-1",
        "laydown_slot": "Y-1",
        "delivery_date": TEST_DEFAULTS["DELIVERY_DATE"],
        "trailer_capacity_lbs": TEST_DEFAULTS["TRAILER_CAPACITY_LBS"],
    }
    defaults.update(overrides)
    return defaults


def add_load_line_payload(piece_id, **overrides) -> dict:
    defaults = {"piece_id": piece_id}
    defaults.update(overrides)
    return defaults


def create_field_fix_payload(job_id, piece_id, repair_lines=None,
                             **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "piece_id": piece_id,
        "description": "Field fix",
        "repair_lines": (
            [{"labor_hours": 1, "labor_rate_cents": 100, "material_cents": 0}]
            if repair_lines is None else repair_lines
        ),
    }
    defaults.update(overrides)
    return defaults


def respond_backcharge_payload(response="ACCEPT", **overrides) -> dict:
    defaults = {"response": response}
    defaults.update(overrides)
    return defaults


def settle_backcharge_payload(settled_amount_cents, **overrides) -> dict:
    defaults = {"settled_amount_cents": settled_amount_cents}
    defaults.update(overrides)
    return defaults


def create_progress_billing_payload(job_id, expected_job_version,
                                    **overrides) -> dict:
    defaults = {
        "job_id": job_id,
        "period_label": TEST_DEFAULTS["PERIOD_LABEL"],
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601, **overrides) -> dict:
    defaults = {"to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults
