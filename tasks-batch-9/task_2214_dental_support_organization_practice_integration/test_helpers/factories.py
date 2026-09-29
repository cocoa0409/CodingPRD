"""Payload factories — one per resource, request-input fields only."""

from .constants import TEST_DEFAULTS


def create_affiliation_payload(**overrides) -> dict:
    payload = {
        "seller_group_name": TEST_DEFAULTS["SELLER_GROUP_NAME"],
        "purchase_price_cents": TEST_DEFAULTS["PURCHASE_PRICE_CENTS"],
        "earnout_pool_cents": TEST_DEFAULTS["EARNOUT_POOL_CENTS"],
        "baseline_ebitda_cents": TEST_DEFAULTS["BASELINE_EBITDA_CENTS"],
        "baseline_net_collections_cents": TEST_DEFAULTS[
            "BASELINE_NET_COLLECTIONS_CENTS"
        ],
        "post_close_doctor_term_months": TEST_DEFAULTS[
            "POST_CLOSE_DOCTOR_TERM_MONTHS"
        ],
    }
    payload.update(overrides)
    return payload


def create_conversion_vendor_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["VENDOR_NAME"],
        "max_concurrent_windows": TEST_DEFAULTS["VENDOR_MAX_CONCURRENT_WINDOWS"],
    }
    payload.update(overrides)
    return payload


def create_practice_payload(affiliation_id, conversion_vendor_id, **overrides) -> dict:
    payload = {
        "affiliation_id": affiliation_id,
        "conversion_vendor_id": conversion_vendor_id,
        "name": TEST_DEFAULTS["PRACTICE_NAME"],
        "state_code": TEST_DEFAULTS["PRACTICE_STATE_CODE"],
        "charts_total_expected": TEST_DEFAULTS["CHARTS_TOTAL_EXPECTED"],
    }
    payload.update(overrides)
    return payload


def create_doctor_payload(**overrides) -> dict:
    payload = {
        "full_name": TEST_DEFAULTS["DOCTOR_FULL_NAME"],
        "npi": TEST_DEFAULTS["DOCTOR_NPI"],
        "license_number": TEST_DEFAULTS["DOCTOR_LICENSE_NUMBER"],
        "license_state": TEST_DEFAULTS["PRACTICE_STATE_CODE"],
        "specialty": "GENERAL",
        "is_seller_owner": True,
    }
    payload.update(overrides)
    return payload


def create_doctor_employment_payload(practice_id, doctor_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "doctor_id": doctor_id,
        "base_salary_monthly_cents": TEST_DEFAULTS["BASE_SALARY_MONTHLY_CENTS"],
        "collections_pct_bps": TEST_DEFAULTS["COLLECTIONS_PCT_BPS"],
        "comp_model": "MONTHLY_MIN_GUARANTEE",
        "legacy_annual_comp_cents": TEST_DEFAULTS["LEGACY_ANNUAL_COMP_CENTS"],
        "post_close_term_months": TEST_DEFAULTS["POST_CLOSE_TERM_MONTHS"],
        "non_compete_months": TEST_DEFAULTS["NON_COMPETE_MONTHS"],
        "non_compete_radius_miles": TEST_DEFAULTS["NON_COMPETE_RADIUS_MILES"],
    }
    payload.update(overrides)
    return payload


def create_service_agreement_payload(practice_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "fee_model": "PCT_OF_COLLECTIONS",
        "mgmt_fee_bps": TEST_DEFAULTS["MGMT_FEE_BPS"],
    }
    payload.update(overrides)
    return payload


