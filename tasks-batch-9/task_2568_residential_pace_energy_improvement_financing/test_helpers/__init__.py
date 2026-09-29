"""Test infrastructure for the residential PACE energy-improvement financing API.

Importing this package registers the program's error/status map with the
framework validators, so any module that pulls in a helper gets accurate status
assertions for free.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users
from .api_client import PaceApiClient
from .assertions import (
    annuity_factor,
    admin_fee_cents,
    assert_absent_or_none,
    assert_contractor_ledger,
    assert_fee_decomposition,
    assert_fields,
    assert_installment_row,
    assert_page_meta,
    assert_parcel_exposure,
    assert_payoff_composition,
    assert_resource_envelope,
    assert_schedule_conserves_principal,
    assert_total_count,
    assert_version,
    expect_created,
    expect_error,
    expect_ok,
    expect_one_of,
    expect_page,
    find_installment,
    ids_of,
    present_value_of_savings,
    round_half_up,
    sir_bps,
)

__all__ = [
    "PaceApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "admin_fee_cents",
    "annuity_factor",
    "assert_absent_or_none",
    "assert_contractor_ledger",
    "assert_fee_decomposition",
    "assert_fields",
    "assert_installment_row",
    "assert_page_meta",
    "assert_parcel_exposure",
    "assert_payoff_composition",
    "assert_resource_envelope",
    "assert_schedule_conserves_principal",
    "assert_total_count",
    "assert_version",
    "expect_created",
    "expect_error",
    "expect_ok",
    "expect_one_of",
    "expect_page",
    "find_installment",
    "ids_of",
    "present_value_of_savings",
    "round_half_up",
    "sir_bps",
]
