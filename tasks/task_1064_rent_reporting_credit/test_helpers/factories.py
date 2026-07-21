"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "TENANT_NAME": "Test Tenant",
    "TENANT_EMAIL": "tenant@example.com",
    "LANDLORD_NAME": "Acme Property Management",
    "LANDLORD_EMAIL": "pm@example.com",
    "PLAN_NAME": "Plus",
    "PLAN_TIER": "PLUS",
    "MONTHLY_FEE_CENTS": 1499,
    "BACK_REPORTING_INCLUDED_MONTHS": 6,
    "PROPERTY_ADDRESS": "1 Main St #2",
    "RENT_AMOUNT_CENTS": 120000,
    "MONTHLY_DUE_DAY": 5,
    "LEASE_START": "2026-01-01T00:00:00Z",
    "LEASE_END": "2027-01-01T00:00:00Z",
}


def create_tenant_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["TENANT_NAME"],
        "email": DEFAULTS["TENANT_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_landlord_payload(**overrides) -> dict:
    payload = {
        "company_name": DEFAULTS["LANDLORD_NAME"],
        "email": DEFAULTS["LANDLORD_EMAIL"],
    }
    payload.update(overrides)
    return payload


def create_plan_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["PLAN_NAME"],
        "tier": DEFAULTS["PLAN_TIER"],
        "monthly_fee_cents": DEFAULTS["MONTHLY_FEE_CENTS"],
        "back_reporting_included_months": DEFAULTS["BACK_REPORTING_INCLUDED_MONTHS"],
    }
    payload.update(overrides)
    return payload


def create_enrollment_payload(tenant_id, plan_id, **overrides) -> dict:
    payload = {"tenant_id": tenant_id, "plan_id": plan_id}
    payload.update(overrides)
    return payload


def create_lease_payload(tenant_id, landlord_id, **overrides) -> dict:
    payload = {
        "tenant_id": tenant_id,
        "landlord_id": landlord_id,
        "property_address": DEFAULTS["PROPERTY_ADDRESS"],
        "rent_amount_cents": DEFAULTS["RENT_AMOUNT_CENTS"],
        "monthly_due_day": DEFAULTS["MONTHLY_DUE_DAY"],
        "lease_start": DEFAULTS["LEASE_START"],
        "lease_end": DEFAULTS["LEASE_END"],
    }
    payload.update(overrides)
    return payload


def create_rent_payment_payload(lease_id, expected_lease_version, **overrides) -> dict:
    payload = {
        "lease_id": lease_id,
        "period_month": "2026-06",
        "due_date": "2026-06-05T00:00:00Z",
        "paid_date": "2026-06-05T00:00:00Z",
        "amount_paid_cents": DEFAULTS["RENT_AMOUNT_CENTS"],
        "expected_lease_version": expected_lease_version,
    }
    payload.update(overrides)
    return payload


def create_dispute_payload(reported_item_id, reason_code="PAID_ON_TIME", **overrides) -> dict:
    payload = {"reported_item_id": reported_item_id, "reason_code": reason_code}
    payload.update(overrides)
    return payload


def create_back_report_payload(lease_id, requested_months, **overrides) -> dict:
    payload = {"lease_id": lease_id, "requested_months": requested_months}
    payload.update(overrides)
    return payload


def create_score_snapshot_payload(tenant_id, bureau="EQUIFAX", score=700, as_of_month="2026-06", **overrides) -> dict:
    payload = {
        "tenant_id": tenant_id,
        "bureau": bureau,
        "score": score,
        "as_of_month": as_of_month,
    }
    payload.update(overrides)
    return payload
