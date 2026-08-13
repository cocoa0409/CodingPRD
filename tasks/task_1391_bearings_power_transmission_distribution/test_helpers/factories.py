"""Payload factories — one per entity, input fields only (PRD Section 4)."""

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_product_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "sku": f"BRG-{n:05d}",
        "description": f"Test bearing {n}",
        "family": "BEARING",
        "list_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_interchange_record_payload(product_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "competitor_part_number": f"CMP-{n}",
        "product_id": product_id,
        "interchange_class": "EXACT",
        "min_shaft_diameter_mm": 45,
        "max_shaft_diameter_mm": 55,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Test Plant {n}",
        "credit_limit_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "family": "BEARING",
        "price_basis": "LIST_LESS",
        "discount_pct": 0.10,
        "effective_from": "2026-01-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_branch_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "code": f"BR-{n:03d}",
        "timezone_offset_hours": 0,
        "business_open_hour": 8,
        "business_close_hour": 17,
        "expedite_cutoff_hour": 14,
        "after_hours_fee_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_branch_stock_payload(branch_id, product_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "product_id": product_id,
        "on_hand_qty": 10,
        "factory_lead_time_days": 5,
    }
    defaults.update(overrides)
    return defaults


def create_price_file_payload(product_id, expected_product_version, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "new_list_price_cents": 12000,
        "effective_at": "2026-12-01T00:00:00Z",
        "expected_product_version": expected_product_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, branch_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "branch_id": branch_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_call_out_payload(branch_id, customer_id, product_id, **overrides) -> dict:
    defaults = {
        "branch_id": branch_id,
        "customer_id": customer_id,
        "product_id": product_id,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_consignment_agreement_payload(customer_id, branch_id, product_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "branch_id": branch_id,
        "product_id": product_id,
        "consigned_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_consumption_payload(**overrides) -> dict:
    defaults = {"qty": 1}
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(product_id, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "failure_mode": "FATIGUE",
        "operating_hours": 100,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_return_authorization_payload(customer_id, product_id, branch_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "branch_id": branch_id,
        "qty": 1,
        "condition": "SURPLUS",
        "original_unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_service_shop_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Repair Shop {n}",
        "capabilities": ["BEARING"],
        "region": "R1",
        "labor_rate_cents": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_service_referral_payload(warranty_claim_id, **overrides) -> dict:
    defaults = {
        "warranty_claim_id": warranty_claim_id,
        "region": "R1",
    }
    defaults.update(overrides)
    return defaults
