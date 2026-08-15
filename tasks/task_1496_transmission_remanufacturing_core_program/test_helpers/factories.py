"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import DEFAULT_CLOCK_UTC, MIN_MODEL


def create_transmission_model_payload(**overrides) -> dict:
    defaults = dict(MIN_MODEL)
    defaults.update(overrides)
    return defaults


def create_hard_part_payload(part_number="P-100", part_family="PUMP",
                             unit_cost_cents=1000, qty_on_hand=5,
                             **overrides) -> dict:
    defaults = {
        "part_number": part_number,
        "part_family": part_family,
        "unit_cost_cents": unit_cost_cents,
        "qty_on_hand": qty_on_hand,
    }
    defaults.update(overrides)
    return defaults


def create_interchange_mapping_payload(hard_part_id, transmission_model_id,
                                       tier="DIRECT", **overrides) -> dict:
    defaults = {
        "hard_part_id": hard_part_id,
        "transmission_model_id": transmission_model_id,
        "tier": tier,
    }
    defaults.update(overrides)
    return defaults


def create_reman_order_payload(transmission_model_id, buyer_ref="BUYER-1",
                               **overrides) -> dict:
    defaults = {
        "transmission_model_id": transmission_model_id,
        "buyer_ref": buyer_ref,
    }
    defaults.update(overrides)
    return defaults


def create_calibration_payload(solenoid_trims=None, tcm_flash_version="TF-2026.08",
                               **overrides) -> dict:
    defaults = {
        "solenoid_trims": solenoid_trims if solenoid_trims is not None
        else [0.1, -0.2, 0.3, 0.0],
        "tcm_flash_version": tcm_flash_version,
    }
    defaults.update(overrides)
    return defaults


def create_resync_payload(expected_reman_order_version) -> dict:
    return {"expected_reman_order_version": expected_reman_order_version}


def create_dyno_booking_payload(reman_order_id, dyno_cell_code="DYNO-1",
                                start_utc="2026-08-01T00:00:00Z",
                                end_utc="2026-08-02T00:00:00Z",
                                **overrides) -> dict:
    defaults = {
        "reman_order_id": reman_order_id,
        "dyno_cell_code": dyno_cell_code,
        "start_utc": start_utc,
        "end_utc": end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_dyno_run_payload(reman_order_id, gear_pressures_kpa=None,
                            **overrides) -> dict:
    defaults = {
        "reman_order_id": reman_order_id,
        "gear_pressures_kpa": gear_pressures_kpa if gear_pressures_kpa is not None
        else [200, 220, 240, 260],
    }
    defaults.update(overrides)
    return defaults


def create_core_unit_payload(core_deposit_invoice_id, dock_code="DOCK-1",
                             dock_start_utc="2026-08-01T10:00:00Z",
                             dock_end_utc="2026-08-01T11:00:00Z",
                             **overrides) -> dict:
    defaults = {
        "core_deposit_invoice_id": core_deposit_invoice_id,
        "dock_code": dock_code,
        "dock_start_utc": dock_start_utc,
        "dock_end_utc": dock_end_utc,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(case_cracked=False, findings=None,
                              **overrides) -> dict:
    defaults = {
        "case_cracked": case_cracked,
        "findings": list(findings) if findings is not None else [],
    }
    defaults.update(overrides)
    return defaults


def create_stock_adjustment_payload(qty_delta, expected_hard_part_version) -> dict:
    return {
        "qty_delta": qty_delta,
        "expected_hard_part_version": expected_hard_part_version,
    }


def create_resolve_dispute_payload(action, adjusted_credit_cents=None) -> dict:
    payload = {"action": action}
    if adjusted_credit_cents is not None:
        payload["adjusted_credit_cents"] = adjusted_credit_cents
    return payload


def create_warranty_claim_payload(reman_order_id, failure_code="GEAR_CLUNK",
                                  claimed_labor_hours=5.0,
                                  installer_labor_rate_cents=12000,
                                  allowance_policy="BOOK_HOURS",
                                  **overrides) -> dict:
    defaults = {
        "reman_order_id": reman_order_id,
        "failure_code": failure_code,
        "claimed_labor_hours": claimed_labor_hours,
        "installer_labor_rate_cents": installer_labor_rate_cents,
        "allowance_policy": allowance_policy,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601=DEFAULT_CLOCK_UTC) -> dict:
    return {"to_iso8601": to_iso8601}
