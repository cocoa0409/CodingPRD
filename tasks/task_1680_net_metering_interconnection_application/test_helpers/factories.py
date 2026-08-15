"""Payload factories — one per creatable resource, input fields only."""

from .constants import (
    STANDARD_EXPORT_RATE,
    STANDARD_IMPORT_RATE,
    STANDARD_NET_SURPLUS_RATE,
    STANDARD_TARIFF_EFFECTIVE_FROM,
    TEST_DEFAULTS,
)


def create_program_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Program",
        "aggregate_cap_watts": TEST_DEFAULTS["PROGRAM_CAP_WATTS"],
        "metering_variant": "MONETARY_CREDIT",
        "true_up_mode": "AVOIDED_COST_PAYOUT",
        "true_up_month": TEST_DEFAULTS["TRUE_UP_MONTH"],
        "screening_basis": "COMMITTED",
    }
    defaults.update(overrides)
    return defaults


def create_tariff_schedule_payload(program_id, **overrides) -> dict:
    defaults = {
        "program_id": program_id,
        "schedule_code": "T-2026",
        "effective_from": STANDARD_TARIFF_EFFECTIVE_FROM,
        "import_rate_millicents_per_kwh": STANDARD_IMPORT_RATE,
        "export_rate_millicents_per_kwh": STANDARD_EXPORT_RATE,
        "net_surplus_rate_millicents_per_kwh": STANDARD_NET_SURPLUS_RATE,
    }
    defaults.update(overrides)
    return defaults


def create_feeder_payload(**overrides) -> dict:
    defaults = {
        "feeder_code": "F-1",
        "peak_load_watts": TEST_DEFAULTS["FEEDER_PEAK_WATTS"],
        "pre_existing_der_watts": 0,
    }
    defaults.update(overrides)
    return defaults


def create_service_transformer_payload(feeder_id, **overrides) -> dict:
    defaults = {
        "feeder_id": feeder_id,
        "transformer_code": "T-1",
        "nameplate_watts": TEST_DEFAULTS["TRANSFORMER_NAMEPLATE_WATTS"],
        "pre_existing_der_watts": 0,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Customer",
        "email": "customer@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_service_account_payload(customer_id, transformer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "transformer_id": transformer_id,
        "account_number": "ACCT-1",
        "service_class": "COMMERCIAL",
        "prior_annual_usage_wh": TEST_DEFAULTS["PRIOR_ANNUAL_USAGE_WH"],
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(service_account_id, program_id, **overrides) -> dict:
    defaults = {
        "service_account_id": service_account_id,
        "program_id": program_id,
        "technology": "SOLAR_PV",
        "system_size_watts_ac": TEST_DEFAULTS["SYSTEM_SIZE_WATTS"],
        "estimated_annual_production_wh":
            TEST_DEFAULTS["ESTIMATED_ANNUAL_PRODUCTION_WH"],
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "doc_type": "SITE_PLAN",
        "title": "Document",
    }
    defaults.update(overrides)
    return defaults


def review_document_payload(**overrides) -> dict:
    defaults = {"outcome": "ACCEPTED"}
    defaults.update(overrides)
    return defaults


def completeness_decision_payload(**overrides) -> dict:
    defaults = {"outcome": "COMPLETE"}
    defaults.update(overrides)
    return defaults


def amend_application_payload(**overrides) -> dict:
    return dict(overrides)


def create_screening_report_payload(application_id, **overrides) -> dict:
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_supplemental_review_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "review_type": "FACILITIES_STUDY",
    }
    defaults.update(overrides)
    return defaults


def complete_supplemental_review_payload(**overrides) -> dict:
    defaults = {"outcome": "CLEARED"}
    defaults.update(overrides)
    return defaults


def create_cost_estimate_payload(application_id, supplemental_review_id,
                                 expected_application_version, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "supplemental_review_id": supplemental_review_id,
        "expected_application_version": expected_application_version,
        "items": [{"description": "Upgrade work", "amount_cents": 50_000}],
        "contingency_pct": 10,
    }
    defaults.update(overrides)
    return defaults


def create_meter_exchange_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "crew_id": "crew-1",
        "window_start": "2026-08-03T09:00:00Z",
        "window_end": "2026-08-03T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(application_id, **overrides) -> dict:
    defaults = {
        "application_id": application_id,
        "scheduled_date": "2026-08-05T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def record_inspection_result_payload(**overrides) -> dict:
    defaults = {
        "outcome": "PASSED",
        "occurred_at": "2026-08-05T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_meter_reading_payload(service_account_id, expected_account_version,
                                 **overrides) -> dict:
    defaults = {
        "service_account_id": service_account_id,
        "period_start": "2026-08-01T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "import_wh": 500_000,
        "export_wh": 800_000,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_annual_reconciliation_payload(service_account_id, **overrides) -> dict:
    defaults = {
        "service_account_id": service_account_id,
        "reconciliation_year": 2026,
    }
    defaults.update(overrides)
    return defaults
