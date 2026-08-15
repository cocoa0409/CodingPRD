"""Payload factories — one per entity, input fields only (PRD sections 3, 4)."""


def create_dealer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Dealer",
        "dealer_code": "DL-TEST",
        "region": "West",
        "credit_limit_cents": 500000,
        "min_stock_value_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(dealer_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "agreement_code": "AGR-TEST",
        "effective_date": "2026-01-01",
        "expiry_date": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(dealer_id: str, agreement_id: str,
                              **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "agreement_id": agreement_id,
        "territory_code": "T-TEST",
        "coverage_type": "EXCLUSIVE",
        "starts_on": "2026-01-01",
        "ends_on": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def create_sales_target_payload(dealer_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "period_year": 2026,
        "period_quarter": 3,
        "target_units": 5,
    }
    defaults.update(overrides)
    return defaults


def create_unit_sale_payload(dealer_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "unit_serial": "UNIT-1",
        "sale_date": "2026-08-05",
        "list_price_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_advance_payload(dealer_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "unit_serial": "UNIT-1",
        "advance_cents": 50000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(dealer_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "unit_serial": "UNIT-1",
        "parts_cost_cents": 10000,
        "labor_hours": 0,
        "failure_description": "test failure",
    }
    defaults.update(overrides)
    return defaults


def create_parts_return_payload(dealer_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "return_year": 2026,
        "lines": [{"part_number": "P1", "quantity": 1,
                   "unit_credit_cents": 100}],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(dealer_id: str, **overrides) -> dict:
    defaults = {
        "dealer_id": dealer_id,
        "cert_code": "CTE-TEST",
        "earned_on": "2026-01-10",
        "expires_on": "2028-01-10",
    }
    defaults.update(overrides)
    return defaults


def create_lead_payload(**overrides) -> dict:
    defaults = {
        "territory_code": "T-TEST",
        "product_line": "DOZER",
        "estimated_value_cents": 100000,
        "contact_name": "Test Contact",
    }
    defaults.update(overrides)
    return defaults
