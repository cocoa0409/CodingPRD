"""Payload factories — one per entity, input fields only.

Each factory provides sensible defaults and accepts **overrides. Optional
fields with server-side defaults (pp_valuation_method, billing_mode,
deductible_waived, interest_type, method) are omitted from the defaults unless
the caller supplies them, so that "omitted -> default" behavior can be tested.
"""
from .constants import (
    LIAB_LIMIT_CENTS,
    LOU_LIMIT_CENTS,
    PP_LIMIT_CENTS,
)


def create_policyholder_payload(**overrides) -> dict:
    defaults = {
        "email": "holder@example.com",
        "full_name": "Test Holder",
        "mailing_address": "1 Test Street",
    }
    defaults.update(overrides)
    return defaults


def create_bundle_payload(policyholder_id, **overrides) -> dict:
    defaults = {
        "policyholder_id": policyholder_id,
        "name": "Home+Auto",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(policyholder_id, **overrides) -> dict:
    defaults = {
        "policyholder_id": policyholder_id,
        "insured_address": "100 Rental Ave",
        "territory_code": "STANDARD",
        "effective_date": "2026-01-01T00:00:00Z",
        "expiry_date": "2027-01-01T00:00:00Z",
        "deductible_cents": 25000,
    }
    defaults.update(overrides)
    return defaults


def add_coverage_line_payload(coverage_type, limit_cents, expected_policy_version,
                              **overrides) -> dict:
    defaults = {
        "coverage_type": coverage_type,
        "limit_cents": limit_cents,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def add_scheduled_item_payload(appraised_value_cents, expected_policy_version,
                               **overrides) -> dict:
    defaults = {
        "description": "engagement ring",
        "appraised_value_cents": appraised_value_cents,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def add_additional_insured_payload(party_name="Acme Realty",
                                   notify_email="landlord@example.com",
                                   **overrides) -> dict:
    defaults = {
        "party_name": party_name,
        "notify_email": notify_email,
    }
    defaults.update(overrides)
    return defaults


def file_claim_payload(loss_type, loss_date, **overrides) -> dict:
    defaults = {
        "loss_type": loss_type,
        "loss_date": loss_date,
    }
    defaults.update(overrides)
    return defaults


def add_claim_item_payload(coverage_line_id, replacement_cost_cents, **overrides) -> dict:
    defaults = {
        "coverage_line_id": coverage_line_id,
        "replacement_cost_cents": replacement_cost_cents,
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(amount_cents, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


# The three coverage limits that produce a fully-covered STANDARD policy
# (used by fixtures and several tests).
FULL_COVERAGE = (
    ("PERSONAL_PROPERTY", PP_LIMIT_CENTS),
    ("LIABILITY", LIAB_LIMIT_CENTS),
    ("LOSS_OF_USE", LOU_LIMIT_CENTS),
)
