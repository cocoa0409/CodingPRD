"""Payload factories — one per entity, input fields only.

Only ``source: input`` fields appear here. Optional fields with documented
PRD defaults are omitted from the defaults and supplied only via overrides,
so factories double as the basis for required-vs-optional field tests.
"""


def create_property_payload(**overrides) -> dict:
    """Required: name, total_rentable_sqft. Optional: gross_up_occupancy_pct."""
    defaults = {
        "name": "Test Property",
        "total_rentable_sqft": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    """Required: legal_name, contact_email."""
    defaults = {
        "legal_name": "Test Tenant LLC",
        "contact_email": "tenant@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_expense_pool_payload(property_id, **overrides) -> dict:
    """Required: property_id, pool_year. Optional: pro_rata_denominator, admin_fee_pct."""
    defaults = {
        "property_id": property_id,
        "pool_year": 2025,
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(**overrides) -> dict:
    """Required: category, amount_cents. Optional: recoverability, is_variable."""
    defaults = {
        "category": "UTILITIES",
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(property_id, tenant_id, **overrides) -> dict:
    """Required: property_id, tenant_id, leased_sqft, base_rent_cents_annual.

    All pricing levers are optional with PRD defaults and are passed via overrides.
    """
    defaults = {
        "property_id": property_id,
        "tenant_id": tenant_id,
        "leased_sqft": 1000,
        "base_rent_cents_annual": 0,
    }
    defaults.update(overrides)
    return defaults


def create_sales_report_payload(lease_id, **overrides) -> dict:
    """Required: lease_id, period_year, gross_sales_cents."""
    defaults = {
        "lease_id": lease_id,
        "period_year": 2025,
        "gross_sales_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_ti_draw_payload(lease_id, **overrides) -> dict:
    """Required: lease_id, amount_cents."""
    defaults = {
        "lease_id": lease_id,
        "amount_cents": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(lease_id, pool_id, recon_year=2025, **overrides) -> dict:
    """Required: lease_id, pool_id, recon_year."""
    defaults = {
        "lease_id": lease_id,
        "pool_id": pool_id,
        "recon_year": recon_year,
    }
    defaults.update(overrides)
    return defaults


def create_estoppel_payload(lease_id, asserted_balance_cents=0,
                            asserted_base_rent_cents_annual=0, **overrides) -> dict:
    """Required: lease_id, asserted_balance_cents, asserted_base_rent_cents_annual."""
    defaults = {
        "lease_id": lease_id,
        "asserted_balance_cents": asserted_balance_cents,
        "asserted_base_rent_cents_annual": asserted_base_rent_cents_annual,
    }
    defaults.update(overrides)
    return defaults
