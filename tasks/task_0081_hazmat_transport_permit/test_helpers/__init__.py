"""Barrel export for the hazmat-transport-permit test infrastructure.

Re-exports the generic framework utilities from `prd_bench_local_runner.testing`
alongside the PRD-specific domain code in this package, so test files can use
a single import source:

    from test_helpers import (
        validate_success, validate_error, validate_paginated, ...,
        api_client, ApiClient,
        ApiErrorId, HTTP_STATUS_CODES,
        CONSTANTS, ...,
        company_operator_headers, driver_headers, regulator_headers, test_harness_headers,
        create_company_payload, create_driver_payload, ...,
        fixture_qualified_company, fixture_active_permit, ...,
        assert_company, assert_driver, assert_permit, ...,
        assert_wallet_conservation, assert_points_conservation,
    )
"""

# Framework re-exports.
from prd_bench_local_runner.testing import (
    GenericApiClient,
    validate_success,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    get_success_data,
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
    build_user_headers,
    NON_EXISTENT_UUID,
)

# Domain re-exports.  Each * import is the module's public name list (the names
# the module's top-level statements bind without a leading underscore).
from .types import *  # noqa: F401,F403
from .api_client import ApiClient, api_client  # noqa: F401
from .api_errors import ApiErrorId, HTTP_STATUS_CODES  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    TEST_USERS,
    OPAQUE_REGULATOR_ID,
    OPAQUE_TEST_HARNESS_ID,
    BOOTSTRAP_COMPANY_OPERATOR_ID,
    BOOTSTRAP_DRIVER_ID,
    company_operator_headers,
    driver_headers,
    regulator_headers,
    test_harness_headers,
    bootstrap_company_operator_headers,
    headers_for_role,
    ROLE_NAMES,
)
from .fixtures import *  # noqa: F401,F403
