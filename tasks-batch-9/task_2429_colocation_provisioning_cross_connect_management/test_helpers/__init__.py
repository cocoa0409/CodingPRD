"""Test helpers for the colocation provisioning PRD.

Generic plumbing (envelope validation, race helpers, header building) comes from
``prd_bench_local_runner.testing``; everything re-exported below that is
PRD-specific lives in this package.
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
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_access_visit,
    assert_amount_equals,
    assert_authorized_contact,
    assert_cabinet,
    assert_cabinet_power,
    assert_circuit_power,
    assert_common_fields,
    assert_contract,
    assert_contract_billing_rollup,
    assert_contract_power_rollup,
    assert_cross_connect_order,
    assert_customer,
    assert_decommission_order,
    assert_fields_present,
    assert_floor_row,
    assert_invoice_line,
    assert_invoice_line_values,
    assert_kw_equals,
    assert_kw_precision,
    assert_ledger_common_fields,
    assert_patch_panel_port,
    assert_power_circuit,
    assert_remote_hands_ticket,
    assert_row_capacity_view,
    assert_ticket_labor,
    assert_timestamps_unchanged,
    assert_unit_rate_precision,
    assert_usd_precision,
    assert_version_is,
    find_lines,
    one_line,
    round_half_up,
)
from .constants import DEFAULT_CLOCK, DEFAULT_LIMIT, MAX_LIMIT, MIN_LIMIT
from .test_users import (
    BILLING_OPERATOR,
    BILLING_OPERATOR_1_ID,
    BILLING_OPERATOR_2,
    BILLING_OPERATOR_2_ID,
    ENGINEER_1,
    ENGINEER_1_ID,
    ENGINEER_2,
    ENGINEER_2_ID,
    ENGINEER_3,
    ENGINEER_3_ID,
    FACILITY_MANAGER,
    FACILITY_MANAGER_1_ID,
    FACILITY_MANAGER_2,
    FACILITY_MANAGER_2_ID,
    FOREIGN_CUSTOMER_ADMIN_ID,
    NO_ROLE_HEADERS,
    SECURITY_OFFICER,
    SECURITY_OFFICER_1_ID,
    SECURITY_OFFICER_2,
    SECURITY_OFFICER_2_ID,
    TEST_USERS,
    UNKNOWN_ROLE_HEADERS,
    make_billing_operator_headers,
    make_customer_admin_headers,
    make_facility_manager_headers,
    make_provisioning_engineer_headers,
    make_security_officer_headers,
)
from .types import UserRole

__all__ = [
    # framework re-exports
    "NON_EXISTENT_UUID",
    "GenericApiClient",
    "assert_at_least_one_succeeds",
    "assert_cost_precision",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "build_user_headers",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
    # modules
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    # client and errors
    "ApiClient",
    "api_client",
    "ApiErrorId",
    "HTTP_STATUS_CODES",
    # constants
    "DEFAULT_CLOCK",
    "DEFAULT_LIMIT",
    "MAX_LIMIT",
    "MIN_LIMIT",
    # identities
    "TEST_USERS",
    "NO_ROLE_HEADERS",
    "UNKNOWN_ROLE_HEADERS",
    "UserRole",
]
