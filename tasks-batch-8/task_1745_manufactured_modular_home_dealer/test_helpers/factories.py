"""Payload factories — one per creatable resource, input fields only (PRD §3)."""
import itertools

_counter = itertools.count(1)


def _n() -> int:
    return next(_counter)


def create_home_model_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "model_code": f"SW-139-{i}",
        "name": f"Slim 139 #{i}",
        "floor_plan_type": "SINGLE_WIDE",
        "section_count": 1,
        "width_ft": 13.9,
        "length_ft": 66,
        "base_price_cents": 4_200_000,
        "factory_lead_time_days": 14,
    }
    defaults.update(overrides)
    return defaults


def double_wide_model_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "model_code": f"DW-2860-{i}",
        "name": f"Pride 2860 #{i}",
        "floor_plan_type": "DOUBLE_WIDE",
        "section_count": 2,
        "width_ft": 28,
        "length_ft": 60,
        "base_price_cents": 9_500_000,
        "factory_lead_time_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_community_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Pinewood MHC #{i}",
        "address": f"{i} Pine Rd",
        "lot_rent_cents": 45_000,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "lot_number": f"A-{i:02d}",
        "max_sections": 2,
        "max_length_ft": 70,
        "utilities_ready": True,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "full_name": f"Buyer {i}",
        "email": f"buyer{i}@example.com",
        "phone": f"555-{1000 + i}",
        "credit_tier": "TIER_A",
    }
    defaults.update(overrides)
    return defaults


def create_home_unit_payload(model_id, **overrides) -> dict:
    i = _n()
    defaults = {
        "model_id": model_id,
        "serial_number": f"SN-{i:05d}",
        "unit_kind": "STOCK",
        "condition_grade": "NEW",
    }
    defaults.update(overrides)
    return defaults


def create_sales_order_payload(customer_id, home_unit_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "home_unit_id": home_unit_id,
        "placement_type": "PRIVATE_LAND",
        "financing_type": "CHATTEL",
        "agreed_home_price_cents": 4_200_000,
    }
    defaults.update(overrides)
    return defaults


def create_order_option_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "option_code": f"OPT-{i}",
        "description": f"Factory option {i}",
        "unit_price_cents": 125_050,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_site_evaluation_payload(expected_sales_order_version, **overrides) -> dict:
    defaults = {
        "scheduled_date": "2026-08-05T09:00:00Z",
        "evaluator_id": "eval-1",
        "expected_sales_order_version": expected_sales_order_version,
    }
    defaults.update(overrides)
    return defaults


def record_findings_payload(**overrides) -> dict:
    defaults = {
        "foundation_type": "PIERS",
        "utilities_verified": True,
        "permit_number": "P-100",
        "findings_result": "PASS",
        "install_estimate_cents": 350_000,
    }
    defaults.update(overrides)
    return defaults


def create_financing_application_payload(financing_type, expected_sales_order_version, **overrides) -> dict:
    defaults = {
        "financing_type": financing_type,
        "lender_name": "Cascade Finance",
        "term_months": 240,
        "down_payment_cents": 0,
        "expected_sales_order_version": expected_sales_order_version,
    }
    defaults.update(overrides)
    return defaults


def create_transport_crew_payload(**overrides) -> dict:
    i = _n()
    defaults = {
        "name": f"Crew Alpha #{i}",
        "crew_size": 4,
        "can_set_multiwide": True,
        "max_sections_per_window": 2,
    }
    defaults.update(overrides)
    return defaults


def create_transport_job_payload(home_unit_id, crew_id, **overrides) -> dict:
    defaults = {
        "home_unit_id": home_unit_id,
        "crew_id": crew_id,
        "origin": "DEALER_LOT",
        "distance_miles": 180,
        "scheduled_start_date": "2026-08-20T08:00:00Z",
        "escort_vehicle_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_delay_notice_payload(**overrides) -> dict:
    defaults = {
        "reason": "FACTORY_DELAY",
        "original_date": "2026-08-20T08:00:00Z",
        "new_date": "2026-08-30T08:00:00Z",
        "buyer_notified": True,
    }
    defaults.update(overrides)
    return defaults


def create_title_record_payload(**overrides) -> dict:
    defaults = {
        "title_type": "MANUFACTURED_CERTIFICATE",
        "state_code": "AL",
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(home_unit_id, sales_order_id, **overrides) -> dict:
    defaults = {
        "home_unit_id": home_unit_id,
        "sales_order_id": sales_order_id,
        "claim_type": "FACTORY_DEFECT",
        "description": "Roof seam leak",
        "estimated_cost_cents": 240_000,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_appraisal_payload(model_id, **overrides) -> dict:
    defaults = {
        "declared_model_year": 2012,
        "declared_condition": "B",
        "model_id": model_id,
    }
    defaults.update(overrides)
    return defaults


def inspect_trade_in_payload(**overrides) -> dict:
    defaults = {
        "appraised_value_cents": 1_500_000,
        "reconditioning_cost_cents": 400_000,
        "condition_grade": "B",
    }
    defaults.update(overrides)
    return defaults
