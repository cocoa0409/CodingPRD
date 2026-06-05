"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CENTER_NAME": "Test Center",
    "CACFP_TIER": "TIER_I",
    "CLASSROOM_NAME": "Test Room",
    "AGE_BAND": "TODDLER",
    "LICENSED_CAPACITY": 5,
    "BASE_TUITION_CENTS": 120000,
    "CONTACT_NAME": "Test Parent",
    "INCOME_CENTS": 9999999,
    "HOUSEHOLD_SIZE": 2,
    "CHILD_NAME": "Test Child",
    "BIRTHDATE": "2024-01-10",
    "BILLING_MONTH": "2026-03",
    "PAYMENT_METHOD": "ACH",
}


def create_center_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CENTER_NAME"],
        "cacfp_tier": DEFAULTS["CACFP_TIER"],
    }
    defaults.update(overrides)
    return defaults


def create_sliding_scale_payload(tier, max_fpl_ratio_pct, parent_share_pct, **overrides) -> dict:
    defaults = {
        "tier": tier,
        "max_fpl_ratio_pct": max_fpl_ratio_pct,
        "parent_share_pct": parent_share_pct,
    }
    defaults.update(overrides)
    return defaults


def create_classroom_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CLASSROOM_NAME"],
        "age_band": DEFAULTS["AGE_BAND"],
        "licensed_capacity": DEFAULTS["LICENSED_CAPACITY"],
        "base_monthly_tuition_cents": DEFAULTS["BASE_TUITION_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_family_payload(center_id, **overrides) -> dict:
    defaults = {
        "center_id": center_id,
        "primary_contact_name": DEFAULTS["CONTACT_NAME"],
        "annual_household_income_cents": DEFAULTS["INCOME_CENTS"],
        "household_size": DEFAULTS["HOUSEHOLD_SIZE"],
    }
    defaults.update(overrides)
    return defaults


def create_child_payload(family_id, **overrides) -> dict:
    defaults = {
        "family_id": family_id,
        "full_name": DEFAULTS["CHILD_NAME"],
        "birthdate": DEFAULTS["BIRTHDATE"],
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_payload(child_id, **overrides) -> dict:
    defaults = {"child_id": child_id}
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(child_id, classroom_id, expected_classroom_version, **overrides) -> dict:
    defaults = {
        "child_id": child_id,
        "classroom_id": classroom_id,
        "expected_classroom_version": expected_classroom_version,
    }
    defaults.update(overrides)
    return defaults


def create_attendance_payload(enrollment_id, service_date, scheduled_pickup_local, **overrides) -> dict:
    defaults = {
        "enrollment_id": enrollment_id,
        "service_date": service_date,
        "scheduled_pickup_local": scheduled_pickup_local,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(billing_month=None, **overrides) -> dict:
    defaults = {"billing_month": billing_month or DEFAULTS["BILLING_MONTH"]}
    defaults.update(overrides)
    return defaults


def create_payment_payload(invoice_id, amount_cents, expected_invoice_version, **overrides) -> dict:
    defaults = {
        "invoice_id": invoice_id,
        "amount_cents": amount_cents,
        "method": DEFAULTS["PAYMENT_METHOD"],
        "expected_invoice_version": expected_invoice_version,
    }
    defaults.update(overrides)
    return defaults


def create_tax_statement_payload(tax_year, **overrides) -> dict:
    defaults = {"tax_year": tax_year}
    defaults.update(overrides)
    return defaults
