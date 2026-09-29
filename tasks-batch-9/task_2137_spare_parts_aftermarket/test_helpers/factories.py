"""Payload factories — one per creating endpoint, input fields only."""

from .constants import TEST_DEFAULTS


def create_part_payload(**overrides) -> dict:
    defaults = {
        "part_number": "PN-0001",
        "description": "Test spare part",
        "unit_cost_cents": TEST_DEFAULTS["UNIT_COST_CENTS"],
        "lead_time_days": TEST_DEFAULTS["LEAD_TIME_DAYS"],
        "weight_kg": TEST_DEFAULTS["WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": "EM-0001",
        "name": "Test machine model",
        "production_end_date": TEST_DEFAULTS["PRODUCTION_END_DATE"],
        "support_end_date": TEST_DEFAULTS["SUPPORT_END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_installed_unit_payload(model_id, dealer_id, **overrides) -> dict:
    defaults = {
        "model_id": model_id,
        "dealer_id": dealer_id,
        "serial_number": "SN-0001",
        "build_revision": TEST_DEFAULTS["BUILD_REVISION"],
        "commission_date": TEST_DEFAULTS["COMMISSION_DATE"],
        "region": "NA",
    }
    defaults.update(overrides)
    return defaults


def create_part_applicability_payload(part_id, model_id, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "model_id": model_id,
        "effective_from_build_revision": 0,
        "qty_per_unit": 1,
    }
    defaults.update(overrides)
    return defaults


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "dealer_code": "D-0001",
        "tier": "GOLD",
        "region": "NA",
        "credit_limit_cents": TEST_DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(installed_unit_id, **overrides) -> dict:
    defaults = {
        "installed_unit_id": installed_unit_id,
        "work_type": "SCHEDULED_MAINTENANCE",
        "downtime_priority": "PLANNED",
    }
    defaults.update(overrides)
    return defaults


def create_part_line_payload(part_id, qty_requested=1, **overrides) -> dict:
    defaults = {"part_id": part_id, "qty_requested": qty_requested}
    defaults.update(overrides)
    return defaults


def create_forecast_payload(**overrides) -> dict:
    defaults = {"horizon_months": 12, "method": "INSTALLED_BASE_RATE"}
    defaults.update(overrides)
    return defaults


def create_campaign_payload(part_id, expected_part_version, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "method": "FLAT_RATE",
        "coverage_years": 3,
        "ltb_window_start": TEST_DEFAULTS["LTB_WINDOW_START"],
        "ltb_window_end": TEST_DEFAULTS["LTB_WINDOW_END"],
        "expected_part_version": expected_part_version,
    }
    defaults.update(overrides)
    return defaults


def create_allocation_request_payload(campaign_id, dealer_id, requested_units,
                                      expected_campaign_version, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "dealer_id": dealer_id,
        "requested_units": requested_units,
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def create_price_rule_payload(criticality_class="DESIRABLE", base_uplift_pct=0.35,
                              max_uplift_pct=0.60, min_margin_pct=0.20,
                              **overrides) -> dict:
    defaults = {
        "criticality_class": criticality_class,
        "base_uplift_pct": base_uplift_pct,
        "max_uplift_pct": max_uplift_pct,
        "min_margin_pct": min_margin_pct,
    }
    defaults.update(overrides)
    return defaults


def create_replenishment_order_payload(part_id, order_type="STOCK", qty=10,
                                       **overrides) -> dict:
    defaults = {"part_id": part_id, "order_type": order_type, "qty": qty}
    defaults.update(overrides)
    return defaults


def create_return_authorization_payload(work_order_part_line_id, qty_returned,
                                        return_reason, **overrides) -> dict:
    defaults = {
        "work_order_part_line_id": work_order_part_line_id,
        "qty_returned": qty_returned,
        "return_reason": return_reason,
    }
    defaults.update(overrides)
    return defaults
