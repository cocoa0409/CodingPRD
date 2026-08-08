"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CLIENT_LEGAL_NAME": "Test Taxpayer LLC",
    "ENTITY_TYPE": "C_CORP",
    "MARGINAL_TAX_RATE": 0.21,
    "PROPERTY_ADDRESS": "1 Test Plaza",
    "BUILDING_TYPE": "COMMERCIAL",
    "PURCHASE_PRICE_CENTS": 120000000,
    "LAND_VALUE_CENTS": 20000000,
    "PLACED_IN_SERVICE_DATE": "2024-03-01T00:00:00.000Z",
    "ENGINEER_NAME": "Test Engineer",
    "ENGINEER_EMAIL": "eng@example.com",
    "TAX_YEAR": 2024,
    "FEE_FIXED_AMOUNT_CENTS": 100000,
}


def create_client_payload(**overrides) -> dict:
    payload = {
        "legal_name": DEFAULTS["CLIENT_LEGAL_NAME"],
        "entity_type": DEFAULTS["ENTITY_TYPE"],
        "marginal_tax_rate": DEFAULTS["MARGINAL_TAX_RATE"],
    }
    payload.update(overrides)
    return payload


def create_property_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "address": DEFAULTS["PROPERTY_ADDRESS"],
        "building_type": DEFAULTS["BUILDING_TYPE"],
        "purchase_price_cents": DEFAULTS["PURCHASE_PRICE_CENTS"],
        "land_value_cents": DEFAULTS["LAND_VALUE_CENTS"],
        "placed_in_service_date": DEFAULTS["PLACED_IN_SERVICE_DATE"],
    }
    payload.update(overrides)
    return payload


def create_engineer_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["ENGINEER_NAME"],
        "email": DEFAULTS["ENGINEER_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_study_payload(client_id, study_type="COST_SEGREGATION", **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "study_type": study_type,
        "tax_year": DEFAULTS["TAX_YEAR"],
    }
    payload.update(overrides)
    return payload


def scope_cost_seg_payload(property_id, fee_type="FIXED", **overrides) -> dict:
    payload = {"fee_type": fee_type, "property_id": property_id}
    if fee_type == "FIXED":
        payload["fee_fixed_amount_cents"] = DEFAULTS["FEE_FIXED_AMOUNT_CENTS"]
    payload.update(overrides)
    return payload


def scope_rd_payload(credit_method="ASC", fee_type="FIXED", **overrides) -> dict:
    payload = {"fee_type": fee_type, "credit_method": credit_method}
    if fee_type == "FIXED":
        payload["fee_fixed_amount_cents"] = DEFAULTS["FEE_FIXED_AMOUNT_CENTS"]
    payload.update(overrides)
    return payload


def asset_component_payload(component_name="Component", asset_class="FIVE_YEAR",
                            allocated_cost_cents=10000000, **overrides) -> dict:
    payload = {
        "component_name": component_name,
        "asset_class": asset_class,
        "allocated_cost_cents": allocated_cost_cents,
    }
    payload.update(overrides)
    return payload


def qre_line_payload(qre_category="WAGES", gross_amount_cents=5000000,
                     qualified_percent=0.80, **overrides) -> dict:
    payload = {
        "qre_category": qre_category,
        "gross_amount_cents": gross_amount_cents,
        "qualified_percent": qualified_percent,
    }
    payload.update(overrides)
    return payload


def amended_return_payload(amended_tax_year, expected_study_version, **overrides) -> dict:
    payload = {
        "amended_tax_year": amended_tax_year,
        "expected_study_version": expected_study_version,
    }
    payload.update(overrides)
    return payload
