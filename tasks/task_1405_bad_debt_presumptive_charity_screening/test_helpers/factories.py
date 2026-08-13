"""Payload factories — one per entity, input fields only (PRD §3 narratives).

patient_mrn is unique per unit (PRD §3.1), so factories mint unique MRNs and
patient names per call unless overridden.
"""
import itertools

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_account_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "patient_mrn": f"MRN-{n:06d}",
        "patient_name": f"Test Patient {n}",
        "original_balance_cents": 100000,
        "guarantor_liability_date": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_screening_payload(account_id, expected_account_version, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "screening_model": "FPL_TIERED",
        "household_size": 1,
        "household_income_cents": 1000000,
        "expected_account_version": expected_account_version,
    }
    defaults.update(overrides)
    return defaults


def create_early_out_placement_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "vendor_name": "VENDOR_A",
        "contingency_fee_bps": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_agency_placement_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "agency_name": "AGENCY_X",
        "contingency_fee_bps": 2000,
    }
    defaults.update(overrides)
    return defaults


def file_dispute_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "dispute_reason": "Patient disputes the balance",
        "dispute_amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def resolve_dispute_payload(**overrides) -> dict:
    defaults = {"resolution_outcome": "UPHELD_PROVIDER"}
    defaults.update(overrides)
    return defaults


def create_payment_plan_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "installment_amount_cents": 50000,
        "installment_count": 2,
        "first_installment_due": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults


def create_write_off_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "write_off_kind": "BAD_DEBT",
        "medicare_cost_report_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def approve_write_off_payload(expected_account_version, **overrides) -> dict:
    defaults = {"expected_account_version": expected_account_version}
    defaults.update(overrides)
    return defaults


def post_recovery_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "payment_kind": "LUMP_SUM",
        "amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_snapshot_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "VENDOR_A",
        "snapshot_period_start": "2026-01-01",
        "snapshot_period_end": "2026-02-01",
    }
    defaults.update(overrides)
    return defaults
