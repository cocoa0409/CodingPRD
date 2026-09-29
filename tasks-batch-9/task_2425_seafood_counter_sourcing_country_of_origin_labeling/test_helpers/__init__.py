"""Test helpers for the Seafood Counter Cool Ops API.

Re-exports the framework generics alongside this domain's client, error
catalogue, payload factories, entity assertions, constants, role headers and
composite setup chains.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import assertions, constants, factories, fixtures, types
from .api_client import MOUNT, ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    ASSOCIATE_USER_ID,
    CHAIN_ADMIN_USER_ID,
    MERCH_LEAD_USER_ID,
    OFFICER_CLAIM_USER_ID,
    OFFICER_COLD_USER_ID,
    OFFICER_COOL_USER_ID,
    OFFICER_LEDGER_USER_ID,
    OFFICER_READ_USER_ID,
    OFFICER_SAMPLING_USER_ID,
    OFFICER_SIMP_USER_ID,
    TEST_USERS,
    headers_without_role,
    headers_without_user_id,
    make_chain_admin_headers,
    make_compliance_officer_headers,
    make_merchandising_lead_headers,
    make_seafood_manager_headers,
    make_supplier_rep_headers,
)

__all__ = [
    # Framework generics
    "GenericApiClient",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "get_success_data",
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    "build_user_headers",
    "NON_EXISTENT_UUID",
    # Domain modules
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    # Client and errors
    "ApiClient",
    "api_client",
    "MOUNT",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    # Identities
    "TEST_USERS",
    "CHAIN_ADMIN_USER_ID",
    "OFFICER_SAMPLING_USER_ID",
    "OFFICER_COOL_USER_ID",
    "OFFICER_CLAIM_USER_ID",
    "OFFICER_SIMP_USER_ID",
    "OFFICER_LEDGER_USER_ID",
    "OFFICER_COLD_USER_ID",
    "OFFICER_READ_USER_ID",
    "MERCH_LEAD_USER_ID",
    "ASSOCIATE_USER_ID",
    "make_chain_admin_headers",
    "make_compliance_officer_headers",
    "make_merchandising_lead_headers",
    "make_seafood_manager_headers",
    "make_supplier_rep_headers",
    "headers_without_user_id",
    "headers_without_role",
]
