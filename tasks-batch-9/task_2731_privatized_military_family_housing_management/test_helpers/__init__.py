"""Test helpers for the privatized military family housing API.

Importing this package registers the error-id → HTTP status map with the
framework validators, so ``validate_error`` checks the status code as well as
the error id.
"""

from prd_bench_local_runner.testing import (  # noqa: F401
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_cost_precision,
    assert_at_least_one_succeeds,
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

from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient, api_client, canonical_instant  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .test_users import (  # noqa: F401
    ALL_ROLE_NAMES,
    TEST_USERS,
    make_environmental_specialist_headers,
    make_installation_housing_office_headers,
    make_maintenance_tech_headers,
    make_platform_admin_headers,
    make_property_manager_headers,
    make_service_member_headers,
)
