"""Payload factories — one per entity, input fields only."""

from .constants import (
    CAMPAIGN_WINDOW_END,
    CAMPAIGN_WINDOW_START,
    HARDNESS_WINDOW,
    TEST_DEFAULTS,
)


def tool_sku_payload(**overrides) -> dict:
    """A BRANDED 17 mm CR_MO wrench: the reference catalogue entry."""
    payload = {
        "sku_code": "WR-17-BR",
        "tool_family": "WRENCH",
        "channel": "BRANDED",
        "nominal_size_mm": 17,
        "alloy_grade": "CR_MO",
        "list_price_cents": TEST_DEFAULTS["SKU_LIST_PRICE_CENTS"],
        "warranty_tier": "LIFETIME",
    }
    payload.update(overrides)
    return payload


def stock_receipt_payload(**overrides) -> dict:
    payload = {"units_received": 10}
    payload.update(overrides)
    return payload


def heat_treat_furnace_payload(**overrides) -> dict:
    payload = {
        "furnace_code": "FCE-1",
        "max_charge_kg": TEST_DEFAULTS["MAX_CHARGE_KG"],
        "alloy_grades_supported": ["CR_MO"],
    }
    payload.update(overrides)
    return payload


def furnace_status_payload(**overrides) -> dict:
    payload = {"status": "MAINTENANCE"}
    payload.update(overrides)
    return payload


def salt_spray_chamber_payload(**overrides) -> dict:
    payload = {
        "chamber_code": "SSC-1",
        "coupon_capacity": TEST_DEFAULTS["COUPON_CAPACITY"],
    }
    payload.update(overrides)
    return payload


def production_lot_payload(sku_id: str, **overrides) -> dict:
    payload = {
        "sku_id": sku_id,
        "lot_code": "LOT-A",
        "unit_count": TEST_DEFAULTS["LOT_UNIT_COUNT"],
        "specimen_pool_total": TEST_DEFAULTS["SPECIMEN_POOL_TOTAL"],
    }
    payload.update(overrides)
    return payload


def advance_payload(target_process_status: str) -> dict:
    return {"target_process_status": target_process_status}


def rework_payload(**overrides) -> dict:
    payload = {"rework_note": "Re-machine and re-plate after rejection"}
    payload.update(overrides)
    return payload


def release_payload(expected_sku_version: int) -> dict:
    return {"expected_sku_version": expected_sku_version}


def furnace_campaign_payload(lot_id: str, furnace_id: str, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "furnace_id": furnace_id,
        "window_start": CAMPAIGN_WINDOW_START,
        "window_end": CAMPAIGN_WINDOW_END,
        "charge_kg": TEST_DEFAULTS["CHARGE_KG"],
    }
    payload.update(overrides)
    return payload


def campaign_complete_payload(**overrides) -> dict:
    payload = {"soak_minutes": TEST_DEFAULTS["SOAK_MINUTES"]}
    payload.update(overrides)
    return payload


def make_test_run_payload(lot_id: str, test_type: str = "HARDNESS", **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "test_type": test_type,
        "specimen_count": 2,
        "window_start": HARDNESS_WINDOW[0],
        "window_end": HARDNESS_WINDOW[1],
    }
    payload.update(overrides)
    return payload


def make_test_results_payload(readings) -> dict:
    return {"readings": list(readings)}


def void_payload(**overrides) -> dict:
    payload = {"void_reason": "Run will not be executed"}
    payload.update(overrides)
    return payload


def pack_configuration_payload(primary_sku_id: str, **overrides) -> dict:
    payload = {
        "pack_code": "PK-1",
        "pack_type": "RETAIL_DISPLAY",
        "primary_sku_id": primary_sku_id,
    }
    payload.update(overrides)
    return payload


def pack_member_payload(sku_id: str, quantity: int = 1, **overrides) -> dict:
    payload = {"sku_id": sku_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def pack_withdraw_payload(**overrides) -> dict:
    payload = {"withdrawal_reason": "Artwork revision"}
    payload.update(overrides)
    return payload


def warranty_program_payload(**overrides) -> dict:
    payload = {
        "program_code": "LIFETIME-1",
        "reserve_funded_cents": TEST_DEFAULTS["RESERVE_FUNDED_CENTS"],
        "fraud_score_threshold": TEST_DEFAULTS["FRAUD_SCORE_THRESHOLD"],
    }
    payload.update(overrides)
    return payload


def claimant_payload(**overrides) -> dict:
    payload = {"email": "c1@example.com", "claimant_type": "CONSUMER"}
    payload.update(overrides)
    return payload


def claimant_block_payload(**overrides) -> dict:
    payload = {"block_reason": "Confirmed abuse of the replacement allowance"}
    payload.update(overrides)
    return payload


def warranty_claim_payload(claimant_id: str, sku_id: str, program_id: str, **overrides) -> dict:
    payload = {
        "claimant_id": claimant_id,
        "sku_id": sku_id,
        "program_id": program_id,
        "serial_code": "SN-1",
        "claim_reason": "BREAKAGE",
    }
    payload.update(overrides)
    return payload


def claim_line_payload(**overrides) -> dict:
    payload = {
        "component_code": "HANDLE",
        "component_list_price_cents": 1099,
        "quantity": 1,
    }
    payload.update(overrides)
    return payload


def hold_payload(**overrides) -> dict:
    payload = {"hold_reason": "SERIAL_PATTERN_REVIEW"}
    payload.update(overrides)
    return payload


def clear_hold_payload(**overrides) -> dict:
    payload = {"clearance_note": "Independent review complete"}
    payload.update(overrides)
    return payload


def approve_claim_payload(expected_program_version: int) -> dict:
    return {"expected_program_version": expected_program_version}


def deny_payload(**overrides) -> dict:
    payload = {"denial_code": "OUT_OF_SCOPE"}
    payload.update(overrides)
    return payload


def fulfill_payload(**overrides) -> dict:
    payload = {"shipment_ref": "UPS-1Z-0001"}
    payload.update(overrides)
    return payload


def revoke_payload(**overrides) -> dict:
    payload = {"revocation_reason": "Counterfeit tool returned under warranty"}
    payload.update(overrides)
    return payload


def counterfeit_report_payload(sku_id: str, **overrides) -> dict:
    payload = {
        "sku_id": sku_id,
        "channel_name": "GreyBazaar",
        "seller_handle": "seller-a",
        "evidence_grade": "STRONG",
        "unit_estimate": 600,
    }
    payload.update(overrides)
    return payload


def confirm_report_payload(**overrides) -> dict:
    payload = {"confirmation_note": "Test purchase authenticated as counterfeit"}
    payload.update(overrides)
    return payload


def dismiss_report_payload(**overrides) -> dict:
    payload = {"dismissal_note": "Genuine unit, mislabelled listing"}
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str) -> dict:
    return {"current_utc": current_utc}
