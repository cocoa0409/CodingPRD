"""Payload factories — one per entity, input fields only (PRD section 3 narrative).

Defaults mirror the canonical ON_47 on-premise class used throughout the design
recipes: base_fee_cents 100000, requires_zoning true, quota_managed true.
"""


# ─── Configuration ───────────────────────────────────────────────────────
def create_license_class_payload(**overrides) -> dict:
    """Required: code, premise_type, base_fee_cents, renewal_cycle_months,
    max_servers_per_license. Optional (defaulted server-side): quota_managed,
    requires_zoning (both default true)."""
    defaults = {
        "code": "ON_47",
        "premise_type": "ON_PREMISE",
        "quota_managed": True,
        "base_fee_cents": 100000,
        "renewal_cycle_months": 12,
        "requires_zoning": True,
        "max_servers_per_license": 5,
    }
    defaults.update(overrides)
    return defaults


def create_quota_region_payload(**overrides) -> dict:
    """Required: region_code, population, persons_per_license. Optional: moratorium."""
    defaults = {
        "region_code": "CTY_LA",
        "population": 50000,
        "persons_per_license": 25000,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    """Required: legal_name. Optional: felony_flag (defaults false)."""
    defaults = {
        "legal_name": "Acme Bar LLC",
    }
    defaults.update(overrides)
    return defaults


def create_premise_payload(**overrides) -> dict:
    """Required: applicant_id, region_code, street_address, distance_to_school_m,
    zoning_district."""
    defaults = {
        "region_code": "CTY_LA",
        "street_address": "1 Main St",
        "distance_to_school_m": 200,
        "zoning_district": "COMMERCIAL",
    }
    defaults.update(overrides)
    return defaults


# ─── Application & children ──────────────────────────────────────────────
def create_application_payload(**overrides) -> dict:
    """Required: applicant_id, premise_id, license_class_code."""
    defaults = {
        "license_class_code": "ON_47",
    }
    defaults.update(overrides)
    return defaults


def create_protest_payload(**overrides) -> dict:
    """Required: application_id, protester_name, grounds."""
    defaults = {
        "protester_name": "Neighbor Assoc",
        "grounds": "OVER_CONCENTRATION",
    }
    defaults.update(overrides)
    return defaults


# ─── Server permits ──────────────────────────────────────────────────────
def create_server_permit_payload(**overrides) -> dict:
    """Required: license_id, holder_name. Optional: training_completed (default false)."""
    defaults = {
        "holder_name": "Bartender A",
        "training_completed": True,
    }
    defaults.update(overrides)
    return defaults


# ─── Violations ──────────────────────────────────────────────────────────
def create_violation_payload(**overrides) -> dict:
    """Required: license_id, severity."""
    defaults = {
        "severity": "SERIOUS",
    }
    defaults.update(overrides)
    return defaults


# ─── Compliance reports ──────────────────────────────────────────────────
def create_compliance_report_payload(**overrides) -> dict:
    """Required: license_id, tier, period_code, gross_sales_cents."""
    defaults = {
        "tier": "RETAILER",
        "period_code": "2026-Q1",
        "gross_sales_cents": 6000000,
    }
    defaults.update(overrides)
    return defaults


# ─── Transfer requests ───────────────────────────────────────────────────
def create_transfer_request_payload(**overrides) -> dict:
    """Required: license_id, transfer_type. Conditional: new_applicant_id (OWNERSHIP)
    / new_premise_id (LOCATION)."""
    defaults = {
        "transfer_type": "LOCATION",
    }
    defaults.update(overrides)
    return defaults
