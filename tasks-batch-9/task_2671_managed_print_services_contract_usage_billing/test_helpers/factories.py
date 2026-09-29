"""Payload factories — one per creatable resource, request-input fields only."""

from typing import Any, Dict, Optional

from .constants import TEST_DEFAULTS


def service_contract_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "customer_name": TEST_DEFAULTS["CUSTOMER_NAME"],
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "included_service_scope": "BASIC",
        "minimum_mono_pages_per_period": 0,
        "minimum_color_pages_per_period": 0,
        "monthly_service_fee_cents": TEST_DEFAULTS["MONTHLY_SERVICE_FEE_CENTS"],
        "response_sla_hours_critical": 4,
        "response_sla_hours_standard": 24,
        "labor_rate_cents_per_hour": TEST_DEFAULTS["LABOR_RATE_CENTS_PER_HOUR"],
        "early_termination_fee_cents": 0,
    }
    payload.update(overrides)
    return payload


def cost_tier_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "page_class": "MONO",
        "tier_index": 1,
        "from_page": 1,
        "rate_micro_dollars_per_page": TEST_DEFAULTS["MONO_RATE_MICRO_DOLLARS"],
    }
    payload.update(overrides)
    return payload


def site_payload(contract_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "name": "Plant 1",
        "address_region": TEST_DEFAULTS["REGION"],
        "toner_unit_cap": TEST_DEFAULTS["TONER_UNIT_CAP"],
        "network_vlan_tag": TEST_DEFAULTS["VLAN_TAG"],
    }
    payload.update(overrides)
    return payload


def secure_release_config_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "release_method": "PIN",
        "probe_result": "PASS",
        "network_vlan_tag": TEST_DEFAULTS["VLAN_TAG"],
    }
    payload.update(overrides)
    return payload


def spare_part_stock_payload(part_sku: str = "FUSER-9", qty_delta: int = 1) -> Dict[str, Any]:
    return {"part_sku": part_sku, "qty_delta": qty_delta}


def device_payload(contract_id: str, site_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "site_id": site_id,
        "asset_tag": "MPS-0001",
        "model_code": "XR-M4200",
        "rated_monthly_duty_cycle": TEST_DEFAULTS["RATED_MONTHLY_DUTY_CYCLE"],
        "assessed_monthly_mono_pages": TEST_DEFAULTS["ASSESSED_MONO_PAGES"],
        "assessed_monthly_color_pages": 0,
        "baseline_cost_micro_dollars_per_page": TEST_DEFAULTS["BASELINE_COST_MICRO_DOLLARS"],
        "baseline_overhead_cents_per_month": TEST_DEFAULTS["BASELINE_OVERHEAD_CENTS"],
        "color_capable": False,
    }
    payload.update(overrides)
    return payload


def technician_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "full_name": "Tess Rowan",
        "home_region": TEST_DEFAULTS["REGION"],
        "skill_level": "L3",
        "travel_buffer_minutes": 30,
    }
    payload.update(overrides)
    return payload


def billing_period_payload(contract_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "contract_id": contract_id,
        "period_start": TEST_DEFAULTS["PERIOD_START"],
        "period_end": TEST_DEFAULTS["PERIOD_END"],
    }
    payload.update(overrides)
    return payload


def meter_read_payload(device_id: str, billing_period_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "device_id": device_id,
        "billing_period_id": billing_period_id,
        "mono_meter": 1000,
        "color_meter": 0,
        "toner_level_pct": 80,
        "coverage_start": "2026-08-01T00:00:00Z",
        "coverage_end": "2026-08-08T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def resolve_exception_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "corrected_mono_meter": 5000,
        "corrected_color_meter": 0,
        "corrected_toner_level_pct": 60,
        "resolution_note": "manual read taken from device panel",
    }
    payload.update(overrides)
    return payload


def void_read_payload(voided_reason: str = "DUPLICATE_CAPTURE") -> Dict[str, Any]:
    return {"voided_reason": voided_reason}


def provisional_statement_payload(expected_billing_period_version: int) -> Dict[str, Any]:
    return {"expected_billing_period_version": expected_billing_period_version}


def consumable_order_payload(device_id: str, expected_device_version: int, **overrides) -> Dict[str, Any]:
    payload = {
        "device_id": device_id,
        "part_type": "TONER_BLACK",
        "unit_price_cents": 8900,
        "expected_device_version": expected_device_version,
        "quantity": 1,
    }
    payload.update(overrides)
    return payload


def cancel_order_payload(cancel_reason: str = "WRONG_PART") -> Dict[str, Any]:
    return {"cancel_reason": cancel_reason}


def service_ticket_payload(device_id: str, **overrides) -> Dict[str, Any]:
    payload = {
        "device_id": device_id,
        "severity": "STANDARD",
        "symptom_code": "PAPER_JAM",
    }
    payload.update(overrides)
    return payload


def dispatch_payload(technician_id: str, window_start: str, window_end: str) -> Dict[str, Any]:
    return {
        "technician_id": technician_id,
        "window_start": window_start,
        "window_end": window_end,
    }


def resolve_ticket_payload(labor_hours: float = 1.0) -> Dict[str, Any]:
    return {"labor_hours": labor_hours}


def quarterly_review_payload(contract_id: str, quarter_label: str = "2026-Q3") -> Dict[str, Any]:
    return {"contract_id": contract_id, "quarter_label": quarter_label}


def removal_order_payload(contract_id: str, scheduled_for: str) -> Dict[str, Any]:
    return {"contract_id": contract_id, "scheduled_for": scheduled_for}


def schedule_removal_payload(scheduled_for: str) -> Dict[str, Any]:
    return {"scheduled_for": scheduled_for}


def sanitize_payload(
    sanitization_method: str = "CRYPTO_ERASE",
    sanitization_certificate_ref: Optional[str] = "CERT-2026-08-20-A",
) -> Dict[str, Any]:
    return {
        "sanitization_method": sanitization_method,
        "sanitization_certificate_ref": sanitization_certificate_ref,
    }


def suspend_payload(reason: str = "NONPAYMENT") -> Dict[str, Any]:
    return {"reason": reason}


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def refresh_replacement_payload(successor_device_id: str) -> Dict[str, Any]:
    return {"successor_device_id": successor_device_id}
