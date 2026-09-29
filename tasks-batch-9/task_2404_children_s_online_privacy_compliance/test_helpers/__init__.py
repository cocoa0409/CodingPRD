"""Test helpers for the Children's Online Privacy Compliance API.

Re-exports the framework generics alongside the PRD-specific client, error
catalogue, assertions, factories, constants and composite fixtures, so a test
module needs a single import site.
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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    ASSESSOR_HEADERS,
    CERTIFIER_HEADERS,
    ENGINEER_HEADERS,
    OFFICER_HEADERS,
    TEST_USERS,
    headers_with_undeclared_role,
    headers_without_role,
    headers_without_user_id,
    make_assessor_headers,
    make_certifier_headers,
    make_engineer_headers,
    make_officer_headers,
    make_parent_headers,
)
from .types import *  # noqa: F401,F403
