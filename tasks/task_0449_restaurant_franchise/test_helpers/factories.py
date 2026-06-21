"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Required vs optional follows the PRD §3 narratives:
factories supply all REQUIRED input fields by default and let tests override or add
optional fields via **overrides. Optional fields (those PRD marks with a default or
calls optional) are NOT supplied unless overridden, so the server applies its own
defaults.
"""

DEFAULTS = {
    "BRAND_NAME": "Test Brand",
    "TERRITORY_CODE": "T1",
    "TERRITORY_NAME": "Test Territory",
    "FRANCHISEE_LEGAL_NAME": "Test Franchisee LLC",
    "OWNER_USER_ID": "u_owner",
    "FDD_VERSION": "2026.1",
    "UNIT_ADDRESS": "1 Main St",
    "VENDOR_NAME": "Test Vendor",
    "VENDOR_CATEGORY": "FOOD",
    "NATIONAL_ACCOUNT_NAME": "Test Rebate Program",
}


# ─── Brand ───────────────────────────────────────────────────────────────────
def create_brand_payload(**overrides) -> dict:
    """POST /franchise/brands. Required: name. Optional (server defaults apply):
    royalty_tier_1_rate, royalty_tier_2_rate, royalty_tier_3_rate, ad_fund_rate,
    late_fee_monthly_rate."""
    payload = {"name": DEFAULTS["BRAND_NAME"]}
    payload.update(overrides)
    return payload


# ─── Territory ───────────────────────────────────────────────────────────────
def create_territory_payload(brand_id: str, **overrides) -> dict:
    """POST /franchise/territories. Required: brand_id, code, name. Optional:
    protected (default true)."""
    payload = {
        "brand_id": brand_id,
        "code": DEFAULTS["TERRITORY_CODE"],
        "name": DEFAULTS["TERRITORY_NAME"],
    }
    payload.update(overrides)
    return payload


def assign_territory_payload(franchisee_id: str, **overrides) -> dict:
    """POST /franchise/territories/{id}/assign. Required: franchisee_id."""
    payload = {"franchisee_id": franchisee_id}
    payload.update(overrides)
    return payload


# ─── Franchisee ──────────────────────────────────────────────────────────────
def create_franchisee_payload(brand_id: str, **overrides) -> dict:
    """POST /franchise/franchisees. Required: brand_id, legal_name, owner_user_id.
    Optional: is_existing_operator (default false)."""
    payload = {
        "brand_id": brand_id,
        "legal_name": DEFAULTS["FRANCHISEE_LEGAL_NAME"],
        "owner_user_id": DEFAULTS["OWNER_USER_ID"],
    }
    payload.update(overrides)
    return payload


# ─── FranchiseAgreement ──────────────────────────────────────────────────────
def create_agreement_payload(
    franchisee_id: str, term_end_period_index: int, **overrides
) -> dict:
    """POST /franchise/agreements. Required: franchisee_id, fdd_version,
    term_end_period_index. Optional: transfer_fee_rate (default 0.02)."""
    payload = {
        "franchisee_id": franchisee_id,
        "fdd_version": DEFAULTS["FDD_VERSION"],
        "term_end_period_index": term_end_period_index,
    }
    payload.update(overrides)
    return payload


def renew_agreement_payload(
    new_fdd_version: str, new_term_end_period_index: int, **overrides
) -> dict:
    """POST /franchise/agreements/{id}/renew. Required: new_fdd_version,
    new_term_end_period_index."""
    payload = {
        "new_fdd_version": new_fdd_version,
        "new_term_end_period_index": new_term_end_period_index,
    }
    payload.update(overrides)
    return payload


def transfer_agreement_payload(buyer_franchisee_id: str, **overrides) -> dict:
    """POST /franchise/agreements/{id}/transfer. Required: buyer_franchisee_id."""
    payload = {"buyer_franchisee_id": buyer_franchisee_id}
    payload.update(overrides)
    return payload


# ─── DevelopmentSchedule ─────────────────────────────────────────────────────
def create_development_schedule_payload(
    franchisee_id: str, required_units: int, deadline_period_index: int, **overrides
) -> dict:
    """POST /franchise/development-schedules. Required: franchisee_id,
    required_units, deadline_period_index."""
    payload = {
        "franchisee_id": franchisee_id,
        "required_units": required_units,
        "deadline_period_index": deadline_period_index,
    }
    payload.update(overrides)
    return payload


# ─── Unit ────────────────────────────────────────────────────────────────────
def create_unit_payload(franchisee_id: str, territory_id: str, **overrides) -> dict:
    """POST /franchise/units. Required: franchisee_id, territory_id, address."""
    payload = {
        "franchisee_id": franchisee_id,
        "territory_id": territory_id,
        "address": DEFAULTS["UNIT_ADDRESS"],
    }
    payload.update(overrides)
    return payload


# ─── SalesReport ─────────────────────────────────────────────────────────────
def create_sales_report_payload(
    unit_id: str, period_index: int, gross_sales_cents: int, **overrides
) -> dict:
    """POST /franchise/sales-reports. Required: unit_id, period_index,
    gross_sales_cents. Optional: discounts_cents (default 0), source
    (default POS_POLL)."""
    payload = {
        "unit_id": unit_id,
        "period_index": period_index,
        "gross_sales_cents": gross_sales_cents,
    }
    payload.update(overrides)
    return payload


# ─── RoyaltyStatement ────────────────────────────────────────────────────────
def create_royalty_statement_payload(
    unit_id: str, period_index: int, **overrides
) -> dict:
    """POST /franchise/royalty-statements. Required: unit_id, period_index."""
    payload = {"unit_id": unit_id, "period_index": period_index}
    payload.update(overrides)
    return payload


def payment_payload(amount_cents: int, **overrides) -> dict:
    """POST /franchise/royalty-statements/{id}/payments. Required: amount_cents."""
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def write_off_payload(expected_brand_version: int, **overrides) -> dict:
    """POST /franchise/royalty-statements/{id}/write-off. Required:
    expected_brand_version (OCC on Brand.version, §2.8)."""
    payload = {"expected_brand_version": expected_brand_version}
    payload.update(overrides)
    return payload


# ─── Vendor ──────────────────────────────────────────────────────────────────
def create_vendor_payload(brand_id: str, **overrides) -> dict:
    """POST /franchise/vendors. Required: brand_id, name, category."""
    payload = {
        "brand_id": brand_id,
        "name": DEFAULTS["VENDOR_NAME"],
        "category": DEFAULTS["VENDOR_CATEGORY"],
    }
    payload.update(overrides)
    return payload


# ─── VendorAuthorization ─────────────────────────────────────────────────────
def create_vendor_authorization_payload(
    unit_id: str, vendor_id: str, **overrides
) -> dict:
    """POST /franchise/vendor-authorizations. Required: unit_id, vendor_id.
    Optional: qualifying_purchase_cents (default 0)."""
    payload = {"unit_id": unit_id, "vendor_id": vendor_id}
    payload.update(overrides)
    return payload


# ─── BrandAudit ──────────────────────────────────────────────────────────────
def create_audit_payload(unit_id: str, **overrides) -> dict:
    """POST /franchise/audits. Required: unit_id."""
    payload = {"unit_id": unit_id}
    payload.update(overrides)
    return payload


def finalize_audit_payload(
    food_safety_score: int,
    cleanliness_score: int,
    service_score: int,
    brand_compliance_score: int,
    **overrides,
) -> dict:
    """POST /franchise/audits/{id}/finalize. Required: food_safety_score,
    cleanliness_score, service_score, brand_compliance_score (each int 0..100)."""
    payload = {
        "food_safety_score": food_safety_score,
        "cleanliness_score": cleanliness_score,
        "service_score": service_score,
        "brand_compliance_score": brand_compliance_score,
    }
    payload.update(overrides)
    return payload


# ─── NationalAccount ─────────────────────────────────────────────────────────
def create_national_account_payload(
    brand_id: str, vendor_id: str, rebate_pool_cents: int, **overrides
) -> dict:
    """POST /franchise/national-accounts. Required: brand_id, vendor_id, name,
    rebate_pool_cents. Optional: min_qualifying_cents (default 1,000,000)."""
    payload = {
        "brand_id": brand_id,
        "vendor_id": vendor_id,
        "name": DEFAULTS["NATIONAL_ACCOUNT_NAME"],
        "rebate_pool_cents": rebate_pool_cents,
    }
    payload.update(overrides)
    return payload


def distribute_payload(expected_brand_version: int, **overrides) -> dict:
    """POST /franchise/national-accounts/{id}/distribute. Required:
    expected_brand_version (OCC on Brand.version, §2.8)."""
    payload = {"expected_brand_version": expected_brand_version}
    payload.update(overrides)
    return payload
