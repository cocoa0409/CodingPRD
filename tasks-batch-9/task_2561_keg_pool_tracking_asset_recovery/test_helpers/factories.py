"""Payload factories — one per write endpoint, caller-supplied fields only."""

from typing import List, Optional

from .constants import TEST_DEFAULTS


def create_brewer_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["BREWER_NAME"],
        "brand_code": TEST_DEFAULTS["BREWER_BRAND_CODE"],
        "credit_limit_cents": TEST_DEFAULTS["BREWER_CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def brewer_status_payload(status: str, **overrides) -> dict:
    payload = {"status": status}
    payload.update(overrides)
    return payload


def create_distributor_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["DISTRIBUTOR_NAME"],
        "region_code": TEST_DEFAULTS["DISTRIBUTOR_REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def cooperation_agreement_payload(
    cooperation_tier: str, effective_date: str, **overrides
) -> dict:
    payload = {
        "cooperation_tier": cooperation_tier,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def create_pool_payload(**overrides) -> dict:
    payload = {
        "pool_code": TEST_DEFAULTS["POOL_CODE"],
        "size_liters": TEST_DEFAULTS["POOL_SIZE_LITERS"],
        "stainless_weight_kg": TEST_DEFAULTS["POOL_STAINLESS_WEIGHT_KG"],
        "replacement_cost_cents": TEST_DEFAULTS["POOL_REPLACEMENT_COST_CENTS"],
        "region_code": TEST_DEFAULTS["POOL_REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def import_keg_payload(asset_tag: str, **overrides) -> dict:
    payload = {"asset_tag": asset_tag}
    payload.update(overrides)
    return payload


def fill_scan_payload(brewer_id: str, scanned_at: str, brand_code: str, **overrides) -> dict:
    payload = {
        "scan_point": "FILL",
        "party_type": "BREWER",
        "scanned_at": scanned_at,
        "brand_code_scanned": brand_code,
        "brewer_id": brewer_id,
    }
    payload.update(overrides)
    return payload


def distribution_scan_payload(
    distributor_id: str, scanned_at: str, brand_code: str, **overrides
) -> dict:
    payload = {
        "scan_point": "DISTRIBUTION",
        "party_type": "DISTRIBUTOR",
        "scanned_at": scanned_at,
        "brand_code_scanned": brand_code,
        "distributor_id": distributor_id,
    }
    payload.update(overrides)
    return payload


def retail_scan_payload(
    retail_account_code: str, scanned_at: str, brand_code: str, **overrides
) -> dict:
    payload = {
        "scan_point": "RETAIL",
        "party_type": "RETAIL_ACCOUNT",
        "scanned_at": scanned_at,
        "brand_code_scanned": brand_code,
        "retail_account_code": retail_account_code,
    }
    payload.update(overrides)
    return payload


def return_scan_payload(
    distributor_id: str, scanned_at: str, brand_code: str, **overrides
) -> dict:
    payload = {
        "scan_point": "RETURN",
        "party_type": "DISTRIBUTOR",
        "scanned_at": scanned_at,
        "brand_code_scanned": brand_code,
        "distributor_id": distributor_id,
    }
    payload.update(overrides)
    return payload


def create_float_agreement_payload(
    brewer_id: str, pool_id: str, float_size_kegs: int, **overrides
) -> dict:
    payload = {
        "brewer_id": brewer_id,
        "pool_id": pool_id,
        "float_size_kegs": float_size_kegs,
        "per_fill_rate_cents": TEST_DEFAULTS["PER_FILL_RATE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_issuance_order_payload(
    agreement_id: str, requested_keg_count: int, **overrides
) -> dict:
    payload = {
        "agreement_id": agreement_id,
        "requested_keg_count": requested_keg_count,
    }
    payload.update(overrides)
    return payload


def create_service_center_payload(concurrent_cycle_capacity: int = 1, **overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["SERVICE_CENTER_NAME"],
        "region_code": TEST_DEFAULTS["SERVICE_CENTER_REGION_CODE"],
        "concurrent_cycle_capacity": concurrent_cycle_capacity,
    }
    payload.update(overrides)
    return payload


def create_service_cycle_payload(
    keg_id: str, service_center_id: str, received_at: str, **overrides
) -> dict:
    payload = {
        "keg_id": keg_id,
        "service_center_id": service_center_id,
        "received_at": received_at,
    }
    payload.update(overrides)
    return payload


def clean_step_payload(occurred_at: str, caustic_cycle_minutes: int = 12, **overrides) -> dict:
    payload = {
        "step": "CLEAN",
        "occurred_at": occurred_at,
        "caustic_cycle_minutes": caustic_cycle_minutes,
    }
    payload.update(overrides)
    return payload


def inspect_step_payload(occurred_at: str, inspection_result: str = "PASS", **overrides) -> dict:
    payload = {
        "step": "INSPECT",
        "occurred_at": occurred_at,
        "inspection_result": inspection_result,
    }
    payload.update(overrides)
    return payload


def pressure_test_step_payload(
    occurred_at: str,
    pressure_test_psi: float = 45,
    pressure_test_result: str = "PASS",
    **overrides,
) -> dict:
    payload = {
        "step": "PRESSURE_TEST",
        "occurred_at": occurred_at,
        "pressure_test_psi": pressure_test_psi,
        "pressure_test_result": pressure_test_result,
    }
    payload.update(overrides)
    return payload


def create_loss_assessment_payload(
    keg_id: str, cause: str, expected_keg_version: int, **overrides
) -> dict:
    payload = {
        "keg_id": keg_id,
        "cause": cause,
        "expected_keg_version": expected_keg_version,
    }
    payload.update(overrides)
    return payload


def resolve_assessment_payload(resolution: str, **overrides) -> dict:
    payload = {
        "resolution": resolution,
        "resolution_notes": "Recorded by the recovery desk.",
    }
    payload.update(overrides)
    return payload


def chargeback_resolution_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def create_reconciliation_claim_payload(
    keg_id: str,
    misdelivered_to_brewer_id: str,
    claimed_offset_cents: int,
    evidence_scanned_at: str,
    **overrides,
) -> dict:
    payload = {
        "keg_id": keg_id,
        "misdelivered_to_brewer_id": misdelivered_to_brewer_id,
        "claimed_offset_cents": claimed_offset_cents,
        "evidence_scanned_at": evidence_scanned_at,
    }
    payload.update(overrides)
    return payload


def claim_response_payload(response: str, expected_claim_version: int, **overrides) -> dict:
    payload = {
        "response": response,
        "expected_claim_version": expected_claim_version,
    }
    payload.update(overrides)
    return payload


def create_theft_investigation_payload(
    pool_id: str, keg_ids: List[str], **overrides
) -> dict:
    payload = {
        "pool_id": pool_id,
        "keg_ids": keg_ids,
        "opened_reason": "Stainless shrinkage reported on the trade route.",
    }
    payload.update(overrides)
    return payload


def investigation_status_payload(action: str, **overrides) -> dict:
    payload = {"action": action}
    payload.update(overrides)
    return payload


def commodity_index_payload(
    effective_date: Optional[str] = None,
    usd_cents_per_kg: Optional[int] = None,
    **overrides,
) -> dict:
    payload = {
        "effective_date": effective_date or TEST_DEFAULTS["COMMODITY_INDEX_DATE"],
        "usd_cents_per_kg": (
            usd_cents_per_kg
            if usd_cents_per_kg is not None
            else TEST_DEFAULTS["COMMODITY_INDEX_CENTS_PER_KG"]
        ),
        "source": TEST_DEFAULTS["COMMODITY_INDEX_SOURCE"],
    }
    payload.update(overrides)
    return payload