def create_service_line_item_payload(**overrides) -> dict:
    payload = {
        "service_code": TEST_DEFAULTS["SERVICE_CODE"],
        "service_domain": TEST_DEFAULTS["SERVICE_DOMAIN"],
        "monthly_fee_cents": TEST_DEFAULTS["MONTHLY_FEE_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_migration_batch_payload(
    practice_id, expected_practice_version, **overrides
) -> dict:
    payload = {
        "practice_id": practice_id,
        "batch_label": "CHART-WAVE-1",
        "records_total": TEST_DEFAULTS["CHARTS_TOTAL_EXPECTED"],
        "expected_practice_version": expected_practice_version,
    }
    payload.update(overrides)
    return payload


def schedule_cutover_payload(cutover_start_at, cutover_end_at, **overrides) -> dict:
    payload = {
        "cutover_start_at": cutover_start_at,
        "cutover_end_at": cutover_end_at,
    }
    payload.update(overrides)
    return payload


def create_payer_contract_payload(practice_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "payer_name": TEST_DEFAULTS["PAYER_NAME"],
    }
    payload.update(overrides)
    return payload


def create_fee_schedule_item_payload(**overrides) -> dict:
    payload = {
        "procedure_code": TEST_DEFAULTS["PROCEDURE_CODE"],
        "legacy_allowed_cents": TEST_DEFAULTS["LEGACY_ALLOWED_CENTS"],
        "dso_allowed_cents": TEST_DEFAULTS["DSO_ALLOWED_CENTS"],
        "annual_volume": TEST_DEFAULTS["ANNUAL_VOLUME"],
    }
    payload.update(overrides)
    return payload


def create_payer_enrollment_payload(
    payer_contract_id, doctor_employment_id, effective_date, **overrides
) -> dict:
    payload = {
        "payer_contract_id": payer_contract_id,
        "doctor_employment_id": doctor_employment_id,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def create_earnout_tranche_payload(
    affiliation_id,
    expected_affiliation_version,
    period_label="EO-Y1",
    measurement_start="2026-09-01T00:00:00Z",
    measurement_end="2027-09-01T00:00:00Z",
    **overrides,
) -> dict:
    payload = {
        "affiliation_id": affiliation_id,
        "period_label": period_label,
        "measurement_start": measurement_start,
        "measurement_end": measurement_end,
        "expected_affiliation_version": expected_affiliation_version,
    }
    payload.update(overrides)
    return payload


def create_supply_preference_exception_payload(doctor_employment_id, **overrides) -> dict:
    payload = {
        "doctor_employment_id": doctor_employment_id,
        "vendor_category": "SUPPLY",
        "item_code": "CMP-2200",
        "annual_qty": 340,
        "formulary_unit_cents": 1275,
        "preferred_unit_cents": 1899,
        "clinical_rationale": "shade matching on anterior composites",
    }
    payload.update(overrides)
    return payload


def create_vendor_consolidation_payload(practice_id, **overrides) -> dict:
    payload = {
        "practice_id": practice_id,
        "vendor_category": "SUPPLY",
        "baseline_annual_spend_cents": 4_100_000,
        "formulary_annual_spend_cents": 3_200_000,
    }
    payload.update(overrides)
    return payload


def create_clinical_quality_review_payload(doctor_employment_id, **overrides) -> dict:
    payload = {
        "doctor_employment_id": doctor_employment_id,
        "period_label": "QR-2026-Q4",
        "charts_sampled": 20,
        "charts_with_findings": 5,
        "treatment_plan_overrides": 5,
    }
    payload.update(overrides)
    return payload


def monthly_collections_series(*values) -> list:
    """A twelve-entry `monthly_collections_cents` array, month one first."""
    series = list(values)
    assert len(series) == 12, "monthly_collections_cents must hold exactly twelve entries"
    return series


__all__ = [
    "create_affiliation_payload",
    "create_conversion_vendor_payload",
    "create_practice_payload",
    "create_doctor_payload",
    "create_doctor_employment_payload",
    "create_service_agreement_payload",
    "create_service_line_item_payload",
    "create_migration_batch_payload",
    "schedule_cutover_payload",
    "create_payer_contract_payload",
    "create_fee_schedule_item_payload",
    "create_payer_enrollment_payload",
    "create_earnout_tranche_payload",
    "create_supply_preference_exception_payload",
    "create_vendor_consolidation_payload",
    "create_clinical_quality_review_payload",
    "monthly_collections_series",
]
