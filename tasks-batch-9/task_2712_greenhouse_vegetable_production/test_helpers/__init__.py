"""Test infrastructure for the greenhouse vegetable production service.

Importing this package re-exports everything a test file needs: the framework
validators, the typed API client, the error catalogue, the domain assertions,
the payload factories, the named constants, the role headers and the composite
setup helpers.
"""

from prd_bench_local_runner.testing import (
    GenericApiClient,
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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (
    TEST_USERS,
    UNKNOWN_WORKER_USER_ID,
    headers_without_role,
    headers_without_user_id,
    make_grower_manager_headers,
    make_harvest_supervisor_headers,
    make_ipm_coordinator_headers,
    make_ipm_scout_headers,
    make_irrigation_tech_headers,
    make_quality_inspector_headers,
)
from .types import *  # noqa: F401,F403
