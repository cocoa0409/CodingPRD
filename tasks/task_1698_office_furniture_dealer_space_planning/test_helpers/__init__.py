"""Barrel export: framework generics + PRD-specific code."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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

# PRD-specific
from .types import *
from .api_client import ApiClient, api_client
from .api_errors import ApiErrorId, HTTP_STATUS_CODES
from .assertions import *
from .factories import *
from .constants import *
from .test_users import (
    NO_AUTH_HEADERS,
    TEST_USERS,
    USER_ACCOUNT_EXECUTIVE,
    USER_CLAIMS_COORDINATOR,
    USER_CLIENT_APPROVER,
    USER_CONTRACTS_OFFICER,
    USER_CONTRACTS_OFFICER_2,
    USER_DEALER_ADMIN,
    USER_DESIGNER,
    USER_FINANCE_MANAGER,
    USER_LIQUIDATION_APPRAISER,
    USER_MANUFACTURER_REP,
    USER_PROJECT_MANAGER,
    USER_WAREHOUSE_LEAD,
    make_account_executive_headers,
    make_claims_coordinator_headers,
    make_client_approver_headers,
    make_contracts_officer_headers,
    make_dealer_admin_headers,
    make_designer_headers,
    make_finance_manager_headers,
    make_liquidation_appraiser_headers,
    make_manufacturer_rep_headers,
    make_project_manager_headers,
    make_warehouse_lead_headers,
)
from .fixtures import *
