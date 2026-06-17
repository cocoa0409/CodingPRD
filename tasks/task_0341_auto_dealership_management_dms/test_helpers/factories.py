"""Payload factories — one per entity, input fields only.

VINs must be exactly 17 chars of uppercase alphanumerics excluding I, O, Q.
``unique_vin`` generates a conforming, collision-free VIN per call.
"""
import itertools

_VIN_COUNTER = itertools.count(1)
# 17-char base prefix using only legal VIN characters (no I, O, Q).
_VIN_PREFIX = "1HGAC1ANCM"  # 10 chars


def unique_vin() -> str:
    """A unique, well-formed 17-char VIN (uppercase alphanumerics, no I/O/Q)."""
    suffix = f"{next(_VIN_COUNTER):07d}"  # 7 digits -> 10 + 7 = 17
    return (_VIN_PREFIX + suffix)[:17]


_EMAIL_COUNTER = itertools.count(1)


def unique_email() -> str:
    return f"cust{next(_EMAIL_COUNTER)}@example.com"


_CODE_COUNTER = itertools.count(1)


def unique_code(prefix="PRD") -> str:
    return f"{prefix}{next(_CODE_COUNTER)}"


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "vin": unique_vin(),
        "condition": "NEW",
        "make": "ACME",
        "model": "SED",
        "model_year": 2026,
        "msrp_cents": 3300000,
        "list_price_cents": 3200000,
    }
    defaults.update(overrides)
    return defaults


def create_floor_plan_line_payload(expected_vehicle_version, **overrides) -> dict:
    defaults = {
        "lender_name": "FLOORBANK",
        "principal_cents": 3000000,
        "annual_rate_bps": 825,
        "floored_on": "2026-05-01T00:00:00.000Z",
        "expected_vehicle_version": expected_vehicle_version,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": unique_email(),
        "monthly_income_cents": 2500000,
        "credit_tier": "TIER_A",
        "drivers_license_valid": True,
    }
    defaults.update(overrides)
    return defaults


def create_lender_program_payload(**overrides) -> dict:
    defaults = {
        "lender_name": "CREDITONE",
        "tier": "TIER_A",
        "buy_rate_bps": 549,
        "max_markup_bps": 200,
        "max_ltv_bps": 12500,
        "max_pti_bps": 1800,
        "max_term_months": 72,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_finance_product_payload(**overrides) -> dict:
    defaults = {
        "code": unique_code("VSC"),
        "name": "Vehicle Service Contract",
        "cost_cents": 180000,
        "max_retail_cents": 300000,
        "taxable": False,
    }
    defaults.update(overrides)
    return defaults


def create_oem_incentive_payload(**overrides) -> dict:
    defaults = {
        "program_code": unique_code("CASH"),
        "rebate_cents": 150000,
        "eligible_condition": "ANY",
        "eligible_make": None,
        "min_model_year": None,
        "stackable_with_finance": True,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(vehicle_id, customer_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "deal_type": "FINANCE",
        "sale_price_cents": 2000000,
        "accessories_cents": 0,
        "doc_fee_cents": 0,
        "title_fee_cents": 0,
        "registration_fee_cents": 0,
        "tax_rate_bps": 725,
        "cash_down_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(**overrides) -> dict:
    defaults = {
        "vin": unique_vin(),
        "acv_cents": 800000,
        "allowance_cents": 800000,
        "payoff_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_finance_contract_payload(lender_program_id, expected_deal_version, **overrides) -> dict:
    defaults = {
        "lender_program_id": lender_program_id,
        "markup_bps": 100,
        "term_months": 72,
        "expected_deal_version": expected_deal_version,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(**overrides) -> dict:
    defaults = {
        "doc_type": "CREDIT_APP",
        "uri": "s3://jacket/doc.pdf",
    }
    defaults.update(overrides)
    return defaults


def create_test_drive_payload(vehicle_id, customer_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "customer_id": customer_id,
        "start_at": "2026-06-10T10:00:00.000Z",
        "end_at": "2026-06-10T10:30:00.000Z",
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(vehicle_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "deal_id": None,
        "ro_type": "RETAIL",
        "bay": "BAY_1",
        "scheduled_start_at": "2026-06-12T10:00:00.000Z",
        "scheduled_end_at": "2026-06-12T11:00:00.000Z",
        "parts_cents": 0,
        "labor_cents": 0,
    }
    defaults.update(overrides)
    return defaults
