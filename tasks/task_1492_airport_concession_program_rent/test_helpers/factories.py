"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "LEGAL_NAME": "SkyEats LLC",
    "CONTACT_EMAIL": "ops@skyeats.com",
    "PREMISES_CODE": "A1",
    "CATEGORY": "FOOD",
    "TERM_START_DATE": "2026-01-01",
    "TERM_END_DATE": "2030-12-31",
    "MAG_ANNUAL_CENTS": 1_200_000,
    "PCT_RATE_BELOW_BP": 800,
    "PCT_BREAKPOINT_CENTS": 500_000,
    "PCT_RATE_ABOVE_BP": 1000,
    "ACDBE_GOAL_BP": 2000,
    "TI_ALLOWANCE_CENTS": 500_000,
    "BUILDOUT_DEADLINE": "2026-09-30",
    "MIN_SPE_CENTS": 1000,
    "PERIOD_YEAR": 2026,
    "PAYMENT_METHOD": "ACH",
    "DRAW_MILESTONE": "DESIGN",
    "WAIVER_REASON": "renovation",
}


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(tenant_id: str, **overrides) -> dict:
    defaults = {
        "tenant_id": tenant_id,
        "premises_code": DEFAULTS["PREMISES_CODE"],
        "category": DEFAULTS["CATEGORY"],
        "term_start_date": DEFAULTS["TERM_START_DATE"],
        "term_end_date": DEFAULTS["TERM_END_DATE"],
        "mag_annual_cents": DEFAULTS["MAG_ANNUAL_CENTS"],
        "pct_rate_below_bp": DEFAULTS["PCT_RATE_BELOW_BP"],
        "pct_breakpoint_cents": DEFAULTS["PCT_BREAKPOINT_CENTS"],
        "pct_rate_above_bp": DEFAULTS["PCT_RATE_ABOVE_BP"],
        "acdbe_goal_bp": DEFAULTS["ACDBE_GOAL_BP"],
        "ti_allowance_cents": DEFAULTS["TI_ALLOWANCE_CENTS"],
        "buildout_deadline": DEFAULTS["BUILDOUT_DEADLINE"],
        "min_spe_cents": DEFAULTS["MIN_SPE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_sales_report_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "period_month": "2026-01",
        "gross_sales_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "period_year": DEFAULTS["PERIOD_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 100_000,
        "method": DEFAULTS["PAYMENT_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_audit_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "period_start_month": "2026-01",
        "period_end_month": "2026-03",
    }
    defaults.update(overrides)
    return defaults


def create_acdbe_review_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "period_year": DEFAULTS["PERIOD_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_ti_draw_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "amount_cents": 100_000,
        "milestone": DEFAULTS["DRAW_MILESTONE"],
    }
    defaults.update(overrides)
    return defaults


def create_violation_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "kind": "OPERATING_HOURS",
        "observed_date": "2026-08-03",
        "shortfall_minutes": 45,
    }
    defaults.update(overrides)
    return defaults


def create_waiver_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "closure_start_date": "2026-10-01",
        "closure_end_date": "2026-10-05",
        "reason": DEFAULTS["WAIVER_REASON"],
    }
    defaults.update(overrides)
    return defaults


def create_enplanement_snapshot_payload(**overrides) -> dict:
    defaults = {
        "month": "2026-06",
        "enplanements": 100_000,
    }
    defaults.update(overrides)
    return defaults
