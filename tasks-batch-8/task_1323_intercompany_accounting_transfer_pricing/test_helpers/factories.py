"""Payload factories — one per resource, input fields only (PRD section 4)."""
from .constants import (
    DEFAULT_EFFECTIVE_FROM,
    DEFAULT_EFFECTIVE_TO,
    DEFAULT_GROUP_REVENUE_EUR,
    DEFAULT_MARKUP_BP,
    DEFAULT_YEAR_INDEX,
    STUDY_COMPARABLES_BP,
)


def create_fiscal_year_payload(**overrides) -> dict:
    defaults = {
        "year_index": DEFAULT_YEAR_INDEX,
        "group_revenue_eur": DEFAULT_GROUP_REVENUE_EUR,
    }
    defaults.update(overrides)
    return defaults


def create_legal_entity_payload(**overrides) -> dict:
    defaults = {
        "name": "USCo",
        "country_code": "US",
        "functional_currency": "USD",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(provider_entity_id, recipient_entity_id,
                             benchmarking_study_id, **overrides) -> dict:
    defaults = {
        "provider_entity_id": provider_entity_id,
        "recipient_entity_id": recipient_entity_id,
        "transaction_type": "SERVICES",
        "pricing_method": "COST_PLUS",
        "markup_bp": DEFAULT_MARKUP_BP,
        "true_up_method": "TO_MEDIAN",
        "benchmarking_study_id": benchmarking_study_id,
        "effective_from": DEFAULT_EFFECTIVE_FROM,
        "effective_to": DEFAULT_EFFECTIVE_TO,
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(agreement_id, fiscal_year_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "fiscal_year_id": fiscal_year_id,
        "cost_base_cents": 1_000_000,
        "provider_revenue_cents": 1_020_000,
        "recipient_cost_cents": 1_020_000,
    }
    defaults.update(overrides)
    return defaults


def create_true_up_run_payload(agreement_id, fiscal_year_id,
                               **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "fiscal_year_id": fiscal_year_id,
    }
    defaults.update(overrides)
    return defaults


def create_benchmarking_study_payload(**overrides) -> dict:
    defaults = {
        "transaction_type": "SERVICES",
        "region": "EU",
        "vintage_year": DEFAULT_YEAR_INDEX,
        "comparables_bp": list(STUDY_COMPARABLES_BP),
    }
    defaults.update(overrides)
    return defaults


def create_refresh_payload(comparables_bp, expected_study_version) -> dict:
    return {
        "comparables_bp": list(comparables_bp),
        "expected_study_version": expected_study_version,
    }


def create_doc_package_payload(fiscal_year_id, doc_type, entity_id=None,
                               **overrides) -> dict:
    # MASTER_FILE and CBC_REPORT must not carry entity_id at all (PRD 3.6),
    # so the key is included only when an entity is actually supplied.
    defaults = {
        "fiscal_year_id": fiscal_year_id,
        "doc_type": doc_type,
    }
    if entity_id is not None:
        defaults["entity_id"] = entity_id
    defaults.update(overrides)
    return defaults


def create_audit_case_payload(entity_id, case_type, authority_country="US",
                              covered_year_indexes=None, **overrides) -> dict:
    # covered_year_indexes is required for APA and omitted for AUDIT.
    defaults = {
        "entity_id": entity_id,
        "case_type": case_type,
        "authority_country": authority_country,
    }
    if covered_year_indexes is not None:
        defaults["covered_year_indexes"] = list(covered_year_indexes)
    defaults.update(overrides)
    return defaults


def create_cash_pool_payload(fiscal_year_id, **overrides) -> dict:
    defaults = {
        "fiscal_year_id": fiscal_year_id,
        "interest_method": "AVERAGE_BALANCE",
        "admin_fee_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_sweep_payload(movements, expected_cash_pool_version) -> dict:
    return {
        "movements": [dict(m) for m in movements],
        "expected_cash_pool_version": expected_cash_pool_version,
    }


def create_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
