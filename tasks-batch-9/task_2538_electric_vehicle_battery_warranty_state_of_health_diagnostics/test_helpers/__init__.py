"""Barrel export: framework generics plus this API's domain code."""

# Framework generics, re-exported so tests have a single import source.
from prd_bench_local_runner.testing import (  # noqa: F401
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

from .api_client import PREFIX, ApiClient, api_client  # noqa: F401
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .fixtures import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ADJUDICATOR_1_ID,
    ADJUDICATOR_2_ID,
    GATEWAY_ID,
    LAB_ID,
    LIAISON_ID,
    NO_HEADERS,
    PROGRAM_ADMIN_ID,
    TEST_USERS,
    headers_without_actor,
    headers_without_role,
    make_adjudicator_headers,
    make_gateway_headers,
    make_lab_headers,
    make_liaison_headers,
    make_owner_headers,
    make_program_admin_headers,
    make_technician_headers,
)
from .types import *  # noqa: F401,F403
