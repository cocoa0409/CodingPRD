"""Payload factories — one per creatable resource, input fields only (PRD 3.x)."""

DEFAULTS = {
    "PROPERTY_NAME": "Maple Court",
    "STATE_CODE": "CA",
    "TENANT_NAME": "Terry Tenant",
    "TENANT_EMAIL": "terry@example.com",
    "UNIT_LABEL": "101",
    "MONTHLY_RENT_CENTS": 200000,
    "DUE_DAY": 1,
    "GRACE_PERIOD_DAYS": 5,
    "TERM_START": "2026-08-01",
    "TERM_END": "2027-07-31",
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2026-08-31",
    "DUE_DATE": "2026-08-01",
    "RENT_AMOUNT": 200000,
    "FIRST_INSTALLMENT_DATE": "2026-08-15",
}


def create_property_payload(**overrides) -> dict:
    """All 12 policy constants per PRD 3.1; defaults mirror the canonical test property."""
    defaults = {
        "name": DEFAULTS["PROPERTY_NAME"],
        "state_code": DEFAULTS["STATE_CODE"],
        "posting_priority_policy": "FEES_FIRST",
        "late_fee_cap_cents": 5000,
        "nsf_fee_cap_cents": 3500,
        "monthly_waiver_cap_cents": 20000,
        "min_partial_payment_percent": 25,
        "collections_threshold_cents": 10000,
        "notice_cure_period_days": 10,
        "plan_cooling_off_days": 30,
        "plan_setup_fee_cents": 2500,
        "plan_setup_fee_threshold_cents": 20000,
    }
    defaults.update(overrides)
    return defaults


def create_tenant_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["TENANT_NAME"],
        "email": DEFAULTS["TENANT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(property_id: str, primary_tenant_id: str, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "primary_tenant_id": primary_tenant_id,
        "unit_label": DEFAULTS["UNIT_LABEL"],
        "monthly_rent_cents": DEFAULTS["MONTHLY_RENT_CENTS"],
        "due_day": DEFAULTS["DUE_DAY"],
        "grace_period_days": DEFAULTS["GRACE_PERIOD_DAYS"],
        "late_fee_type": "FLAT",
        "late_fee_flat_cents": 4000,
        "term_start_date": DEFAULTS["TERM_START"],
        "term_end_date": DEFAULTS["TERM_END"],
    }
    defaults.update(overrides)
    return defaults


def create_charge_payload(**overrides) -> dict:
    defaults = {
        "kind": "RENT",
        "period_start_date": DEFAULTS["PERIOD_START"],
        "period_end_date": DEFAULTS["PERIOD_END"],
        "due_date": DEFAULTS["DUE_DATE"],
        "amount_cents": DEFAULTS["RENT_AMOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(lease_id: str, tenant_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "tenant_id": tenant_id,
        "channel": "CARD",
        "amount_cents": DEFAULTS["RENT_AMOUNT"],
        "received_date": DEFAULTS["DUE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_notice_payload(lease_id: str, charge_ids, expected_lease_version: int, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "charge_ids": list(charge_ids),
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(lease_id: str, charge_ids, expected_lease_version: int, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "charge_ids": list(charge_ids),
        "installment_count": 2,
        "first_installment_date": DEFAULTS["FIRST_INSTALLMENT_DATE"],
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(lease_id: str, charge_id: str, tenant_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "charge_id": charge_id,
        "tenant_id": tenant_id,
        "reason": "contested",
    }
    defaults.update(overrides)
    return defaults
