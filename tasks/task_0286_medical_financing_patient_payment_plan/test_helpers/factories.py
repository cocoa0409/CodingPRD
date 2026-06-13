"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "PROVIDER_LEGAL_NAME": "Test Clinic",
    "SPECIALTY": "DENTAL",
    "BASE_RATE": 0.08,
    "PLAN_NAME": "Test Plan",
    "PLAN_CATEGORY": "DEFERRED_INTEREST",
    "DEFERRED_PERIOD_MONTHS": 12,
    "PROMO_APR": 0.2,
    "MIN_PAYMENT_FACTOR": 0.05,
    "APPLICANT_NAME": "Test Applicant",
    "INCOME_CENTS": 6_000_000,
    "REQUESTED_LIMIT_CENTS": 500_000,
    "FUNDING_TOKEN": "tok-test",
    "DRAFT_DAY": 15,
}


def create_provider_payload(**overrides) -> dict:
    """POST /providers — legal_name, specialty, tax_id, base_merchant_discount_rate."""
    defaults = {
        "legal_name": DEFAULTS["PROVIDER_LEGAL_NAME"],
        "specialty": DEFAULTS["SPECIALTY"],
        "tax_id": "TX-TEST-1",
        "base_merchant_discount_rate": DEFAULTS["BASE_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_promotional_plan_payload(**overrides) -> dict:
    """POST /promotional-plans — name, plan_category, deferred_period_months, promo_apr,
    min_payment_factor."""
    defaults = {
        "name": DEFAULTS["PLAN_NAME"],
        "plan_category": DEFAULTS["PLAN_CATEGORY"],
        "deferred_period_months": DEFAULTS["DEFERRED_PERIOD_MONTHS"],
        "promo_apr": DEFAULTS["PROMO_APR"],
        "min_payment_factor": DEFAULTS["MIN_PAYMENT_FACTOR"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_promotion_payload(provider_id, promotional_plan_id, **overrides) -> dict:
    """POST /provider-promotions — provider_id, promotional_plan_id, effective_start,
    effective_end."""
    defaults = {
        "provider_id": provider_id,
        "promotional_plan_id": promotional_plan_id,
        "effective_start": "2026-01-01T00:00:00Z",
        "effective_end": "2028-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_credit_application_payload(**overrides) -> dict:
    """POST /credit-applications — applicant_full_name, applicant_ssn_last4,
    stated_annual_income_cents, requested_limit_cents."""
    defaults = {
        "applicant_full_name": DEFAULTS["APPLICANT_NAME"],
        "applicant_ssn_last4": "0001",
        "stated_annual_income_cents": DEFAULTS["INCOME_CENTS"],
        "requested_limit_cents": DEFAULTS["REQUESTED_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_autopay_enrollment_payload(patient_account_id, **overrides) -> dict:
    """POST /autopay-enrollments — patient_account_id, funding_token, draft_day_of_month."""
    defaults = {
        "patient_account_id": patient_account_id,
        "funding_token": DEFAULTS["FUNDING_TOKEN"],
        "draft_day_of_month": DEFAULTS["DRAFT_DAY"],
    }
    defaults.update(overrides)
    return defaults


def create_financed_purchase_payload(
    provider_id, patient_account_id, provider_promotion_id, principal_cents,
    expected_patient_account_version, **overrides
) -> dict:
    """POST /financed-purchases — provider_id, patient_account_id, provider_promotion_id,
    principal_cents, expected_patient_account_version."""
    defaults = {
        "provider_id": provider_id,
        "patient_account_id": patient_account_id,
        "provider_promotion_id": provider_promotion_id,
        "principal_cents": principal_cents,
        "expected_patient_account_version": expected_patient_account_version,
    }
    defaults.update(overrides)
    return defaults


def settle_payload(expected_financed_purchase_version, **overrides) -> dict:
    """POST /financed-purchases/{id}/settle — expected_financed_purchase_version."""
    defaults = {"expected_financed_purchase_version": expected_financed_purchase_version}
    defaults.update(overrides)
    return defaults


def create_payment_payload(patient_account_id, amount_cents, payment_type, **overrides) -> dict:
    """POST /payments — patient_account_id, amount_cents, payment_type."""
    defaults = {
        "patient_account_id": patient_account_id,
        "amount_cents": amount_cents,
        "payment_type": payment_type,
    }
    defaults.update(overrides)
    return defaults


def create_refund_payload(financed_purchase_id, refund_kind, amount_cents, **overrides) -> dict:
    """POST /refunds — financed_purchase_id, refund_kind, amount_cents."""
    defaults = {
        "financed_purchase_id": financed_purchase_id,
        "refund_kind": refund_kind,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def open_statement_payload(patient_account_id, period_start, period_end, **overrides) -> dict:
    """POST /_cycle/open_statement — patient_account_id, period_start, period_end."""
    defaults = {
        "patient_account_id": patient_account_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    defaults.update(overrides)
    return defaults
